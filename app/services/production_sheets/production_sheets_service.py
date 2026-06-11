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
import re as _re
from typing import Any, Dict, List, Tuple

from app.services.llm_service import llm_service
from app.services.register_extractor.register_service import register_extractor_service
from app.services.register_extractor.ocr_engine import parse_llm_json


# Vision model for production-sheet OCR. Maverick (128-expert) is markedly more
# accurate on handwritten digits than Scout (16-expert) — it reduces the common
# 0/8, 2/4, 6/0, 3/8 confusions. Override via PRODUCTION_SHEETS_VISION_MODEL.
import os as _os
VISION_MODEL = _os.getenv(
    "PRODUCTION_SHEETS_VISION_MODEL",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
)
# Number of independent extraction passes whose results are merged by majority
# vote per cell. Digit misreads are semi-random, so voting cancels most of them.
VOTING_PASSES = int(_os.getenv("PRODUCTION_SHEETS_VOTING_PASSES", "3"))


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
    "handwritten date value, sometimes followed by a shift word (DAY / NIGHT).\n\n"
    "Your ONLY job: TRANSCRIBE the date character-by-character, EXACTLY as drawn.\n\n"
    "ABSOLUTE RULES — READ CAREFULLY:\n"
    "1. Copy every character literally: digits, slashes '/', dots '.', dashes,\n"
    "   and spacing. Read it left to right, one symbol at a time.\n"
    "2. NEVER convert or interpret. Do NOT turn numbers into month names.\n"
    "   If the page shows '06/06/026', output exactly \"06/06/026\" — NOT\n"
    "   '6 June', NOT '6 June 2026', NOT '06/06/2026'. Keep the literal digits,\n"
    "   even if the year looks unusual like '026' or '26'.\n"
    "3. Do NOT 'fix' or normalize anything. Leading zeros stay. Three-digit\n"
    "   years stay three digits. Whatever is ink on the page is the answer.\n"
    "4. Apply the same digit care as elsewhere (0 vs 8, 6 vs 0, 2 vs 4, 3 vs 8).\n"
    "5. If a SHIFT word (DAY or NIGHT) is written next to the date, include it\n"
    "   in a separate field. Do not merge it into the date string.\n"
    "6. If no date is visible, output an empty string for date.\n\n"
    "Output JSON ONLY: {\"date\": \"<exact literal date string>\", "
    "\"shift\": \"<DAY|NIGHT|>\"}"
)

DATE_USER_PROMPT = (
    "Transcribe the DATE next to 'DATE :' at the top of this page EXACTLY as "
    "written, character by character — keep all slashes/dots and the literal "
    "digits (e.g. '06/06/026' stays '06/06/026', never '6 June'). Do NOT convert "
    "to a month name or change the year digits. If a DAY/NIGHT shift word is "
    "present, put it in 'shift'. Output JSON: "
    "{\"date\": \"<literal>\", \"shift\": \"<DAY|NIGHT|>\"}."
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

    "HANDWRITTEN DIGIT DISCIPLINE — THE #1 SOURCE OF ERRORS:\n"
    "Read each digit by its actual drawn shape. Do NOT pattern-guess. These pairs\n"
    "are the most commonly CONFUSED — look carefully and pick the one truly drawn:\n"
    "  • 0 vs 8 : 0 is a single open loop; 8 has a pinched waist (two stacked loops).\n"
    "  • 0 vs 6 : 6 has a tail/hook curling up into the loop; 0 is a clean oval.\n"
    "  • 2 vs 4 : 2 has a rounded top and a flat baseline; 4 has a straight\n"
    "             vertical stroke and an open or closed triangle, no baseline curve.\n"
    "  • 3 vs 8 : 3 is open on the LEFT (two right-facing bumps); 8 is fully closed.\n"
    "  • 1 vs 7 : 7 has a horizontal top bar; 1 does not.\n"
    "  • 5 vs 6 : 5 has a flat top and open bottom curve; 6 is a closed lower loop.\n"
    "Transcribe the digits you SEE, never what you expect a code 'should' be.\n"
    "Read every digit of a number left-to-right; do not drop or add digits.\n\n"

    "INTEGER COLUMNS — NO DECIMAL POINTS:\n"
    "LOT NO, STYLE CODE, IO NUMBER, ShadeCode, TeamCode, and PCS are WHOLE NUMBERS.\n"
    "They must NEVER contain a decimal point or fractional part. If you think you\n"
    "see a dot in one of these, it is dirt/noise on the page — ignore it. ONLY the\n"
    "KGS column may contain a decimal (e.g. 32.2). Never invent a decimal in KGS.\n\n"

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
            model=VISION_MODEL,
        )
        result = parse_llm_json(raw)
        if isinstance(result, dict):
            st = (result.get("sheet_type") or "").strip()
            if st in SHEET_TYPES:
                return st
    except Exception as exc:
        print(f"[ProductionSheets] sheet-type detect failed: {exc}")
    return DEFAULT_SHEET_TYPE


async def _extract_page_date(img_base64: str) -> Tuple[str, str]:
    """Read the DATE (and optional shift) header field from a page image.
    Returns (date_string, shift_string)."""
    try:
        raw = await llm_service.unified_chat_completion(
            DATE_SYSTEM_PROMPT,
            DATE_USER_PROMPT,
            image_base64=img_base64,
            image_mime_type="image/jpeg",
            max_tokens=200,
            model=VISION_MODEL,
        )
        result = parse_llm_json(raw)
        if isinstance(result, dict):
            date_val = (result.get("date") or "").strip()
            shift_val = (result.get("shift") or "").strip().upper()
            if shift_val not in ("DAY", "NIGHT"):
                shift_val = ""
            return date_val, shift_val
        return "", ""
    except Exception as exc:
        print(f"[ProductionSheets] DATE extract failed: {exc}")
        return "", ""


# Columns that must be whole numbers — a decimal here is an OCR/noise artifact.
# KGS is intentionally excluded: it is the only column allowed a decimal.
_INTEGER_COLUMNS = ("LOT NO", "STYLE CODE", "IO NUMBER", "PCS")


def _clean_cell(col: str, val: str) -> str:
    """Deterministic cleanup of a single extracted value.

    - Trims whitespace.
    - For integer columns, removes decimal points and any fractional part
      ('1234.0' → '1234', '12.34' → '1234'), and strips stray non-digit noise
      while leaving purely-alphanumeric codes intact.
    - KGS keeps a single decimal if present.
    """
    v = (val or "").strip()
    if v == "" or v == DITTO_SENTINEL:
        return v

    if col in _INTEGER_COLUMNS:
        if _re.fullmatch(r"[\d.\s]+", v):
            v = _re.sub(r"\s", "", v)
            # A trailing ".0"/".00" is a spurious fractional part on an integer
            # ('1234.0' → '1234') — drop it rather than concatenating digits.
            v = _re.sub(r"\.0*$", "", v)
            # Any remaining dots are stray marks between digits ('12.34' is a
            # misread of '1234' in an integer column) — remove them.
            return v.replace(".", "")
        return v

    if col == "KGS":
        # Keep at most one decimal point; strip spaces. Leave non-numeric as-is.
        if _re.fullmatch(r"[\d.\s]+", v):
            v = _re.sub(r"\s", "", v)
            if v.count(".") > 1:
                first = v.find(".")
                v = v[:first + 1] + v[first + 1:].replace(".", "")
            return v.rstrip(".")
        return v

    return v


def _clean_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    for row in rows:
        for col in COLUMNS:
            row[col] = _clean_cell(col, row.get(col, ""))
    return rows


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

    # Resolve ditto marks across the surviving rows (in original order),
    # then deterministically clean each cell (strip decimals from integer cols).
    return _clean_rows(_resolve_dittos(mapped))


async def _extract_page_rows_once(img_base64: str, page_num: int):
    """One extraction pass. Returns (rows, confidence) or (None, 0.0) on failure."""
    try:
        raw = await llm_service.unified_chat_completion(
            ROWS_SYSTEM_PROMPT,
            ROWS_USER_PROMPT,
            image_base64=img_base64,
            image_mime_type="image/jpeg",
            max_tokens=4000,
            model=VISION_MODEL,
        )
        result = parse_llm_json(raw)
        if not isinstance(result, dict):
            return None, 0.0
        mapped_rows = _map_rows(result.get("rows", []), page_num)
        confidence = float(result.get("confidence", 0.0) or 0.0)
        return mapped_rows, confidence
    except Exception as exc:
        print(f"[ProductionSheets] Row pass failed (page {page_num}): {exc}")
        return None, 0.0


def _vote_rows(passes: List[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    """Merge multiple extraction passes by majority vote PER CELL.

    Passes can disagree on row count; we align by row index up to the modal
    length. For each (row, column) cell we take the most common non-empty value
    across passes. Ties fall back to the first pass's value (it is the primary).
    This cancels most random digit misreads without ever inventing a value.
    """
    from collections import Counter
    valid = [p for p in passes if p]
    if not valid:
        return []
    if len(valid) == 1:
        return valid[0]

    # Use the most common row count as the canonical length; prefer the longest
    # among the modal set so we don't silently drop rows a pass actually read.
    length_counts = Counter(len(p) for p in valid)
    modal_len = max(length_counts, key=lambda L: (length_counts[L], L))
    # The reference pass is the first one whose length matches the modal length.
    reference = next((p for p in valid if len(p) == modal_len), valid[0])

    merged: List[Dict[str, str]] = []
    for i in range(len(reference)):
        cell_votes: Dict[str, Counter] = {col: Counter() for col in COLUMNS}
        for p in valid:
            if i < len(p):
                for col in COLUMNS:
                    v = (p[i].get(col, "") or "").strip()
                    if v != "":
                        cell_votes[col][v] += 1
        row: Dict[str, str] = {}
        for col in COLUMNS:
            votes = cell_votes[col]
            if not votes:
                row[col] = ""
                continue
            top = votes.most_common()
            best_count = top[0][1]
            tied = [val for val, c in top if c == best_count]
            if len(tied) == 1:
                row[col] = tied[0]
            else:
                # Tie → trust the reference pass's value if it's among the tied.
                ref_val = (reference[i].get(col, "") or "").strip()
                row[col] = ref_val if ref_val in tied else tied[0]
        merged.append(row)
    return merged


async def _extract_page_rows(img_base64: str, page_num: int) -> Tuple[List[Dict[str, str]], float]:
    """Extract rows via N independent passes merged by per-cell majority vote."""
    import asyncio
    n = max(1, VOTING_PASSES)
    results = await asyncio.gather(
        *[_extract_page_rows_once(img_base64, page_num) for _ in range(n)]
    )
    passes = [rows for rows, _ in results if rows is not None]
    confs = [c for rows, c in results if rows is not None and c]

    merged = _vote_rows(passes)
    # Confidence: average of passes, nudged up when passes agreed on row count.
    confidence = (sum(confs) / len(confs)) if confs else 0.0

    print(f"[ProductionSheets] Page {page_num}: passes={len(passes)}/{n} "
          f"rows={len(merged)} conf={confidence*100:.1f}%")
    return merged, confidence


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
        date_value, shift_value = await _extract_page_date(img_b64)
        mapped_rows, confidence = await _extract_page_rows(img_b64, page_num)

        meta = sheet_meta(sheet_type)
        print(
            f"[ProductionSheets] Page {page_num} complete: type={sheet_type} "
            f"date='{date_value}' shift='{shift_value}' rows={len(mapped_rows)} "
            f"conf={confidence*100:.1f}%"
        )

        return {
            "page_number": page_num,
            "image_url": image_url,
            "sheet_type": sheet_type,
            "sheet_title": meta["title"],
            "sheet_label": meta["label"],
            "team_header": meta["team_header"],
            "date": date_value,
            "shift": shift_value,
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
