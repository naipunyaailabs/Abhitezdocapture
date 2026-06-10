"""
Production Sheets Service — Vision LLM extraction for the Abhitex daily
production registers, extracting ONLY the reduced "green column" set.

Each source sheet exists in two layouts:
  * a FULL layout with display-only columns (COLOR NAME, DESIGN, BUYER,
    SIZE, TEAM NAME, ...) and
  * a reduced "extractable" layout that keeps ONLY the green columns.

This service always extracts and exports the reduced green-column set:

    LOT NO | STYLE CODE | IO NUMBER | ShadeCode | TeamCode | PCS | KGS

It auto-detects which of the four production sheets each page is, from the
printed "... PROD" / "FNS TO CONT /OUTSIDE" title at the top:

    LENGTH HEMING PROD       → length_heming
    LENGTH CUTING  PROD      → length_cuting
    FNS TO CONT /OUTSIDE     → fns_to_job
    CROSS CUTING  PROD       → cross_cuting

The four sheets share the same 7-column schema; only the title (and the
"TeamCode" header label, which prints as "TEAM CODE" on FNS TO JOB) differs.
This service reuses the register_extractor PDF/image page-split + OCR
pipeline, then reads the page DATE and the table rows with specialized
vision prompts. Fixed columns, no template picking, stateless.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from app.services.llm_service import llm_service
from app.services.register_extractor.register_service import register_extractor_service
from app.services.register_extractor.ocr_engine import parse_llm_json


# ── Reduced "green column" schema (stable — frontend + export depend on it) ──
COLUMNS: List[str] = [
    "LOT NO",
    "STYLE CODE",
    "IO NUMBER",
    "ShadeCode",
    "TeamCode",
    "PCS",
    "KGS",
]

EXTRACTION_HINTS: Dict[str, str] = {
    "LOT NO": "Lot number, usually 4-6 digits. Read exactly. Empty cell is \"\".",
    "STYLE CODE": "Style code, usually 5-6 digits. Match the handwriting exactly.",
    "IO NUMBER": "IO / item-order number, usually 5 digits. Never merge with the lot or style number.",
    "ShadeCode": "Shade code — digits or a short alphanumeric code, or blank. Read exactly.",
    "TeamCode": "Team code — a short code or number identifying the team, or blank.",
    "PCS": "Pieces count — a whole number, or blank. NEVER compute.",
    "KGS": "Weight in kilograms — integer or decimal (e.g. 45, 32.2), or blank. Read exactly.",
}


# ── Sheet-type registry ─────────────────────────────────────────────────────
# Each production sheet shares the 7-column schema above. They differ only by
# the printed title and the exported header label for the TeamCode column.
SHEET_TYPES: Dict[str, Dict[str, str]] = {
    "length_heming": {
        "title": "LENGTH HEMING PROD",
        "team_header": "TeamCode",
        "label": "Length Heming",
    },
    "length_cuting": {
        "title": "LENGTH CUTING  PROD",
        "team_header": "TeamCode",
        "label": "Length Cutting",
    },
    "fns_to_job": {
        "title": "FNS TO CONT /OUTSIDE",
        "team_header": "TEAM CODE",
        "label": "FNS to Job",
    },
    "cross_cuting": {
        "title": "CROSS  CUTING  PROD",
        "team_header": "TEAM CODE",
        "label": "Cross Cutting",
    },
}

DEFAULT_SHEET_TYPE = "length_heming"


def sheet_meta(sheet_type: str) -> Dict[str, str]:
    """Return the registry entry for a sheet type, falling back to the default."""
    return SHEET_TYPES.get(sheet_type, SHEET_TYPES[DEFAULT_SHEET_TYPE])


# ── Prompts ─────────────────────────────────────────────────────────────────

DETECT_SYSTEM_PROMPT = (
    "You read the TITLE printed at the top of an Indian textile factory daily "
    "production register page and classify which sheet it is.\n\n"
    "The page has a bold title banner just under the 'DATE :' line. It is ONE of:\n"
    "  - 'LENGTH HEMING PROD'      → length_heming\n"
    "  - 'LENGTH CUTING PROD'      → length_cuting\n"
    "  - 'FNS TO CONT /OUTSIDE'    → fns_to_job\n"
    "  - 'CROSS CUTING PROD'       → cross_cuting\n\n"
    "Read the banner text and map it to the matching key. Spelling on the form "
    "may vary slightly (CUTING/CUTTING, extra spaces) — match on the keywords "
    "(HEMING, LENGTH CUTING, FNS, CROSS CUTING).\n\n"
    "Output ONLY this JSON, no prose:\n"
    "{\"sheet_type\": \"length_heming|length_cuting|fns_to_job|cross_cuting\"}"
)

DETECT_USER_PROMPT = (
    "Read the title banner at the top of this production sheet and return the "
    "matching sheet_type key. Return only the JSON object."
)


DATE_SYSTEM_PROMPT = (
    "You are reading a daily production register page from an Indian textile "
    "factory. At the TOP of the page there is a 'DATE :' field with a "
    "handwritten date value.\n"
    "Your job: Read EXACTLY what is written in the DATE field.\n\n"
    "DATE FORMATS IN THESE REGISTERS:\n"
    "- Indian format with slashes: 3/5/96 (day/month/year)\n"
    "- Mixed format: 9.8/5/26 (dots and slashes)\n"
    "- Standard format: 08/06/26, 12/05/25\n"
    "- Other: 5 May 2026, 3 JUN 2025\n\n"
    "RULES:\n"
    "1. Preserve EXACTLY what is written: slashes, dots, spacing, numbers, letters\n"
    "2. Do NOT convert formats (e.g., '3/5/96' stays '3/5/96')\n"
    "3. If date is unclear, output your best reading\n"
    "4. If no date visible, output empty string ''\n\n"
    "Output JSON: {\"date\": \"<exact_date_string>\"}"
)

DATE_USER_PROMPT = (
    "This is a production register page. Read the DATE value shown at the top "
    "next to 'DATE :'. Return EXACTLY what you read, preserving all slashes, "
    "dots, and formatting. Output JSON: {\"date\": \"<value>\"}."
)


# The four sheets share a single rows prompt — only the schema matters, and it
# is identical across them. The FULL layout on the source sheet may show extra
# display columns (COLOR NAME, DESIGN, BUYER, SIZE, TEAM NAME); we IGNORE those
# and read ONLY the seven green columns below.
ROWS_SYSTEM_PROMPT = (
    "You are an EXPERT OCR specialist for Indian textile factory daily "
    "PRODUCTION registers (Length Heming / Length Cuting / FNS to Cont / Cross "
    "Cuting). Your job is to read EXACTLY what is written, with PERFECT column "
    "alignment.\n\n"

    "EXTRACT ONLY THESE 7 COLUMNS, IN THIS EXACT ORDER:\n"
    "  1. LOT NO      — lot number (4-6 digits)\n"
    "  2. STYLE CODE  — style code (5-6 digits)\n"
    "  3. IO NUMBER   — IO / item-order number (usually 5 digits)\n"
    "  4. ShadeCode   — shade code (digits or short alphanumeric, or blank)\n"
    "  5. TeamCode    — team code (short code/number, or blank)\n"
    "  6. PCS         — pieces (whole number, or blank)\n"
    "  7. KGS         — weight in kg (integer or decimal, or blank)\n\n"

    "IMPORTANT — THE FORM MAY HAVE MORE COLUMNS THAN THESE 7:\n"
    "Some versions of the form ALSO print COLOR NAME, DESIGN, BUYER, SIZE and\n"
    "TEAM NAME columns. You MUST IGNORE those extra columns entirely. Map only\n"
    "the columns listed above. The header labels to anchor on are:\n"
    "  LOT NO, STYLE CODE, IO (or IO NUMBER), SHADE NO / ShadeCode,\n"
    "  TeamCode / TEAM CODE, PCS, KGS.\n"
    "Pick the value from UNDER each of those labelled columns. Do not pull the\n"
    "value from a COLOR/DESIGN/BUYER/SIZE column into one of the 7 outputs.\n\n"

    "DITTO MARKS — CRITICAL, READ THIS CAREFULLY:\n"
    "These sheets use DITTO marks to mean 'same value as the cell directly\n"
    "ABOVE in this same column'. A ditto mark looks like a double-quote (\"), a\n"
    "pair of small ticks (,, or '' or \" ), a small 'do', or a short\n"
    "dash/squiggle placed in the MIDDLE of an otherwise empty cell, sitting\n"
    "right under a filled cell.\n"
    "\n"
    "DO NOT try to copy the value from the row above yourself — you make mistakes\n"
    "when you do that (for example pulling the STYLE CODE number into the LOT NO\n"
    "column). INSTEAD, for ANY cell that contains a ditto mark, output the single\n"
    "caret character: ^  (a literal ^). The system will fill in the correct value\n"
    "from above automatically.\n"
    "\n"
    "RULES FOR THE ^ DITTO SENTINEL:\n"
    "- A cell with a ditto mark → output \"^\" (just the caret). Do NOT output the\n"
    "  ditto symbol itself, do NOT output the value above, do NOT output \"\".\n"
    "- Apply this PER COLUMN, reading STRAIGHT DOWN. Each column is independent:\n"
    "  the LOT NO column may be ditto on a row while STYLE CODE on the same row\n"
    "  has a real written value. Decide ^ vs real value SEPARATELY for each of\n"
    "  the 7 columns.\n"
    "- VERY COMMON: LOT NO, IO NUMBER and ShadeCode are dittoed down many rows in\n"
    "  a block while STYLE CODE, PCS and KGS change every row. In that case LOT\n"
    "  NO = \"^\", IO NUMBER = \"^\", ShadeCode = \"^\", but STYLE CODE/PCS/KGS hold\n"
    "  their own real values.\n"
    "- A new written value in a cell is NOT a ditto — output that real value.\n"
    "- A genuinely EMPTY cell (no mark at all, nothing written) → output \"\".\n"
    "  Use \"^\" ONLY when a ditto mark is actually drawn in the cell.\n"
    "\n"
    "EXAMPLE (IO NUMBER and ShadeCode dittoed under a block; STYLE CODE changes):\n"
    "Row 1 written: LOT 27098, STYLE 118158, IO 84668, Shade 14\n"
    "Row 2 below it: LOT ditto, STYLE 118156 (written), IO ditto, Shade ditto\n"
    "Row 3 below it: LOT ditto, STYLE 118157 (written), IO ditto, Shade ditto\n"
    "→ Row 1: [\"27098\", \"118158\", \"84668\", \"14\", ...]\n"
    "→ Row 2: [\"^\", \"118156\", \"^\", \"^\", ...]\n"
    "→ Row 3: [\"^\", \"118157\", \"^\", \"^\", ...]\n\n"

    "ZERO vs BLANK vs DITTO:\n"
    "- A handwritten '0' → output \"0\".\n"
    "- A ditto mark in the cell → output \"^\" (the system resolves it).\n"
    "- A completely blank cell with NO mark at all → output \"\".\n"
    "- Do NOT confuse zero with blank, and do NOT confuse a ditto with a blank.\n\n"

    "COLUMN ALIGNMENT (MOST IMPORTANT):\n"
    "EVERY ROW MUST HAVE EXACTLY 7 VALUES IN THIS ORDER:\n"
    "[LOT NO, STYLE CODE, IO NUMBER, ShadeCode, TeamCode, PCS, KGS]\n"
    "If a cell is blank, use \"\" for that position — DO NOT SKIP IT.\n"
    "NEVER shift values left to fill blanks. NEVER merge columns. NEVER skip "
    "positions.\n\n"

    "VALUE RULES:\n"
    "- Output numbers exactly as written: '120', '45.5', '0'.\n"
    "- NEVER add units, letters, or row numbers.\n"
    "- Do NOT compute PCS/KGS — read what is handwritten.\n"
    "- Skip the printed header row and any blank trailing rows.\n\n"

    "ONLY output what you ACTUALLY SEE on THIS image. Do NOT invent, guess, or "
    "recall values from another page or document. An empty string is ALWAYS "
    "correct for something you cannot read.\n\n"

    "OUTPUT — RETURN ONLY VALID JSON, no prose, no markdown fences.\n"
    "In the example below, row 1 has real written values; rows 2-3 have ditto\n"
    "marks under LOT NO, IO NUMBER and ShadeCode, so those become \"^\", while the\n"
    "STYLE CODE, PCS and KGS that are written change every row:\n"
    "{\n"
    "  \"headers\": [\"LOT NO\", \"STYLE CODE\", \"IO NUMBER\", \"ShadeCode\", \"TeamCode\", \"PCS\", \"KGS\"],\n"
    "  \"rows\": [\n"
    "    [\"27098\", \"118158\", \"84668\", \"14\", \"\", \"769\", \"470\"],\n"
    "    [\"^\", \"118156\", \"^\", \"^\", \"\", \"3060\", \"593\"],\n"
    "    [\"^\", \"118157\", \"^\", \"^\", \"\", \"315\", \"108\"]\n"
    "  ],\n"
    "  \"confidence\": 0.95\n"
    "}\n\n"

    "CONFIDENCE SCORING:\n"
    "- 0.95+: all cells clearly readable\n"
    "- 0.85-0.94: minor ambiguity on 1-2 cells\n"
    "- 0.75-0.84: some unclear cells but readable\n"
    "- Below 0.75: many ambiguous cells\n\n"

    "ABSOLUTE RULES:\n"
    "1. EVERY row gets EXACTLY 7 values (never more, never less).\n"
    "2. For ANY cell containing a ditto mark, output \"^\" — decided PER COLUMN.\n"
    "   NEVER copy the value from the row above yourself, and NEVER pull a value\n"
    "   from a neighbouring column (e.g. do NOT put STYLE CODE into LOT NO).\n"
    "3. A cell is \"\" ONLY when it is genuinely empty (no mark at all).\n"
    "4. ZEROS are \"0\" not \"\".\n"
    "5. NO value shifting, NO merging, NO skipping.\n"
    "6. NO explanations — ONLY JSON output."
)

ROWS_USER_PROMPT = (
    "This is a daily production register page. Read EVERY visible data row. For "
    "each row output EXACTLY 7 values in order: LOT NO, STYLE CODE, IO NUMBER, "
    "ShadeCode, TeamCode, PCS, KGS. Ignore any COLOR NAME / DESIGN / BUYER / "
    "SIZE / TEAM NAME columns.\n"
    "IMPORTANT: This sheet uses DITTO marks (\", ,, do, dash) that mean 'same as "
    "the cell directly above in this column'. For ANY cell that contains a ditto "
    "mark, output the single caret \"^\" — do NOT copy the value yourself and do "
    "NOT leave it blank. Decide ^ vs a real value SEPARATELY for each column: "
    "LOT NO, IO NUMBER and ShadeCode are often dittoed (=\"^\") down a block while "
    "STYLE CODE, PCS and KGS hold their own written values on every row. Output "
    "\"\" only for a genuinely empty cell with no mark. NEVER put a STYLE CODE "
    "value into the LOT NO column.\n"
    "Return complete JSON with ALL rows, ALL 7 columns per row, and a "
    "confidence score."
)


# The caret is the sentinel the model is instructed to emit for a ditto cell.
DITTO_SENTINEL = "^"

# Other tokens the model might still emit for a ditto instead of the sentinel.
# All of these are treated as "inherit the value from the cell above".
_DITTO_TOKENS = {
    "^", '"', "''", "'", ",,", ",", "”", "“", "„", "‚", "do", "dо", "ditto",
    "-", "–", "—", "~",
}


def _is_ditto(val: str) -> bool:
    """True if a cell value is a ditto sentinel/mark to be inherited from above."""
    v = val.strip().strip('.').lower()
    if not v:
        return False
    if v in _DITTO_TOKENS:
        return True
    # A short run of only caret/quote/tick/comma characters is a ditto too.
    return len(v) <= 2 and all(ch in "^\"'’‘`,，" for ch in v)


# ── Page-level vision helpers ────────────────────────────────────────────────

async def _detect_sheet_type(img_base64: str) -> str:
    """Classify the page into one of the four production sheet types."""
    try:
        raw = await llm_service.unified_chat_completion(
            DETECT_SYSTEM_PROMPT,
            DETECT_USER_PROMPT,
            image_base64=img_base64,
            image_mime_type="image/jpeg",
            max_tokens=120,
        )
        result = parse_llm_json(raw)
        if isinstance(result, dict):
            st = (result.get("sheet_type") or "").strip()
            if st in SHEET_TYPES:
                return st
    except Exception as exc:
        print(f"[ProductionSheets] sheet-type detect failed: {exc}")
    return DEFAULT_SHEET_TYPE


async def _extract_page_date(img_base64: str) -> str:
    """Read the DATE header field from a single page image."""
    try:
        raw = await llm_service.unified_chat_completion(
            DATE_SYSTEM_PROMPT,
            DATE_USER_PROMPT,
            image_base64=img_base64,
            image_mime_type="image/jpeg",
            max_tokens=200,
        )
        result = parse_llm_json(raw)
        return (result.get("date") or "").strip() if isinstance(result, dict) else ""
    except Exception as exc:
        print(f"[ProductionSheets] DATE extract failed: {exc}")
        return ""


# Identifier columns that commonly DITTO down the sheet. For these, a BLANK
# cell on a continuation row is also treated as a ditto (fallback for when the
# model forgets the "^" sentinel). PCS and KGS are per-row quantities, so a
# blank there is left blank — only an explicit ditto sentinel inherits.
_CARRY_COLUMNS = ("LOT NO", "STYLE CODE", "IO NUMBER", "ShadeCode", "TeamCode")


def _resolve_dittos(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Forward-fill ditto marks down each column, tracking the last real value.

    The model is instructed to emit the "^" sentinel for every ditto cell, so
    the primary rule is simple: a "^" (or any other ditto mark) inherits the
    last real value seen above in that column. This is decided PER COLUMN, so a
    dittoed LOT NO never picks up a written STYLE CODE from the same row.

    As a fallback for when the model forgets the sentinel, a BLANK cell in an
    identifier column also inherits — but only on a continuation row (one whose
    LOT NO is itself ditto/blank), so a genuinely new lot is never overwritten.
    Quantity columns (PCS, KGS) inherit ONLY on an explicit ditto sentinel.
    """
    last: Dict[str, str] = {col: "" for col in COLUMNS}
    for row in rows:
        lot_raw = row.get("LOT NO", "").strip()
        # A row continues the previous record when its LOT NO is ditto or blank.
        continuation = (lot_raw == "" or _is_ditto(lot_raw))

        for col in COLUMNS:
            val = row.get(col, "").strip()
            if _is_ditto(val):
                # Explicit ditto sentinel → inherit (works for every column).
                row[col] = last[col]
            elif val == "":
                # Blank fallback: only carry columns, only on continuation rows.
                if last[col] and col in _CARRY_COLUMNS and continuation:
                    row[col] = last[col]
            else:
                # A real written value resets the chain for this column.
                last[col] = val
                continue
            if row[col]:
                last[col] = row[col]
    return rows


def _map_rows(raw_rows: Any, page_num: int) -> List[Dict[str, str]]:
    """Coerce raw model rows into 7-column dicts, resolve ditto marks, and drop
    fully-empty rows."""
    mapped: List[Dict[str, str]] = []
    if not isinstance(raw_rows, list):
        return mapped

    for row_idx, r in enumerate(raw_rows):
        if not isinstance(r, list):
            print(f"[ProductionSheets] Page {page_num}: skipping row {row_idx} (not a list)")
            continue

        # Pad short rows so every column has a position.
        while len(r) < len(COLUMNS):
            r.append("")

        row_dict: Dict[str, str] = {}
        for i, col in enumerate(COLUMNS):
            val = r[i] if i < len(r) else ""
            row_dict[col] = str(val).strip() if val is not None else ""

        # Drop rows where every cell is empty (blank template lines). Done
        # BEFORE ditto resolution so a truly blank line doesn't absorb values.
        if not any(row_dict.values()):
            continue

        mapped.append(row_dict)

    # Resolve ditto marks across the surviving rows (in original order).
    return _resolve_dittos(mapped)


async def _extract_page_rows(img_base64: str, page_num: int) -> Tuple[List[Dict[str, str]], float]:
    """Extract the reduced 7-column rows from a single production page."""
    try:
        raw = await llm_service.unified_chat_completion(
            ROWS_SYSTEM_PROMPT,
            ROWS_USER_PROMPT,
            image_base64=img_base64,
            image_mime_type="image/jpeg",
            max_tokens=4000,
        )
        result = parse_llm_json(raw)
        if not isinstance(result, dict):
            return [], 0.0

        mapped_rows = _map_rows(result.get("rows", []), page_num)
        confidence = float(result.get("confidence", 0.0) or 0.0)

        print(f"[ProductionSheets] Page {page_num}: rows={len(mapped_rows)} conf={confidence*100:.1f}%")
        return mapped_rows, confidence
    except Exception as exc:
        print(f"[ProductionSheets] Row extraction failed (page {page_num}): {exc}")
        import traceback
        traceback.print_exc()
        return [], 0.0


class ProductionSheetsService:
    """Fixed-schema extractor for the four Abhitex production sheets."""

    async def _split(self, buffer: bytes, filename: str) -> List[Dict[str, Any]]:
        lower = filename.lower()
        if lower.endswith(".pdf"):
            pages = await register_extractor_service.split_pdf_to_pages(buffer)
        elif lower.endswith((".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")):
            pages = await register_extractor_service.process_image_file(buffer, filename)
        else:
            raise ValueError(f"Unsupported file: {filename}")
        if not pages:
            raise ValueError("Failed to parse document into pages.")
        return pages

    async def _process_page(self, page_info: Dict[str, Any]) -> Dict[str, Any]:
        page_num = page_info["page_number"]
        img_b64 = page_info.get("img_base64", "")
        image_url = page_info.get("image_url", "")

        sheet_type = await _detect_sheet_type(img_b64)
        date_value = await _extract_page_date(img_b64)
        mapped_rows, confidence = await _extract_page_rows(img_b64, page_num)

        meta = sheet_meta(sheet_type)
        print(
            f"[ProductionSheets] Page {page_num} complete: type={sheet_type} "
            f"date='{date_value}' rows={len(mapped_rows)} conf={confidence*100:.1f}%"
        )

        return {
            "page_number": page_num,
            "image_url": image_url,
            "sheet_type": sheet_type,
            "sheet_title": meta["title"],
            "sheet_label": meta["label"],
            "team_header": meta["team_header"],
            "date": date_value,
            "headers": COLUMNS,
            "rows": mapped_rows,
            "confidence": confidence,
        }

    async def extract(self, buffer: bytes, filename: str) -> Dict[str, Any]:
        pages = await self._split(buffer, filename)

        page_results: List[Dict[str, Any]] = []
        all_rows: List[Dict[str, str]] = []
        confidences: List[float] = []

        for page_info in pages:
            page_result = await self._process_page(page_info)
            page_results.append(page_result)
            all_rows.extend(page_result["rows"])
            confidences.append(page_result["confidence"])

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "service": "production_sheets",
            "filename": filename,
            "total_pages": len(page_results),
            "total_rows": len(all_rows),
            "headers": COLUMNS,
            "rows": all_rows,
            "pages": page_results,
            "average_confidence": avg_conf,
        }

    async def extract_streaming(self, buffer: bytes, filename: str):
        """Extract pages and yield JSONL results progressively, one per page."""
        pages = await self._split(buffer, filename)

        yield json.dumps({
            "type": "metadata",
            "total_pages": len(pages),
            "filename": filename,
        }).encode() + b"\n"

        all_confidences: List[float] = []

        for idx, page_info in enumerate(pages, start=1):
            page_num = page_info["page_number"]
            try:
                page_result = await self._process_page(page_info)
                all_confidences.append(page_result["confidence"])

                page_result = {"type": "page", "page_index": idx, **page_result}
                yield json.dumps(page_result).encode() + b"\n"
                print(f"[ProductionSheets] Streamed page {page_num}")
            except Exception as e:
                print(f"[ProductionSheets] Error processing page {page_num}: {e}")
                import traceback
                traceback.print_exc()
                yield json.dumps({
                    "type": "page_error",
                    "page_number": page_num,
                    "error": str(e),
                }).encode() + b"\n"

        avg_conf = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
        yield json.dumps({
            "type": "complete",
            "total_pages": len(pages),
            "average_confidence": avg_conf,
        }).encode() + b"\n"


production_sheets_service = ProductionSheetsService()
