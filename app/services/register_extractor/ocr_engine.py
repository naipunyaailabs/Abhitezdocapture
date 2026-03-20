"""
OCR Engine for Register Extraction — Vision LLM

Uses Groq Vision LLM to extract tabular data from handwritten/printed
register pages. Includes fabrication detection and retry logic.
"""

from __future__ import annotations

import json
import re
import string
from typing import Dict, List, Optional

from app.services.llm_service import llm_service


# ── Domain-specific system prompt for Indian textile factory registers ────────
# Provides the model with pattern knowledge about the exact register types
# and field values it will encounter, plus strict rules for separator
# preservation and empty cell handling.

OCR_SYSTEM = (
    "You are an OCR specialist for Indian textile factory handwritten registers.\n"
    "Your ONLY job is to READ what is written in the image and return it as JSON.\n\n"

    "REGISTER TYPES YOU WILL SEE:\n"
    "1. PREP BEAM ISSUE REPORT — Columns: Beam No, Party Name, IO#, Size, Yarn Count Code, Ends, DBF, Length, Weight, Lot, Loom\n"
    "2. LENGTH HEMMING/CUTTING PROD — Columns: Lot No, Style Code, IO Number, Shade Name, Style Type, Party Name, Size, PCS, KGS\n"
    "3. DYEING TO MACHINE LINE — Columns: Style Code, Lot No, IO No, Buyer Name, Shade, Style, Grey Wt, After Dye Wt\n"
    "4. DYEING REGISTER (printed) — Columns: Date, Style Code, Lot No, IO No, Party, Shade, Style, Grey Wt, After Dye Wt\n\n"

    "EXAMPLE REAL VALUES (these are the patterns you will see):\n"
    "- Beam No: TP-06, TN-102, TP-201, TS-50 (letters + dash + number)\n"
    "- Party/Buyer Names: Revman, DUNLEM, WSP, RVM, LUXMI, DM, Rajluxmi, TLi, W.S.P\n"
    "- IO Numbers: 84415, 84437, 83851 (5-digit)\n"
    "- Lot Numbers: 24357, 22473, 24558 (5-digit)\n"
    "- Style Codes: 116045, 114228, 105532 (5-6 digit)\n"
    "- Sizes: 20x30, 76x137, 40x66 (dimension), OR Bath, Hand, Sheet, Wash, Mat, Stock (towel size names)\n"
    "- Yarn Count Code: 2/18 ZT, 9/20 kw, 10a o/6 Pc, 20/2 (mixed alphanumeric WITH slashes — PRESERVE EXACTLY)\n"
    "- Shade Names: Dove, Navy, Black, Petal Pink, Tan, Sage, Pebble, Mushroom, White, Midnight Blue, Sunset Pink, Honey, Olive, Denim, Sea Green, Blue\n"
    "- Style Types: Soft & Fluffy, Modern Waffle, Simple City, Trade Wind, Gimmy, Stock, Remnant, Twill STP, Bold STP, Rugby, 2 PLY, ZT, 1 PLY, Somesta Better\n"
    "- PCS/KGS/Weight: plain numbers like 84, 280, 967.5\n"
    "- Grey Wt / After Dye Wt: decimal numbers like 145.5, 203.2\n"
    "- Ends/DBF/Length: numeric values\n"
    "- Loom: numeric or alphanumeric\n\n"

    "CRITICAL RULES:\n"
    "1. ONLY output data you can ACTUALLY SEE. Do NOT invent or fabricate values.\n"
    "2. PRESERVE ALL SEPARATORS EXACTLY: slashes (/), dashes (-), spaces, 'x' in sizes.\n"
    "   '12/32/43' must stay '12/32/43', NEVER '1232143'.\n"
    "   '2/18 ZT' must stay '2/18 ZT', NEVER '218ZT' or '218 ZT'.\n"
    "   'TP-06' must stay 'TP-06', NEVER 'TP06'.\n"
    "3. EMPTY CELLS: If a cell is blank/empty in the register, output \"\" (empty string).\n"
    "   Do NOT fill blank cells with values from neighboring cells or the row above.\n"
    "   ONLY treat actual ditto marks (\u3003 or \") as repeats — a blank cell is NOT a ditto.\n"
    "4. COLUMN ALIGNMENT: Each value must go in the correct column. Count carefully.\n"
    "   Do NOT shift values left/right to fill gaps.\n"
    "5. Real data is NEVER sequential (A,B,C or 1,2,3 or E201,E202,E203).\n"
    "6. Skip total/summary rows at the bottom.\n"
    "7. If you cannot read a cell, use \"\".\n"
    "8. If you cannot read ANY content, return {\"headers\":[], \"rows\":[], \"confidence\":0}.\n\n"

    "OUTPUT FORMAT — Return ONLY valid JSON, no other text:\n"
    "{\n"
    '  "headers": ["Col1", "Col2", ...],\n'
    '  "rows": [["val1", "val2", ...], ...],\n'
    '  "confidence": 0.85\n'
    "}\n"
    "Each row array MUST have the same number of elements as headers. Pad with \"\" if empty."
)


def parse_llm_json(raw_text: str) -> Dict:
    """Robustly extract a JSON object from LLM output, handling truncation."""
    try:
        m = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        m = re.search(r"```\s*(.*?)\s*```", raw_text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        m = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except json.JSONDecodeError:
        pass

    # If standard parsing failed, try repairing truncated JSON
    return _repair_truncated_json(raw_text)


def parse_llm_json_array(raw_text: str) -> List[Dict]:
    """Extract a JSON array from LLM output."""
    try:
        m = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        m = re.search(r"```\s*(.*?)\s*```", raw_text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        m = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        obj = parse_llm_json(raw_text)
        if obj:
            return [obj]
        return []
    except Exception as exc:
        print(f"[ocr_engine] JSON array parse error: {exc}")
        return []


def _repair_truncated_json(raw_text: str) -> Dict:
    """Attempt to repair truncated JSON from cut-off LLM responses."""
    # Find the start of JSON
    start = raw_text.find("{")
    if start == -1:
        return {}

    text = raw_text[start:]

    # Find the last complete row (ends with ]) in the rows array
    last_bracket = text.rfind("]")
    if last_bracket == -1:
        return {}

    # Try progressively truncating to find valid JSON
    for end_pos in range(len(text), max(0, len(text) - 500), -1):
        candidate = text[:end_pos]
        # Count unclosed brackets
        open_sq = candidate.count("[") - candidate.count("]")
        open_cr = candidate.count("{") - candidate.count("}")
        # Close them
        repair = candidate + '""' + "]" * max(0, open_sq) + "}" * max(0, open_cr)
        try:
            result = json.loads(repair)
            if isinstance(result, dict) and "rows" in result:
                # Remove the last row as it might be incomplete
                rows = result.get("rows", [])
                if rows:
                    result["rows"] = rows[:-1]
                print(f"[ocr_engine] Repaired truncated JSON: {len(result.get('rows', []))} rows recovered")
                return result
        except json.JSONDecodeError:
            continue

    return {}


# ── Fabrication Detection ────────────────────────────────────────────────────

def _is_sequential_alpha(values: List[str]) -> bool:
    """Check if values are sequential alphabet e.g. A, B, C, D..."""
    cleaned = [v.strip().upper() for v in values if v.strip()]
    if len(cleaned) < 3:
        return False
    alpha = list(string.ascii_uppercase)
    for start in range(len(alpha)):
        seq = alpha[start:start + len(cleaned)]
        if cleaned == seq:
            return True
    return False


def _is_sequential_numbers(values: List[str]) -> bool:
    """Check if values are clearly fabricated sequential numbers.
    
    Only flags sequences starting from small numbers (< 100) like 1,2,3,4
    or from round numbers like 1001,1002,1003.
    Real register roll numbers (66044,66045,66046) are NOT flagged.
    """
    nums = []
    for v in values:
        v = v.strip()
        if v and v.isdigit():
            nums.append(int(v))
    if len(nums) < 3:
        return False
    diffs = [nums[i+1] - nums[i] for i in range(len(nums) - 1)]
    if not (len(set(diffs)) == 1 and diffs[0] in (1, -1)):
        return False
    # Only flag if starting from a suspicious value:
    # - Small numbers (< 100) like 1,2,3 or 10,11,12
    # - Round multiples (1000,1001... or 100,101...)
    start = min(nums)
    if start < 100:
        return True
    if start % 100 == 0 or start % 1000 == 0:
        return True
    return False


def _is_sequential_prefixed(values: List[str]) -> bool:
    """Check patterns like E201,E202,E203 or IO201,IO202,IO203 or T201,T202,T203."""
    cleaned = [v.strip() for v in values if v.strip()]
    if len(cleaned) < 3:
        return False
    # Extract common prefix + numeric suffix
    m = re.match(r'^([A-Za-z]+)(\d+)$', cleaned[0])
    if not m:
        return False
    prefix = m.group(1)
    nums = []
    for v in cleaned:
        m2 = re.match(r'^' + re.escape(prefix) + r'(\d+)$', v, re.IGNORECASE)
        if not m2:
            return False
        nums.append(int(m2.group(1)))
    diffs = [nums[i+1] - nums[i] for i in range(len(nums) - 1)]
    return len(set(diffs)) == 1 and diffs[0] in (1, -1)


def _all_identical(values: List[str]) -> bool:
    """Check if all non-empty values are suspiciously identical.
    
    Excludes: dates (contain /), short codes (< 3 chars), party names.
    Only flags if 5+ identical values of a suspicious type.
    """
    cleaned = [v.strip() for v in values if v.strip()]
    if len(cleaned) < 5 or len(set(cleaned)) != 1:
        return False
    val = cleaned[0]
    # Don't flag dates (contain /)
    if "/" in val:
        return False
    # Don't flag short values that could be legitimate codes/abbreviations
    if len(val) <= 3:
        return False
    return True


def detect_fabrication(headers: List[str], rows: List[List[str]]) -> bool:
    """
    Detect if OCR output looks fabricated/hallucinated.
    Returns True if data appears fabricated.
    """
    if not rows or len(rows) < 3:
        return False

    fabrication_count = 0
    total_cols = len(headers) if headers else (len(rows[0]) if rows else 0)

    for col_idx in range(total_cols):
        col_vals = [row[col_idx] for row in rows if col_idx < len(row)]
        if _is_sequential_alpha(col_vals):
            col_name = headers[col_idx] if col_idx < len(headers) else f"col{col_idx}"
            print(f"[ocr_engine] FABRICATION: column '{col_name}' has sequential alphabet: {col_vals[:5]}")
            fabrication_count += 1
        elif _is_sequential_numbers(col_vals):
            col_name = headers[col_idx] if col_idx < len(headers) else f"col{col_idx}"
            print(f"[ocr_engine] FABRICATION: column '{col_name}' has sequential numbers: {col_vals[:5]}")
            fabrication_count += 1
        elif _is_sequential_prefixed(col_vals):
            col_name = headers[col_idx] if col_idx < len(headers) else f"col{col_idx}"
            print(f"[ocr_engine] FABRICATION: column '{col_name}' has sequential prefixed: {col_vals[:5]}")
            fabrication_count += 1
        elif _all_identical(col_vals) and total_cols > 2:
            col_name = headers[col_idx] if col_idx < len(headers) else f"col{col_idx}"
            print(f"[ocr_engine] FABRICATION: column '{col_name}' all identical: {col_vals[0]}")
            fabrication_count += 1

    # If 2+ columns look fabricated, the whole output is suspect
    is_fabricated = fabrication_count >= 2
    if is_fabricated:
        print(f"[ocr_engine] OUTPUT APPEARS FABRICATED ({fabrication_count} suspicious columns)")
    return is_fabricated


# ── Main OCR Function ────────────────────────────────────────────────────────

# Auto-generated hints for known textile register column types.
# These are used when the user hasn't provided a specific hint for a column.
DEFAULT_COLUMN_HINTS: Dict[str, str] = {
    "style code": "5-6 digit number (e.g. 116045, 114228, 105532)",
    "lot no": "5-digit lot number (e.g. 24357, 22473, 24558)",
    "lot": "5-digit lot number (e.g. 24357, 22473)",
    "lot number": "5-digit lot number (e.g. 24357, 22473)",
    "io no": "5-digit IO number (e.g. 84415, 84437, 83851)",
    "io number": "5-digit IO number (e.g. 84415, 84437, 83851)",
    "io#": "5-digit IO number (e.g. 84415, 84437)",
    "i.o. no": "5-digit IO number (e.g. 84415, 84437)",
    "buyer name": "company/party name (e.g. LUXMI, RVM, WSP, DM, DUNLEM, Revman, Rajluxmi, W.S.P)",
    "party name": "company/party name (e.g. DUNLEM, Revman, WSP, TLi, Mali, Moda)",
    "party": "company/party name (e.g. DUNLEM, Revman, WSP)",
    "shade": "color/shade name (e.g. Dove, Navy, Black, Petal Pink, Honey, Olive, Pebble, Mushroom, Denim, Sea Green)",
    "shade name": "color/shade name (e.g. Dove, Navy, Black, Petal Pink, Honey, Olive, Sunset Pink, Midnight Blue, Tan, Sage)",
    "style": "style description (e.g. 2 PLY, ZT, 1 PLY, Soft & Fluffy, Modern Waffle)",
    "style type": "style description (e.g. Soft & Fluffy, Modern Waffle, Simple City, Trade Wind, Gimmy, Stock, Remnant, Twill STP, Somesta Better)",
    "size": "dimension NxN (e.g. 20x30, 76x137) OR towel size name (Bath, Hand, Sheet, Wash, Mat, Stock)",
    "pcs": "whole number — pieces count (e.g. 84, 280, 1970)",
    "kgs": "numeric weight, may have decimal (e.g. 164, 425, 967.5)",
    "weight": "numeric weight, may have decimal (e.g. 145.5, 203.2)",
    "grey wt": "decimal weight before dyeing (e.g. 145.5, 203.2)",
    "after dye wt": "decimal weight after dyeing (e.g. 140.1, 198.6)",
    "beam no": "alphanumeric with dash (e.g. TP-06, TN-102, TP-201, TS-50). PRESERVE the dash",
    "yarn count code": "mixed alphanumeric WITH slashes — PRESERVE EXACTLY (e.g. 2/18 ZT, 9/20 kw, 10a o/6 Pc, 20/2)",
    "ends": "numeric — number of ends (e.g. 2560, 3840)",
    "dbf": "numeric — DBF value",
    "d.b.f": "numeric — DBF value",
    "length": "numeric — length value",
    "loom": "numeric or alphanumeric — loom number",
    "loom no": "numeric — loom number",
    "r.no": "5-digit roll number (e.g. 66044, 66045)",
    "i.no": "inspection number",
    "l.no": "lot/length number",
    "design": "design name (e.g. Rutland, Pleat Border, Trade Wind, Infinite, Modern Waffle, Popcorn)",
    "gsm": "3-4 digit GSM number",
    "thread no": "4-5 digit thread number",
    "date": "date in DD/MM/YYYY or DD/MM format — PRESERVE slashes",
}


def _build_column_definitions(
    expected_headers: List[str],
    extraction_hints: Optional[Dict[str, str]],
) -> str:
    """Build a structured per-column definition block for the LLM prompt.
    
    Each column gets: position number, name, and format guidance.
    Uses user-provided hints when available, falls back to domain-smart defaults.
    """
    if not expected_headers:
        return ""

    hints = extraction_hints or {}
    lines = [
        f"COLUMN DEFINITIONS — The table has exactly {len(expected_headers)} columns. "
        f"Use these as your 'headers' array. Each row MUST have exactly {len(expected_headers)} values.",
        f"Read these columns LEFT-TO-RIGHT in the image. Column 1 is the leftmost data column.",
    ]

    for i, col in enumerate(expected_headers, 1):
        col_lower = col.strip().lower()
        auto_hint = DEFAULT_COLUMN_HINTS.get(col_lower, "")
        user_hint = hints.get(col, "").strip()

        # Combine: auto-hint always present (domain knowledge), user note appended
        if auto_hint and user_hint:
            hint = f"{auto_hint}. User note: {user_hint}"
        elif user_hint:
            hint = user_hint
        else:
            hint = auto_hint

        if hint:
            lines.append(f"  Column {i}: \"{col}\" — {hint}")
        else:
            lines.append(f"  Column {i}: \"{col}\"")

    # Add disambiguation note when STYLE CODE and STYLE both exist
    col_names_lower = {c.strip().lower() for c in expected_headers}
    if "style code" in col_names_lower and "style" in col_names_lower:
        lines.append(
            "  WARNING: 'STYLE CODE' (5-6 digit number like 116665) and 'STYLE' "
            "(textile type like ZT, 2 PLY) are DIFFERENT columns. Do NOT confuse them. "
            "Do NOT leave STYLE CODE blank — it is the FIRST column with a long number."
        )

    lines.append(
        f"  ALIGNMENT CHECK: Verify each value matches its column description. "
        f"Numbers go in number columns, names go in name columns. "
        f"If a column appears empty in the image, output \"\" — do NOT shift other values into it."
    )

    return "\n".join(lines)


async def ocr_full_page(
    img_base64: str,
    expected_headers: Optional[List[str]] = None,
    extraction_hints: Optional[Dict[str, str]] = None,
) -> Dict:
    """OCR an entire register page image using vision LLM with fabrication detection."""

    # Build structured column definitions (merging user hints + auto-hints)
    col_block = _build_column_definitions(expected_headers, extraction_hints)
    if col_block:
        col_block = "\n\n" + col_block

    user_prompt = (
        "Read the handwritten/printed table from this register page image.\n"
        "READING RULES:\n"
        "- Extract every data row exactly as written. Read each cell individually.\n"
        "- PRESERVE all separators: / (slashes), - (dashes), x (in sizes), spaces within values.\n"
        "- Empty/blank cells = \"\" (empty string). Do NOT copy values from other cells.\n"
        "- Align each value precisely to its correct column. Count columns carefully.\n"
        "- For handwriting: read carefully, distinguish similar chars (0 vs O, 1 vs l, 5 vs S).\n"
        "CRITICAL: Only output what you can actually see. Never generate fake or sequential data."
        + col_block
    )

    # Attempt 1: Standard extraction
    result = await _call_vision_llm(img_base64, OCR_SYSTEM, user_prompt)
    headers = result.get("headers", [])
    rows = result.get("rows", [])

    if rows and detect_fabrication(headers, rows):
        print("[ocr_engine] Attempt 1 produced fabricated data. Retrying with stricter prompt...")
        # Attempt 2: Retry with stronger anti-hallucination prompt + hints
        retry_result = await _retry_extraction(img_base64, expected_headers, extraction_hints)
        retry_headers = retry_result.get("headers", [])
        retry_rows = retry_result.get("rows", [])

        if retry_rows and not detect_fabrication(retry_headers, retry_rows):
            print("[ocr_engine] Retry produced non-fabricated data. Using retry result.")
            return retry_result
        else:
            print("[ocr_engine] Retry also fabricated. Returning empty — model cannot read this image.")
            return {"headers": expected_headers or [], "rows": [], "confidence": 0.0}

    return result


async def _call_vision_llm(
    img_base64: str,
    system_prompt: str,
    user_prompt: str,
) -> Dict:
    """Call vision LLM and parse the JSON response."""
    try:
        raw = await llm_service.unified_chat_completion(
            system_prompt,
            user_prompt,
            image_base64=img_base64,
            image_mime_type="image/jpeg",
            max_tokens=8000,
        )
        print(f"[ocr_engine] LLM response ({len(raw)} chars): {raw[:400]}")

        result = parse_llm_json(raw)
        headers = result.get("headers", [])
        rows = result.get("rows", [])

        # Normalize row lengths
        if headers and rows:
            n = len(headers)
            normalized = []
            for row in rows:
                if isinstance(row, list):
                    if len(row) < n:
                        row = row + [""] * (n - len(row))
                    elif len(row) > n:
                        row = row[:n]
                    normalized.append(row)
            rows = normalized

        return {
            "headers": headers,
            "rows": rows,
            "confidence": float(result.get("confidence", 0.0)),
        }
    except Exception as exc:
        print(f"[ocr_engine] Vision LLM call failed: {exc}")
        return {"headers": [], "rows": [], "confidence": 0.0}


async def _retry_extraction(
    img_base64: str,
    expected_headers: Optional[List[str]] = None,
    extraction_hints: Optional[Dict[str, str]] = None,
) -> Dict:
    """Retry with minimal prompt, focused entirely on reading the image."""
    system = (
        "You are an OCR reader for Indian textile factory registers.\n"
        "STRICT RULES:\n"
        "- You MUST read from the actual image. NEVER output sequential data.\n"
        "- PRESERVE all separators: / - x spaces. '2/18 ZT' stays '2/18 ZT'.\n"
        "- Empty cells = \"\". Do NOT fill blanks with neighboring values.\n"
        "- Real handwritten data has irregular, unique values in each cell.\n"
        "If you cannot read the handwriting, return: {\"headers\":[], \"rows\":[], \"confidence\":0}\n"
        "Return ONLY JSON: {\"headers\":[...], \"rows\":[[...]], \"confidence\":N}"
    )

    col_block = _build_column_definitions(expected_headers, extraction_hints)
    col_hint = ("\n" + col_block) if col_block else ""

    user = (
        "Read this register image. Extract each handwritten value exactly as written." + col_hint
    )

    return await _call_vision_llm(img_base64, system, user)
