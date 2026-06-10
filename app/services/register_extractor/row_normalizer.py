"""
Row Normalizer — Deterministic post-processing for register extraction.

Two responsibilities:
  1. Resolve ditto marks ("do", "''", quotes, etc.) by copying the value from
     the same column in the row directly above. The LLM is asked to do this in
     the prompt, but it is unreliable on long handwritten pages — so we enforce
     it in Python after extraction.
  2. Flag values that violate the digit-count rule for their column (e.g. a
     5-digit IO Number that comes back as "0" or "850170"). Flagged cells are
     blanked so they don't pollute the output; the user can fix them by hand
     in the editable table.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# ── Ditto detection ──────────────────────────────────────────────────────────

# Values the LLM emits when a register cell contains a ditto mark.
# Lowercased + stripped before comparison.
_DITTO_TOKENS = {
    "do", "do.", "do,", "do-",
    "d/o", "d.o", "d.o.",
    "ditto",
    '"', '"', '"',          # ASCII + curly double quotes
    "''", "‘‘", "''",       # double single-quotes (typed ditto)
    "〃",                    # Japanese ditto mark (Unicode IDEOGRAPHIC DITTO MARK)
    ",,", ",,,",
    "—do—", "-do-",
    "same", "same as above", "as above",
}

# A bare comma or two commas often means "ditto" in handwritten registers.
_DITTO_PATTERN = re.compile(r"^\s*[,\"'`]{1,3}\s*$")


def _is_ditto(value: str) -> bool:
    if not value:
        return False
    v = value.strip().lower()
    if not v:
        return False
    if v in _DITTO_TOKENS:
        return True
    if _DITTO_PATTERN.match(v):
        return True
    return False


def resolve_dittos(rows: List[Dict[str, str]], headers: List[str]) -> List[Dict[str, str]]:
    """Replace ditto markers with the value from the same column in the row above.

    Operates in-place on a copy and returns the new list. If the row above is
    also a ditto (or empty), walks further up until a real value is found.
    """
    if not rows or not headers:
        return rows

    out: List[Dict[str, str]] = []
    for row_idx, row in enumerate(rows):
        new_row = dict(row)
        for col in headers:
            val = str(new_row.get(col, "") or "")
            if not _is_ditto(val):
                continue
            # Walk upward through already-resolved rows to find a real value.
            resolved = ""
            for prev_idx in range(row_idx - 1, -1, -1):
                candidate = str(out[prev_idx].get(col, "") or "").strip()
                if candidate and not _is_ditto(candidate):
                    resolved = candidate
                    break
            new_row[col] = resolved
        out.append(new_row)
    return out


# ── Digit-count enforcement ──────────────────────────────────────────────────

# Columns whose values must be a specific digit count. Bad values (wrong length,
# non-numeric, contain prefix garbage) are blanked.
_DIGIT_COUNT_RULES: Dict[str, Tuple[int, int]] = {
    "io no":       (5, 5),
    "io number":   (5, 5),
    "io#":         (5, 5),
    "i.o. no":     (5, 5),
    "lot no":      (5, 5),
    "lot number":  (5, 5),
    "lot":         (5, 5),
    "style code":  (5, 6),
    "r.no":        (5, 5),
}


def _clean_numeric(value: str) -> str:
    """Strip surrounding whitespace and trailing punctuation that the LLM
    sometimes emits ('85017.', '85017,'). Returns the inner digit run if the
    value is clearly numeric, otherwise the original stripped value.
    """
    v = value.strip().rstrip(".,;:")
    return v


def enforce_digit_counts(rows: List[Dict[str, str]], headers: List[str]) -> Tuple[List[Dict[str, str]], int]:
    """Blank cells whose value violates the expected digit count for the column.

    Returns (new_rows, n_fixed). Cells we couldn't trust are set to "" so the
    user is prompted to re-check rather than getting a wrong number that looks
    plausible.
    """
    if not rows or not headers:
        return rows, 0

    # Build a lookup: header (as it appears in the row) → digit rule
    col_rules: Dict[str, Tuple[int, int]] = {}
    for col in headers:
        rule = _DIGIT_COUNT_RULES.get(col.strip().lower())
        if rule:
            col_rules[col] = rule

    if not col_rules:
        return rows, 0

    n_fixed = 0
    out: List[Dict[str, str]] = []
    for row in rows:
        new_row = dict(row)
        for col, (min_d, max_d) in col_rules.items():
            raw = str(new_row.get(col, "") or "")
            if not raw.strip():
                continue
            cleaned = _clean_numeric(raw)
            # Must be all digits, no separators, no letters.
            if not cleaned.isdigit():
                # Common LLM mistake: extracts "do" / "0" / "—" into a number
                # column. Blank it so it surfaces in the editable view.
                if cleaned in {"0", "00", "000", "-", "—", "_"}:
                    new_row[col] = ""
                    n_fixed += 1
                continue
            length = len(cleaned)
            if length < min_d or length > max_d:
                # Wrong digit count — blank rather than emit a wrong-looking number.
                print(f"[row_normalizer] Blanked '{col}'='{raw}' (len={length}, expected {min_d}-{max_d})")
                new_row[col] = ""
                n_fixed += 1
            else:
                new_row[col] = cleaned
        out.append(new_row)
    return out, n_fixed


# ── Combined entry point ─────────────────────────────────────────────────────

def normalize_rows(rows: List[Dict[str, str]], headers: List[str]) -> List[Dict[str, str]]:
    """Run the full deterministic normalization pipeline.

    Order matters: resolve dittos FIRST (so a 'do' under a valid IO# becomes
    that IO#), then enforce digit counts (so bad numerics are blanked).
    """
    rows = resolve_dittos(rows, headers)
    rows, n_blanked = enforce_digit_counts(rows, headers)
    if n_blanked:
        print(f"[row_normalizer] {n_blanked} cell(s) blanked for failing digit-count rules")
    return rows
