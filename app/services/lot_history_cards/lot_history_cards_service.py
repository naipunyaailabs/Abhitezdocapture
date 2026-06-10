"""
Lot History Cards Extraction Service — Vision LLM extraction for the
Abhitex International "LOT HISTORY CARD — GREY FOLDING" (QMS/REC/115) form.

Each card is ONE document (not a row register). It carries a small set of
header fields plus up to three "ROPE" blocks, each holding a variable-length
list of rolls. The roll lists differ in length per rope, so this service does
NOT use the fixed-row register pipeline — it asks the vision model for the
whole card as a structured object.

Extracted per card:
    Header  : I.O. No, Dye Lot No, Shade No, Quality M.No
    Rope 1  : list of { Roll No, Total Pcs, Wt (kg), Code }
    Rope 2  : list of { Roll No, Total Pcs, Wt (kg), Code }
    Rope 3  : list of { Roll No, Total Pcs, Wt (kg), Code }

The "Code" column on the form is the small "Code" sub-label sitting above the
Length (Mtrs.) column — the numeric code written there (e.g. 119477, 118156,
104213). Designed to scale to thousands of cards: one vision call per page,
no template picking, stateless.
"""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, List, Optional

from PIL import Image

from app.services.llm_service import llm_service
from app.services.register_extractor.register_service import register_extractor_service
from app.services.register_extractor.ocr_engine import parse_llm_json
from app.services.lot_history_cards import confidence as confidence_scorer


# Header field keys (kept stable — frontend + export depend on them).
HEADER_FIELDS: List[str] = [
    "I.O. No",
    "Dye Lot No",
    "Shade No",
    "Quality M.No",
]

# Per-roll column keys inside every rope block.
ROPE_COLUMNS: List[str] = [
    "Roll No",
    "Total Pcs",
    "Wt (kg)",
    "Code",
]

ROPE_KEYS: List[str] = ["Rope 1", "Rope 2", "Rope 3"]


LOT_CARD_SYSTEM = (
    "You are an OCR specialist for Indian textile factory handwritten forms.\n"
    "You read ONE 'ABHITEX INTERNATIONAL — LOT HISTORY CARD (GREY FOLDING)' form.\n"
    "Your ONLY job is to READ what is written and return it as strict JSON.\n\n"

    "FORM LAYOUT:\n"
    "- A top info row with labelled boxes: I.O. No, PARTY NAME, DYE LOT NO,\n"
    "  SHADE NAME, SHADE No, STYLE, QUALITY M.No.\n"
    "- Below it, THREE side-by-side blocks titled 'ROPE - 1', 'ROPE - 2',\n"
    "  'ROPE - 3'. Each block is a small table with these columns, left to right:\n"
    "    Roll No | Size | Total Pcs. | Wt. (K.G.) | Length (Mtrs.)\n"
    "  A tiny hand-written 'Code' label sits above the 'Length (Mtrs.)' column;\n"
    "  the number written in that column is the CODE (e.g. 119477, 118156,\n"
    "  104213). Treat that column's value as the 'Code'.\n\n"

    "WHAT TO EXTRACT (ignore every other field):\n"
    "  HEADER: I.O. No, Dye Lot No, Shade No, Quality M.No\n"
    "  For EACH rope block, one entry per data row that has a Roll No:\n"
    "    Roll No, Total Pcs (the 'Total Pcs.' column),\n"
    "    Wt (kg) (the 'Wt. (K.G.)' column), Code (the Length/Code column number).\n\n"

    "COLUMN & BLOCK ALIGNMENT — THIS IS THE MOST COMMON MISTAKE, READ TWICE:\n"
    "- The three ROPE blocks sit SIDE BY SIDE. Treat each block as a SEPARATE,\n"
    "  ISOLATED table. NEVER take a value from one rope block into another. A\n"
    "  number physically printed inside the Rope-2 area belongs to Rope 2 ONLY;\n"
    "  it must NOT appear anywhere in Rope 1 or Rope 3 (and vice-versa). If the\n"
    "  Code/Length cell of a Rope-1 row looks empty or unclear, leave it \"\" —\n"
    "  do NOT borrow the Roll No or any value from the Rope-2 block to its right.\n"
    "- Within ONE block the columns are, strictly left to right:\n"
    "    [Roll No] [Size] [Total Pcs.] [Wt. (K.G.)] [Length/Code]\n"
    "  Read STRAIGHT DOWN one column before moving to the next. Each field MUST\n"
    "  come from its OWN column position:\n"
    "    * 'Roll No' = ONLY the leftmost column of that block. It is the roll's\n"
    "      identifier (a few digits, sometimes short like 3 or 34, and it MAY end\n"
    "      in a trailing letter such as A). NEVER put a Total Pcs / Wt / Size\n"
    "      value into Roll No. If the leftmost cell is blank, Roll No is \"\".\n"
    "    * 'Total Pcs' = ONLY the 3rd column. 'Wt (kg)' = ONLY the 4th column.\n"
    "    * 'Code' = ONLY the rightmost (Length/Code) column of THIS block.\n"
    "- Do NOT shift a column: if the Roll No column for a row is hard to read,\n"
    "  still read it from the leftmost column — do NOT slide the Total Pcs value\n"
    "  left into Roll No. Roll No and Total Pcs are DIFFERENT columns and usually\n"
    "  DIFFERENT numbers; if you output the same number for both, you mis-aligned.\n"
    "- Sanity check before output: within a block, the Roll No column and the\n"
    "  Total Pcs column must come from two different vertical lines on the form.\n\n"

    "VALUE PATTERNS — the numbers in parentheses below are ILLUSTRATIVE SHAPE\n"
    "EXAMPLES ONLY. They are NOT data from this card and they are NOT from any\n"
    "previous card. NEVER copy an example value into your output. They only show\n"
    "you the typical length/format. Read the ACTUAL ink on THIS image:\n"
    "- I.O. No: 5 digits, sometimes with a suffix like 81839-4.\n"
    "- Dye Lot No: 4-5 digits.\n"
    "- Shade No: 4-5 digits or blank.\n"
    "- Quality M.No: a single small number (one or two digits) — read the number\n"
    "  next to the QUALITY M.No label, not the letters.\n"
    "- Roll No: usually 4-5 digits, sometimes short (1-2 digits), and may end in\n"
    "  a trailing letter.\n"
    "- Total Pcs: whole numbers (e.g. 120, 176, 372, 732).\n"
    "- Wt (kg): whole numbers (e.g. 88, 122, 78, 49).\n"
    "- Code: 5-6 digits (e.g. 119477, 118156, 104213, 106794).\n\n"

    "DIGIT DISAMBIGUATION — read carefully, do NOT confuse these:\n"
    "- '7' vs '1': In this Indian handwriting a '7' is written with a flat top\n"
    "  stroke (a horizontal bar) and a long diagonal going down to the left,\n"
    "  often with a small cross-stroke through the middle. A '1' is just a\n"
    "  single near-vertical stroke (sometimes with a tiny top flag and a base\n"
    "  serif). If the figure has a clear horizontal TOP bar or a slanted body,\n"
    "  it is a '7', NOT a '1'. A weight like '78' is far more typical than '18'\n"
    "  for these rolls — when a Wt value's first digit has any top bar/slant,\n"
    "  read it as 7. Do not collapse '7' into '1'.\n"
    "- '1' vs '7': conversely, only read '1' when the stroke is a plain vertical\n"
    "  with no horizontal top bar and no diagonal slant.\n"
    "- '0' vs '6' vs '8': a closed loop with a tail/opening = 6; two stacked\n"
    "  loops = 8; a single clean oval = 0.\n"
    "- '4' vs '9': an open top with a crossing stroke = 4; a closed top loop\n"
    "  over a stem = 9.\n"
    "- Cross-check digits against the column's own bottom TOTAL row when one is\n"
    "  printed (e.g. the Wt total): your read of each cell should be consistent\n"
    "  with that sum. If reading a first digit as '1' would make the column not\n"
    "  add up but reading it as '7' would, it is a '7'.\n\n"

    "CRITICAL RULES:\n"
    "1. ONLY output what you ACTUALLY SEE on THIS image. Do NOT invent, compute,\n"
    "   guess, or recall. Treat each card in COMPLETE ISOLATION: you have no\n"
    "   memory of any other card. Do NOT reuse a value because it appeared on a\n"
    "   previous document or because it looks like an example in these rules.\n"
    "2. Read every roll row in each rope block, top to bottom. The number of\n"
    "   rows differs between Rope 1, Rope 2 and Rope 3.\n"
    "3. Do NOT include the bottom 'total' summary row (the row that only holds\n"
    "   a Total-Pcs sum and a Wt sum with no Roll No) as a roll entry. INSTEAD,\n"
    "   read that printed total row separately into the 'totals' object for that\n"
    "   rope: its Total Pcs sum and its Wt sum exactly as written on the card\n"
    "   (e.g. the cell showing '480  368' means Total Pcs total=480, Wt total=\n"
    "   368). If no total row is printed for a rope, use \"\" for its totals.\n"
    "4. If a rope block is entirely empty, return an empty list for its rolls.\n"
    "5. Preserve digits exactly. Do NOT strip leading parts or merge separators.\n"
    "6. If a single field is unreadable or blank, output an empty string \"\".\n"
    "   NEVER fill an unreadable cell with an example value from these rules or\n"
    "   with a value remembered from another row, rope, or document. An empty\n"
    "   string is ALWAYS correct for something you cannot read; a made-up or\n"
    "   borrowed number is always wrong.\n\n"

    "OUTPUT — return ONLY this JSON object, no prose, no markdown fences.\n"
    "Each rope is an object with a 'rolls' list and a 'totals' object:\n"
    "{\n"
    "  \"header\": {\n"
    "    \"I.O. No\": \"\", \"Dye Lot No\": \"\", \"Shade No\": \"\", \"Quality M.No\": \"\"\n"
    "  },\n"
    "  \"Rope 1\": {\n"
    "    \"rolls\": [ {\"Roll No\": \"\", \"Total Pcs\": \"\", \"Wt (kg)\": \"\", \"Code\": \"\"} ],\n"
    "    \"totals\": {\"Total Pcs\": \"\", \"Wt (kg)\": \"\"}\n"
    "  },\n"
    "  \"Rope 2\": { ... same shape ... },\n"
    "  \"Rope 3\": { ... same shape ... }\n"
    "}"
)

LOT_CARD_USER = (
    "Read this LOT HISTORY CARD. Extract the header fields (I.O. No, Dye Lot No, "
    "Shade No, Quality M.No) and, for each of Rope 1, Rope 2 and Rope 3, list "
    "every roll row (Roll No, Total Pcs, Wt (kg), Code) under 'rolls', and read "
    "the printed bottom total row (Total Pcs sum and Wt sum) into 'totals'. "
    "Return only the JSON object described."
)


# ── Cropped-region prompts ──────────────────────────────────────────────────
# To make cross-block bleed physically impossible, each card is cropped into a
# header strip and three single-rope strips; each crop is read in ISOLATION, so
# the model never sees a neighbouring rope's columns.

HEADER_CROP_SYSTEM = (
    "You are an OCR specialist for Indian textile factory handwritten forms.\n"
    "You are shown ONLY the TOP INFO STRIP of an 'ABHITEX INTERNATIONAL — LOT\n"
    "HISTORY CARD' form: a row of labelled boxes (I.O. No, PARTY NAME, DYE LOT\n"
    "NO, SHADE NAME, SHADE No, STYLE, QUALITY M.No).\n\n"
    "Extract ONLY these four fields, reading the actual ink in THIS image:\n"
    "  I.O. No        — the number under the 'I.O. No' box (4-6 digits).\n"
    "  Dye Lot No     — the number under 'DYE LOT NO' (4-5 digits).\n"
    "  Shade No       — the number under 'SHADE No' (digits) or blank.\n"
    "  Quality M.No   — the small number under 'QUALITY M.No' (1-2 digits).\n\n"
    "RULES:\n"
    "1. ONLY output what you ACTUALLY SEE here. Do NOT invent, guess, or recall\n"
    "   any value from another card. You have no memory of other documents.\n"
    "2. If a field is unreadable or blank, output an empty string \"\".\n\n"
    "OUTPUT — ONLY this JSON, no prose, no markdown fences:\n"
    "{ \"I.O. No\": \"\", \"Dye Lot No\": \"\", \"Shade No\": \"\", \"Quality M.No\": \"\" }"
)

HEADER_CROP_USER = (
    "Read the four header fields (I.O. No, Dye Lot No, Shade No, Quality M.No) "
    "from this top strip and return only the JSON object."
)

ROPE_CROP_SYSTEM = (
    "You are an OCR specialist for Indian textile factory handwritten forms.\n"
    "You are shown ONLY ONE 'ROPE' block cropped from an ABHITEX LOT HISTORY\n"
    "CARD. This is a SINGLE small table. There are NO other rope blocks in this\n"
    "image — read ONLY what is inside it.\n\n"

    "The table columns, strictly LEFT to RIGHT, are:\n"
    "  Roll No | Size | Total Pcs. | Wt. (K.G.) | Length (Mtrs.)\n"
    "A tiny 'Code' label sits above the last (Length/Mtrs.) column; the number\n"
    "written in that last column is the CODE.\n\n"

    "Extract, for EVERY data row that has a Roll No (top to bottom):\n"
    "  Roll No   — the LEFTMOST column only (a few digits, may end in a letter).\n"
    "  Total Pcs — the 'Total Pcs.' (3rd) column only.\n"
    "  Wt (kg)   — the 'Wt. (K.G.)' (4th) column only.\n"
    "  Code      — the LAST (Length/Code) column only.\n\n"

    "Also read the printed bottom TOTAL row (a row with column SUMS and no Roll\n"
    "No, e.g. a cell showing two numbers like the Total-Pcs sum and the Wt sum)\n"
    "into 'totals'. Do NOT list that total row as a roll.\n\n"

    "CRITICAL:\n"
    "1. ONLY output what you ACTUALLY SEE in THIS crop. Do NOT invent, compute,\n"
    "   guess, or recall values from another rope, row, or document.\n"
    "2. Each field MUST come from its OWN column. NEVER slide the Total Pcs value\n"
    "   into Roll No. Roll No and Total Pcs are different columns and usually\n"
    "   different numbers; if you output the same number for both, you misread.\n"
    "3. DIGIT shapes: a '7' has a flat TOP bar and a diagonal/cross stroke; a '1'\n"
    "   is a plain vertical. Read a top-bar/slant first digit as 7, not 1.\n"
    "4. If a cell is unreadable or blank, output \"\" — never a remembered value.\n\n"

    "OUTPUT — ONLY this JSON, no prose, no markdown fences:\n"
    "{\n"
    "  \"rolls\": [ {\"Roll No\": \"\", \"Total Pcs\": \"\", \"Wt (kg)\": \"\", \"Code\": \"\"} ],\n"
    "  \"totals\": {\"Total Pcs\": \"\", \"Wt (kg)\": \"\"}\n"
    "}"
)

ROPE_CROP_USER = (
    "Read every roll row in THIS single rope block (Roll No, Total Pcs, Wt (kg), "
    "Code) and its printed total row. Return only the JSON object described."
)


def _clean(val: Any) -> str:
    """Coerce any model value to a trimmed string."""
    if val is None:
        return ""
    return str(val).strip()


def _normalize_rope(raw: Any) -> Dict[str, Any]:
    """Coerce a rope block into {'rolls': [...], 'totals': {...}}.

    Accepts both the new object shape {rolls, totals} and the older bare-list
    shape (rolls only), so cached/old responses still parse.
    """
    rolls_src: Any = raw
    totals_src: Any = None
    if isinstance(raw, dict):
        rolls_src = raw.get("rolls", [])
        totals_src = raw.get("totals")

    rolls: List[Dict[str, str]] = []
    if isinstance(rolls_src, list):
        for item in rolls_src:
            if not isinstance(item, dict):
                continue
            row = {col: _clean(item.get(col)) for col in ROPE_COLUMNS}
            # Skip rows with nothing useful in them.
            if not any(row.values()):
                continue
            rolls.append(row)

    totals = {"Total Pcs": "", "Wt (kg)": ""}
    if isinstance(totals_src, dict):
        totals["Total Pcs"] = _clean(totals_src.get("Total Pcs"))
        totals["Wt (kg)"] = _clean(totals_src.get("Wt (kg)"))

    return {"rolls": rolls, "totals": totals}


def _normalize_header(raw: Any) -> Dict[str, str]:
    header = {field: "" for field in HEADER_FIELDS}
    if isinstance(raw, dict):
        for field in HEADER_FIELDS:
            header[field] = _clean(raw.get(field))
    return header


# ── Crop geometry ───────────────────────────────────────────────────────────
# Fractions of the card image. The header info strip sits across the top; the
# three rope blocks occupy equal horizontal thirds of the area below it. We give
# each rope strip a small horizontal overlap so a block's rightmost Code column
# is never sliced off, and start the strips slightly above the rope tables so
# the 'ROPE - n' titles are included for orientation.
HEADER_TOP = 0.0
HEADER_BOTTOM = 0.22          # top ~22% = the labelled header boxes
ROPE_AREA_TOP = 0.20          # rope tables begin a little below the header
ROPE_AREA_BOTTOM = 1.0
ROPE_OVERLAP = 0.03           # horizontal padding added to each third


def _b64_to_image(img_base64: str) -> Optional[Image.Image]:
    try:
        return Image.open(io.BytesIO(base64.b64decode(img_base64)))
    except Exception as exc:
        print(f"[LotHistoryCards] crop decode failed: {exc}")
        return None


def _crop_b64(img: Image.Image, left: float, top: float, right: float, bottom: float) -> str:
    """Crop by fractional box and return base64 PNG."""
    w, h = img.size
    box = (
        int(max(0.0, left) * w),
        int(max(0.0, top) * h),
        int(min(1.0, right) * w),
        int(min(1.0, bottom) * h),
    )
    crop = img.crop(box)
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _crop_card_regions(img_base64: str) -> Optional[Dict[str, Any]]:
    """Split a card image into a header crop and three single-rope crops.

    Returns {"header": b64, "ropes": [b64, b64, b64]} or None if the image
    cannot be decoded (caller then falls back to the whole-image read).
    """
    img = _b64_to_image(img_base64)
    if img is None:
        return None
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    header_b64 = _crop_b64(img, 0.0, HEADER_TOP, 1.0, HEADER_BOTTOM)

    rope_crops: List[str] = []
    for i in range(3):
        left = i / 3.0 - ROPE_OVERLAP
        right = (i + 1) / 3.0 + ROPE_OVERLAP
        rope_crops.append(_crop_b64(img, left, ROPE_AREA_TOP, right, ROPE_AREA_BOTTOM))

    return {"header": header_b64, "ropes": rope_crops}


class LotHistoryCardsService:
    """Structured extractor for the Lot History Card (Grey Folding) form."""

    async def _read_header_crop(self, header_b64: str) -> Dict[str, str]:
        raw = await llm_service.unified_chat_completion(
            HEADER_CROP_SYSTEM,
            HEADER_CROP_USER,
            image_base64=header_b64,
            image_mime_type="image/png",
            max_tokens=512,
        )
        parsed = parse_llm_json(raw)
        return _normalize_header(parsed if isinstance(parsed, dict) else None)

    async def _read_rope_crop(self, rope_b64: str) -> Dict[str, Any]:
        raw = await llm_service.unified_chat_completion(
            ROPE_CROP_SYSTEM,
            ROPE_CROP_USER,
            image_base64=rope_b64,
            image_mime_type="image/png",
            max_tokens=1536,
        )
        parsed = parse_llm_json(raw)
        # _normalize_rope accepts the {rolls, totals} crop shape directly.
        return _normalize_rope(parsed if isinstance(parsed, dict) else None)

    async def _extract_card(self, img_base64: str) -> Dict[str, Any]:
        """Extract one card by reading FOUR isolated crops — the header strip and
        each rope block separately — so a value can never bleed from one rope
        into another (the model only ever sees one block at a time).

        Falls back to a single whole-image read if cropping is unavailable.
        Confidence is still scored by reconciling each rope's roll values against
        its PRINTED total row (see confidence.score_sections).
        """
        regions = _crop_card_regions(img_base64)

        if regions is None:
            # Fallback: one whole-image read (legacy path).
            header, rolls_by_rope, totals_by_rope = await self._read_whole_card(img_base64)
        else:
            header = await self._read_header_crop(regions["header"])
            rolls_by_rope: Dict[str, List[Dict[str, str]]] = {}
            totals_by_rope: Dict[str, Dict[str, str]] = {}
            for idx, key in enumerate(ROPE_KEYS):
                rope = await self._read_rope_crop(regions["ropes"][idx])
                rolls_by_rope[key] = rope["rolls"]
                totals_by_rope[key] = rope["totals"]

        confidence = confidence_scorer.score_sections(header, rolls_by_rope, totals_by_rope)
        return {
            "header": header,
            **rolls_by_rope,
            "totals": totals_by_rope,
            "confidence": confidence,
        }

    async def _read_whole_card(self, img_base64: str):
        """Legacy single-call read of the entire card (fallback only)."""
        raw = await llm_service.unified_chat_completion(
            LOT_CARD_SYSTEM,
            LOT_CARD_USER,
            image_base64=img_base64,
            image_mime_type="image/png",
            max_tokens=2048,
        )
        parsed = parse_llm_json(raw)
        if not isinstance(parsed, dict):
            parsed = {}
        header = _normalize_header(parsed.get("header"))
        ropes = {key: _normalize_rope(parsed.get(key)) for key in ROPE_KEYS}
        rolls_by_rope = {key: ropes[key]["rolls"] for key in ROPE_KEYS}
        totals_by_rope = {key: ropes[key]["totals"] for key in ROPE_KEYS}
        return header, rolls_by_rope, totals_by_rope

    async def extract(self, buffer: bytes, filename: str) -> Dict[str, Any]:
        lower = filename.lower()

        if lower.endswith(".pdf"):
            pages = await register_extractor_service.split_pdf_to_pages(buffer)
        elif lower.endswith((".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")):
            pages = await register_extractor_service.process_image_file(buffer, filename)
        else:
            raise ValueError(f"Unsupported file: {filename}")

        if not pages:
            raise ValueError("Failed to parse document into pages.")

        page_results: List[Dict[str, Any]] = []
        total_rolls = 0

        for page_info in pages:
            page_num = page_info["page_number"]
            img_b64 = page_info.get("img_base64", "")
            image_url = page_info.get("image_url", "")

            try:
                card = await self._extract_card(img_b64)
            except Exception as exc:
                print(f"[LotHistoryCards] Page {page_num} extract failed: {exc}")
                card = {
                    "header": _normalize_header(None),
                    **{key: [] for key in ROPE_KEYS},
                    "totals": {k: {"Total Pcs": "", "Wt (kg)": ""} for k in ROPE_KEYS},
                    "confidence": {
                        "available": False,
                        "sections": {"header": None, **{k: None for k in ROPE_KEYS}},
                    },
                }

            n_rolls = sum(len(card.get(key, [])) for key in ROPE_KEYS)
            total_rolls += n_rolls

            page_results.append({
                "page_number": page_num,
                "image_url": image_url,
                "header": card["header"],
                "Rope 1": card.get("Rope 1", []),
                "Rope 2": card.get("Rope 2", []),
                "Rope 3": card.get("Rope 3", []),
                "totals": card.get("totals", {k: {"Total Pcs": "", "Wt (kg)": ""} for k in ROPE_KEYS}),
                "confidence": card.get("confidence", {
                    "available": False,
                    "sections": {"header": None, **{k: None for k in ROPE_KEYS}},
                }),
            })

            io_no = card["header"].get("I.O. No", "")
            print(
                f"[LotHistoryCards] Page {page_num}: I.O.No='{io_no}' "
                f"rolls={n_rolls}"
            )

        return {
            "service": "lot_history_cards",
            "filename": filename,
            "total_pages": len(page_results),
            "total_cards": len(page_results),
            "total_rolls": total_rolls,
            "header_fields": HEADER_FIELDS,
            "rope_columns": ROPE_COLUMNS,
            "rope_keys": ROPE_KEYS,
            "pages": page_results,
        }


lot_history_cards_service = LotHistoryCardsService()
