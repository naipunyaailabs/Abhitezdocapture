"""
Total-row reconciliation confidence for Lot History Card extraction.

WHY NOT logprobs or self-consistency:
  - Groq's vision models do not expose token logprobs.
  - Reading the card twice (self-consistency) measures STABILITY, not
    CORRECTNESS: a systematic misread (e.g. a smudged '7' read as '1' both
    times) agrees with itself and looks 100% confident while being wrong.

THE INDEPENDENT GROUND TRUTH:
  Every rope block on this form prints a TOTAL row at the bottom — the column
  sums for Total Pcs and Wt (e.g. "480  368"). That printed total is written by
  the operator and does NOT depend on how the model reads the individual roll
  cells. So we reconcile: do the extracted roll values actually add up to the
  printed totals? If they don't, the section is provably wrong and scores low.

  Example from a real card (Rope 2):
    extracted Wt: 18 + 91 + 102 + 97 = 308, but printed Wt total = 368.
    308 != 368  ->  the section is wrong (the 18 should be 78), so it must NOT
    show 100%. This module gives it a low score and names the mismatch.

Per-rope confidence:
  For each numeric column that has a printed total (Total Pcs, Wt (kg)):
    err = |extracted_sum - printed_total| / max(printed_total, 1)
    col_score = clamp(1 - err, 0, 1)
  Rope score = mean(col_score over columns that had a printed total).
  If a rope has rolls but NO printed total to check against, its score is None
  (unverifiable) rather than a fake 100%.

Header confidence:
  The header has no printed total to reconcile against, so we score it on
  completeness + format plausibility of its four fields (a real, deterministic
  check — all present and matching the expected digit shape = high).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

HEADER_FIELDS = ["I.O. No", "Dye Lot No", "Shade No", "Quality M.No"]
ROPE_KEYS = ["Rope 1", "Rope 2", "Rope 3"]

# Columns that carry a printed total we can reconcile against.
SUM_COLUMNS = ["Total Pcs", "Wt (kg)"]

# Expected shapes for header fields (used only for the header plausibility
# score, never to alter extracted values).
_HEADER_PATTERNS = {
    "I.O. No": re.compile(r"^\d{4,6}(-\d+)?$"),
    "Dye Lot No": re.compile(r"^\d{3,6}$"),
    "Shade No": re.compile(r"^\d{3,6}$"),
    "Quality M.No": re.compile(r"^\d{1,3}$"),
}


def _to_number(val: Any) -> Optional[float]:
    """Parse a cell into a number, or None if it isn't numeric."""
    if val is None:
        return None
    s = str(val).strip().replace(",", "")
    if s == "":
        return None
    m = re.search(r"-?\d+(\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _round(v: Optional[float]) -> Optional[int]:
    return None if v is None else max(0, min(100, int(round(v * 100))))


def _column_score(rolls: List[Dict[str, str]], printed_total: Optional[float], col: str) -> Optional[float]:
    """Score one column by how well its roll values sum to the printed total."""
    if printed_total is None:
        return None  # nothing independent to check against
    extracted = sum(
        (n for n in (_to_number(r.get(col)) for r in rolls) if n is not None)
    )
    denom = printed_total if printed_total != 0 else 1.0
    err = abs(extracted - printed_total) / denom
    return max(0.0, min(1.0, 1.0 - err))


def _rope_detail(rolls: List[Dict[str, str]], totals: Dict[str, str]) -> Dict[str, Any]:
    """Per-rope score plus a human-readable mismatch note for the UI."""
    col_scores: List[float] = []
    notes: List[str] = []
    for col in SUM_COLUMNS:
        printed = _to_number(totals.get(col))
        score = _column_score(rolls, printed, col)
        if score is None:
            continue
        col_scores.append(score)
        extracted = sum(
            (n for n in (_to_number(r.get(col)) for r in rolls) if n is not None)
        )
        if abs(extracted - printed) > 0.5:
            notes.append(f"{col} sum {int(extracted)} ≠ card total {int(printed)}")

    # Column-shift detection (independent of totals): the total-row check can't
    # see a misaligned Roll No, because Total Pcs can still sum correctly while
    # the Roll No column was copied from another column. If, on multiple rows,
    # the Roll No equals that row's Total Pcs, the model almost certainly slid
    # the Total Pcs column into Roll No.
    shift_hits = 0
    shift_rows = 0
    for r in rolls:
        roll_no = _to_number(r.get("Roll No"))
        pcs = _to_number(r.get("Total Pcs"))
        if roll_no is None or pcs is None:
            continue
        shift_rows += 1
        if abs(roll_no - pcs) < 0.5:
            shift_hits += 1
    shift_penalty: Optional[float] = None
    if shift_rows >= 2 and shift_hits >= 2:
        # Fraction of rows where Roll No was copied from Total Pcs.
        frac = shift_hits / shift_rows
        shift_penalty = max(0.0, 1.0 - frac)
        notes.append(
            f"Roll No matches Total Pcs on {shift_hits} of {shift_rows} rows "
            f"(column likely misaligned)"
        )

    candidates = list(col_scores)
    if shift_penalty is not None:
        candidates.append(shift_penalty)

    if not candidates:
        # Rolls exist but nothing independent to check against -> unverifiable.
        return {"score": None, "note": ""}
    # Weakest-link: ANY failing check (a total that doesn't reconcile OR a
    # misaligned Roll No column) means the section is wrong, so the worst signal
    # dominates rather than being averaged away into a falsely-green score.
    return {"score": _round(min(candidates)), "note": "; ".join(notes)}


def _header_score(header: Dict[str, str]) -> Optional[int]:
    """Completeness + format plausibility of the four header fields."""
    scores: List[float] = []
    for field in HEADER_FIELDS:
        val = str(header.get(field, "")).strip()
        if not val:
            scores.append(0.0)
            continue
        pat = _HEADER_PATTERNS.get(field)
        scores.append(1.0 if (pat is None or pat.match(val)) else 0.5)
    if not scores:
        return None
    return _round(sum(scores) / len(scores))


def score_sections(
    header: Dict[str, str],
    rolls_by_rope: Dict[str, List[Dict[str, str]]],
    totals_by_rope: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    """Compute per-section confidence.

    Returns:
      {
        "available": bool,
        "sections": {"header": 0-100|None, "Rope 1": ..., ...},
        "notes":    {"Rope 1": "Wt sum 308 ≠ card total 368", ...}
      }
    """
    sections: Dict[str, Optional[int]] = {"header": _header_score(header)}
    notes: Dict[str, str] = {}

    for key in ROPE_KEYS:
        rolls = rolls_by_rope.get(key, []) or []
        totals = totals_by_rope.get(key, {}) or {}
        if not rolls:
            sections[key] = None  # empty rope -> no badge
            continue
        detail = _rope_detail(rolls, totals)
        sections[key] = detail["score"]
        if detail["note"]:
            notes[key] = detail["note"]

    available = any(v is not None for v in sections.values())
    return {"available": available, "sections": sections, "notes": notes}
