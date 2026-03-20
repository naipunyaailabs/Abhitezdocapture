"""
LLM Post-Processing for OCR Correction & Validation.

Uses rule-based corrections and Groq LLM to:
  - Correct OCR errors (76xI42 → 76x142)
  - Normalize values
  - Validate numeric fields
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.services.llm_service import llm_service
from app.services.register_extractor.ocr_engine import parse_llm_json_array


CORRECTION_SYSTEM = (
    "You are a post-processing correction engine for OCR data extracted from Indian textile factory registers.\n\n"
    "CONTEXT: The data comes from handwritten registers at textile/fabric factories. Common register types include:\n"
    "- Grey Inspection Reports (columns: I.NO, R.NO, L.NO, Party, Design, Size, PCS, WT, STD, ACT, ST, BP, DC, CM, HOO K, etc.)\n"
    "- Hemming/Length Production Logs (columns: Lot No, IO No, Shade, Shade No, Style, Party Name, Size, GSM, PCS, KGS, Thread No)\n"
    "- Stock Registers (columns: N.wt, Lot, Yarn Party, BKS/10M, Loom No, Oprater)\n"
    "- Beam Registers (columns: Beam No, Party, String/Style, Lot#, Size, Count, Ends, D.B.F, Length)\n"
    "- Production/Dispatch Registers (columns: Lot No, IO No, Style, Shade, Size, PCS, KGS, Loom/Name, Style Code)\n\n"
    "DOMAIN KNOWLEDGE — USE THIS FOR CORRECTIONS:\n"
    "- Lot numbers: 5-digit numbers (24357, 22473, 24558). If OCR says 2435T or 2247E, fix to 24357, 22473.\n"
    "- IO numbers: 5-digit numbers (84370, 83851, 66044). Fix letter/digit confusion.\n"
    "- R.NO: 5-digit roll numbers (66044, 66045). Fix O→0, l→1, etc.\n"
    "- Style codes: 5-6 digit numbers (116045, 114228, 105532). Fix O→0, I→1.\n"
    "- Sizes MUST be in NUMBERxNUMBER format: 76x142, 30x30, 80x110, 41x76. \n"
    "  Fix: '76xI42'→'76x142', '30 x 30'→'30x30', '76xl42'→'76x142', '8OxllO'→'80x110'\n"
    "- PCS/Pieces: whole integers only (84, 280, 1970). Remove any letters.\n"
    "- KGS/Weight: numeric, can have decimals (164, 425, 967.5). Remove letters.\n"
    "- GSM: 3-4 digit number. Remove letters.\n"
    "- Party name abbreviations are valid: 'Rum', 'WSP', 'Mali', 'Moda' — do NOT change these.\n"
    "- Design names: 'Rutland', 'Pleat Border', 'Trade Wind', 'Infinite', 'Modern Waffle', 'Soft and Fluffy', \n"
    "  'Ginny P. Pink', 'Popcorn', 'Niza Solid', 'Simplicity', 'Park STP', 'Rugby Midnight Blue' — \n"
    "  fix only CLEAR OCR errors (e.g., 'Rut1and'→'Rutland', 'P1eat Border'→'Pleat Border')\n"
    "- BP, DC, CM, ST: typically 1-2 digit numbers. Fix letter/digit confusion.\n"
    "- Thread No: 4-5 digit numbers.\n"
    "- Beam numbers: alphanumeric like 'TP-08', 'TP-210', 'TS-211' — preserve the format.\n\n"
    "CORRECTION RULES:\n"
    "1. Fix common OCR letter/digit confusion: 0↔O, 1↔l↔I, 5↔S, 8↔B, 6↔G, 9↔g\n"
    "2. Fix dimension formats: '76xI42'→'76x142', '30 x 30'→'30x30'\n"
    "3. Normalize ALL numeric fields: remove stray characters\n"
    "4. For text fields (party, design, shade): fix only clear OCR letter substitutions\n"
    "5. Empty/illegible cells should stay as empty string ''\n"
    "6. Do NOT invent data that wasn't in the original\n"
    "7. Do NOT change party abbreviations or names that look correct\n"
    "8. Preserve the original meaning — only fix clear OCR errors\n\n"
    "Return ONLY valid JSON array of corrected row objects.\n"
    "Each object must have the same keys as the input."
)


VALIDATION_RULES = {
    "pcs": {"type": "integer", "pattern": r"^\d+$"},
    "pieces": {"type": "integer", "pattern": r"^\d+$"},
    "qty": {"type": "integer", "pattern": r"^\d+$"},
    "quantity": {"type": "integer", "pattern": r"^\d+$"},
    "kgs": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "weight": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "kg": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "wt": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "wt.": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "gsm": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "size": {"type": "dimension", "pattern": r"^(\d+[xX×]\d+([xX×]\d+)?|[A-Za-z ]+)$"},
    "dimensions": {"type": "dimension", "pattern": r"^\d+[xX×]\d+([xX×]\d+)?$"},
    "lot no": {"type": "string", "pattern": r"^\d+$"},
    "lot no.": {"type": "string", "pattern": r"^\d+$"},
    "lot number": {"type": "string", "pattern": r"^\d+$"},
    "io no": {"type": "string", "pattern": r"^\d+$"},
    "io no.": {"type": "string", "pattern": r"^\d+$"},
    "io number": {"type": "string", "pattern": r"^\d+$"},
    "io#": {"type": "string", "pattern": r"^\d+$"},
    "i.o. no": {"type": "string", "pattern": r"^\d+$"},
    "r.no": {"type": "string", "pattern": r"^\d+$"},
    "rate": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "amount": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "std": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "act": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "style code": {"type": "string", "pattern": r"^\d+$"},
    "style no": {"type": "string", "pattern": r"^\d+$"},
    "thread no": {"type": "string", "pattern": r"^\d+$"},
    "loom no": {"type": "string", "pattern": r"^\d+$"},
    "count": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "ends": {"type": "numeric", "pattern": r"^\d+$"},
    "d.b.f": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "dbf": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "length": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "grey wt": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    "after dye wt": {"type": "numeric", "pattern": r"^\d+\.?\d*$"},
    # beam no and yarn count code intentionally excluded — they have mixed formats
}


async def correct_ocr_data(
    rows: List[Dict[str, str]],
    headers: List[str],
    extraction_hints: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    """Apply rule-based corrections to fix common OCR errors.
    
    Note: LLM text-only correction is disabled because the text model
    cannot see the original image and was introducing fabricated data.
    Only deterministic rule-based corrections are applied.
    
    extraction_hints: User-provided hints that inform correction behavior.
    Columns with hints containing 'preserve' or separator-related keywords
    will skip aggressive cleaning.
    """
    if not rows:
        return []

    # Build a set of columns whose hints say to preserve separators
    preserve_cols: set = set()
    if extraction_hints:
        for col, hint in extraction_hints.items():
            hint_lower = hint.lower()
            if any(kw in hint_lower for kw in (
                "preserve", "slash", "separator", "as-is", "as is",
                "exact", "mixed", "alphanumeric", "with /", "with slash",
            )):
                preserve_cols.add(col.strip().lower())

    corrected = [_rule_based_correct(row, preserve_cols) for row in rows]
    print(f"[llm_postprocessor] Rule-based corrected {len(corrected)} rows"
          + (f" (preserving separators in: {preserve_cols})" if preserve_cols else ""))
    return corrected


def validate_rows(
    rows: List[Dict[str, str]],
    extraction_hints: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Validate extracted rows and return validation report.
    
    extraction_hints: User-provided hints can be used to derive
    dynamic validation patterns (e.g., "5-digit number" generates a digit-count check).
    """
    # Build hint-based validation overrides
    hint_patterns: Dict[str, str] = {}
    if extraction_hints:
        for col, hint in extraction_hints.items():
            pattern = _derive_pattern_from_hint(hint)
            if pattern:
                hint_patterns[col.strip().lower()] = pattern

    results = []
    for i, row in enumerate(rows):
        issues = []
        for key, value in row.items():
            if key.startswith("_"):
                continue
            key_lower = key.strip().lower()
            # Use hint-derived pattern if available, else default rules
            if key_lower in hint_patterns and value:
                if not re.match(hint_patterns[key_lower], value.strip()):
                    issues.append({
                        "column": key,
                        "value": value,
                        "expected_type": "hint-based",
                    })
            elif key_lower in VALIDATION_RULES and value:
                rule = VALIDATION_RULES[key_lower]
                if not re.match(rule["pattern"], value.strip()):
                    issues.append({
                        "column": key,
                        "value": value,
                        "expected_type": rule["type"],
                    })
        results.append({
            "row_index": i,
            "valid": len(issues) == 0,
            "issues": issues,
        })
    return results


def _derive_pattern_from_hint(hint: str) -> Optional[str]:
    """Derive a regex validation pattern from a user-provided hint string."""
    if not hint:
        return None
    h = hint.lower().strip()

    # "5-digit number" or "5 digit number"
    m = re.match(r"(\d+)[- ]?digit\s*(?:number|code|id)?", h)
    if m:
        n = int(m.group(1))
        return rf"^\d{{{n}}}$"

    # "whole number" or "integer"
    if "whole number" in h or "integer" in h:
        return r"^\d+$"

    # "decimal" or "numeric with decimal"
    if "decimal" in h:
        return r"^\d+\.?\d*$"

    # "alphanumeric with dash"
    if "alphanumeric" in h and "dash" in h:
        return r"^[A-Za-z0-9\-]+$"

    return None


def _rule_based_correct(row: Dict[str, str], preserve_cols: Optional[set] = None) -> Dict[str, str]:
    """Apply deterministic OCR corrections.
    
    preserve_cols: set of lowercased column names whose values should not
    be aggressively cleaned (user indicated to preserve separators).
    """
    preserve_cols = preserve_cols or set()
    corrected = {}
    for key, value in row.items():
        if key.startswith("_"):
            corrected[key] = value
            continue
        val = str(value).strip() if value else ""
        key_lower = key.strip().lower()

        if not val:
            corrected[key] = ""
            continue

        # If user hint says to preserve this column, skip all correction
        if key_lower in preserve_cols:
            corrected[key] = val
            continue

        # Skip correction for fields that contain compound/mixed values
        if key_lower in (
            "yarn count code", "yarn count", "count code",
        ):
            pass  # These have mixed alphanumeric with slashes — preserve as-is
        elif key_lower in ("beam no", "beam no."):
            pass  # Beam numbers like TP-06 have dashes — preserve as-is
        elif key_lower in (
            "pcs", "pieces", "qty", "quantity", "kgs", "weight", "kg", "wt", "wt.",
            "gsm", "g.s.m.", "rate", "amount", "std", "act", "st", "bp", "dc", "cm",
            "td pcs", "d%", "n.wt", "bks/10m", "count", "ends", "d.b.f", "dbf", "length",
            "grey wt", "after dye wt",
        ):
            val = _fix_numeric(val)
        elif key_lower in ("size", "dimensions"):
            val = _fix_dimension(val)
        elif key_lower in (
            "lot no", "io no", "lot", "io", "lot no.", "l.no",
            "io no.", "i.o. no", "i.no", "r.no", "r.no.",
            "io number", "io#", "lot number",
            "style code", "style no", "style no.", "thread no",
            "loom no", "loom no.",
        ):
            val = _fix_id_number(val)

        corrected[key] = val
    return corrected


def _fix_numeric(val: str) -> str:
    # If value contains slashes, it's a compound/ratio value — preserve as-is
    if "/" in val:
        return val
    val = val.replace("O", "0").replace("o", "0")
    val = val.replace("l", "1").replace("I", "1")
    val = val.replace("S", "5").replace("s", "5")
    val = val.replace("B", "8")
    val = re.sub(r"[^\d.]", "", val)
    val = val.rstrip(".")
    return val


def _fix_dimension(val: str) -> str:
    val = val.replace("×", "x").replace("X", "x")
    val = val.replace(" ", "")
    parts = val.split("x")
    fixed = []
    for p in parts:
        p = p.replace("O", "0").replace("o", "0")
        p = p.replace("l", "1").replace("I", "1")
        p = re.sub(r"[^\d]", "", p)
        if p:
            fixed.append(p)
    return "x".join(fixed) if fixed else val


def _fix_id_number(val: str) -> str:
    # If value contains dashes or slashes, it's a formatted code — preserve structure
    if "-" in val or "/" in val:
        return val
    val = val.replace("O", "0").replace("o", "0")
    val = val.replace("l", "1").replace("I", "1")
    val = val.replace("S", "5").replace("s", "5")
    val = val.replace("B", "8")
    cleaned = re.sub(r"[^\d]", "", val)
    return cleaned if cleaned else val


def _merge_correction(original: Dict[str, str], llm_corrected: Dict[str, str]) -> Dict[str, str]:
    """Merge LLM correction with original, preferring LLM for changed values."""
    merged = {}
    for key in original:
        if key.startswith("_"):
            merged[key] = original[key]
            continue
        orig_val = str(original.get(key, "")).strip()
        llm_val = str(llm_corrected.get(key, "")).strip()
        # Keep LLM correction if it's non-empty and different
        if llm_val and llm_val != orig_val:
            merged[key] = llm_val
        else:
            merged[key] = orig_val
    return merged
