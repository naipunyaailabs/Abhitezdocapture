"""
Header Detection & Column Mapping for Register Extraction.

Detects header rows, maps cell values to column names, and handles
user-defined column templates for improved accuracy.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


KNOWN_HEADERS = {
    "lot no", "lot number", "lot", "lot no.",
    "io no", "io number", "io", "i.o. no", "i.o. no.", "io no.", "io#",
    "i.no", "i. no", "i.no.",
    "r.no", "r. no", "r.no.", "r no", "roll no", "roll number",
    "l.no", "l. no", "l.no.", "l no",
    "sr no", "s.no", "s.no.", "serial", "serial no", "serial no.",
    "beam no", "beam no.",
    "shade", "shade no", "shade no.", "shade number", "shade name",
    "style", "style no", "style no.", "style code", "style type",
    "party", "party name", "buyer", "buyer name", "customer",
    "design", "design name",
    "size", "dimensions",
    "gsm", "g.s.m.", "g.s.m",
    "pcs", "pieces", "qty", "quantity",
    "kgs", "weight", "kg", "wt", "wt.",
    "thread no", "thread", "thread number", "thread no.",
    "loom no", "loom no.", "loom",
    "std", "act", "st", "bp", "dc", "cm",
    "hoo k", "hook",
    "s-terry", "d-end",
    "td pcs", "td", "d%",
    "string", "count", "ends", "d.b.f", "d.b.f.", "dbf", "length",
    "n.wt", "yarn party", "bks/10m", "oprater", "operator",
    "yarn count code", "yarn count",
    "remarks", "remark", "notes",
    "signature", "signatures", "sign", "opt. signature",
    "date",
    "description", "item", "particular", "particulars",
    "rate", "price", "amount", "total",
    "debit", "credit", "balance",
    "challan", "challan no", "invoice", "invoice no",
    "colour", "color",
    "shift",
    "grey wt", "after dye wt", "grey weight", "after dye weight",
    "buff name", "buyer name", "super name",
    "iob",
}


REGISTER_TEMPLATES: Dict[str, List[str]] = {
    # ── Primary templates (from user's actual register images) ────────────
    "prep_beam_issue_report": [
        "Beam No", "Party Name", "IO#", "Size", "Yarn Count Code",
        "Ends", "DBF", "Length", "Weight", "Lot", "Loom",
    ],
    "length_hemming_prod": [
        "Lot No", "Style Code", "IO Number", "Shade Name",
        "Style Type", "Party Name", "Size", "PCS", "KGS",
    ],
    "length_cutting_prod": [
        "Lot No", "Style Code", "IO Number", "Shade Name",
        "Style Type", "Party Name", "Size", "PCS", "KGS",
    ],
    "dyeing_to_machine": [
        "Style Code", "Lot No", "IO No", "Buyer Name",
        "Shade", "Style", "Grey Wt", "After Dye Wt",
    ],
    "dyeing_register_printed": [
        "Date", "Style Code", "Lot No", "IO No", "Party",
        "Shade", "Style", "Grey Wt", "After Dye Wt",
    ],
    # ── Legacy/generic templates ─────────────────────────────────────────
    "grey_inspection": [
        "I.NO", "R.NO", "L.NO", "Party", "Design",
        "Size", "PCS", "WT.", "STD", "ACT",
        "ST", "BP", "DC", "CM", "HOO K",
        "S-TERRY", "D-END", "TD PCS", "D%",
    ],
    "textile_production": [
        "Lot No", "IO No", "Shade", "Shade No", "Style",
        "Party Name", "Size", "GSM", "PCS", "KGS",
        "Thread No", "Opt. Signature", "Remarks",
    ],
    "hemming_production": [
        "Lot No", "I.O. No", "Shade", "Shade No", "Style",
        "Party Name", "Size", "GSM", "PCS", "KGS",
        "Thread No", "Opt. Signature", "Remarks", "Style No.",
    ],
    "beam_register": [
        "Beam No", "Party", "String", "Lot#", "Size",
        "Count", "Ends", "D.B.F", "Length",
    ],
    "stock_register": [
        "N.wt", "Lot", "Yarn Party",
        "BKS/10M", "Loom No", "Oprater",
    ],
    "dispatch_register": [
        "Lot No", "IO No", "Style", "Date", "Shade",
        "Size", "PCS", "KGS", "Loom/Name", "Style Code",
    ],
    "ledger": [
        "Date", "Particulars", "Voucher No",
        "Debit", "Credit", "Balance",
    ],
    "production_log": [
        "Date", "Shift", "Machine No", "Operator",
        "Item", "Qty Produced", "Qty Rejected", "Remarks",
    ],
    "inspection_report": [
        "Sr No", "Lot No", "Date", "Item", "Description",
        "Qty Inspected", "Accepted", "Rejected", "Remarks",
    ],
    "challan_register": [
        "Sr No", "Date", "Challan No", "Party Name",
        "Item", "Qty", "Rate", "Amount", "Remarks",
    ],
    "general_stock": [
        "Sr No", "Date", "Item", "Description",
        "Qty In", "Qty Out", "Balance", "Rate", "Amount", "Remarks",
    ],
}


def get_template(template_name: str) -> Optional[List[str]]:
    return REGISTER_TEMPLATES.get(template_name)


def get_available_templates() -> Dict[str, List[str]]:
    return dict(REGISTER_TEMPLATES)


def detect_header_row(rows: List[List[str]]) -> Tuple[int, List[str]]:
    """Detect which row is the header row based on content analysis."""
    if not rows:
        return 0, []

    best_idx = 0
    best_score = 0

    for idx, row in enumerate(rows[:5]):
        score = _header_score(row)
        if score > best_score:
            best_score = score
            best_idx = idx

    headers = rows[best_idx] if best_idx < len(rows) else []
    headers = [_normalize_header(h) for h in headers]
    return best_idx, headers


def map_rows_to_columns(
    headers: List[str],
    rows: List[List[str]],
) -> List[Dict[str, str]]:
    """Map raw row data to column-named dictionaries."""
    if not headers or not rows:
        return []

    mapped = []
    for row in rows:
        record = {}
        for i, header in enumerate(headers):
            if i < len(row):
                value = str(row[i]).strip() if row[i] else ""
            else:
                value = ""
            record[header] = value
        mapped.append(record)

    return mapped


def align_headers_with_template(
    detected_headers: List[str],
    template_headers: List[str],
) -> List[str]:
    """Align detected headers with template using fuzzy matching.

    Prevents duplicate mappings and ensures all template columns appear.
    If the LLM returns fewer headers, missing template columns are appended.
    """
    used: set = set()
    aligned = []
    remaining_templates = list(template_headers)

    for detected in detected_headers:
        best_match = _fuzzy_match_header(detected, remaining_templates)
        if best_match and best_match not in used:
            aligned.append(best_match)
            used.add(best_match)
            remaining_templates = [t for t in remaining_templates if t != best_match]
        else:
            aligned.append(detected)

    # If some template columns were never matched, append them so
    # map_rows_to_columns can still create those keys (with empty values).
    for tmpl in template_headers:
        if tmpl not in used and tmpl not in aligned:
            aligned.append(tmpl)

    return aligned


def _header_score(row: List[str]) -> int:
    if not row:
        return 0
    score = 0
    for cell in row:
        text = str(cell).strip().lower()
        if not text:
            continue
        if text in KNOWN_HEADERS:
            score += 3
        elif not text.replace(".", "").replace(",", "").isdigit() and len(text) < 30:
            score += 1
        elif text.replace(".", "").replace(",", "").isdigit():
            score -= 1
    return score


def _normalize_header(text: str) -> str:
    text = str(text).strip()
    if not text:
        return "Column"
    text = re.sub(r"\s+", " ", text)
    return text.title() if len(text) < 40 else text[:40].title()


def _fuzzy_match_header(detected: str, templates: List[str]) -> Optional[str]:
    """Multi-pass fuzzy matching: exact → base → stripped → substring → synonym.

    Separate passes prevent 'Style' from matching 'Style Code' via substring
    before the exact match with 'Style' is found.
    """
    detected_lower = detected.strip().lower()
    d_base = re.sub(r"[\s.]*(no|number|#|\.)\s*$", "", detected_lower).strip()
    d_stripped = re.sub(r"[^a-z0-9]", "", detected_lower)

    # Pass 1: Exact case-insensitive match
    for tmpl in templates:
        if detected_lower == tmpl.lower():
            return tmpl

    # Pass 2: Base-form match (strip trailing no/number/#)
    for tmpl in templates:
        t_base = re.sub(r"[\s.]*(no|number|#|\.)\s*$", "", tmpl.lower()).strip()
        if d_base and t_base and d_base == t_base:
            return tmpl

    # Pass 3: Stripped alphanumeric match
    for tmpl in templates:
        t_stripped = re.sub(r"[^a-z0-9]", "", tmpl.lower())
        if d_stripped and t_stripped and d_stripped == t_stripped:
            return tmpl

    # Pass 4: Substring match — prefer the template closest in length
    #  (avoids "style" matching "style code" when "style" template exists)
    substring_matches = []
    for tmpl in templates:
        tmpl_lower = tmpl.lower()
        if detected_lower in tmpl_lower or tmpl_lower in detected_lower:
            substring_matches.append(tmpl)
    if substring_matches:
        substring_matches.sort(key=lambda t: abs(len(t) - len(detected)))
        return substring_matches[0]

    # Pass 5: Synonym matching
    synonyms = {
        "wt": {"weight", "kgs", "kg"},
        "weight": {"wt", "kgs", "kg"},
        "kgs": {"weight", "wt", "kg"},
        "pcs": {"pieces", "qty", "quantity"},
        "pieces": {"pcs", "qty", "quantity"},
        "qty": {"pcs", "pieces", "quantity"},
        "sr no": {"serial", "serial no", "s.no"},
        "party": {"party name", "buyer", "buyer name", "customer"},
        "party name": {"party", "buyer", "buyer name", "customer"},
        "buyer name": {"party", "party name", "buyer"},
        "design": {"design name"},
        "style type": {"style"},
        "shade": {"shade no", "shade name", "colour", "color"},
        "shade name": {"shade", "shade no", "colour"},
        "lot": {"lot no", "lot number"},
        "io": {"io no", "i.o. no", "io number", "io#"},
        "io#": {"io no", "io number", "i.o. no"},
        "io number": {"io no", "io", "i.o. no", "io#"},
        "grey wt": {"grey weight"},
        "after dye wt": {"after dye weight"},
        "dbf": {"d.b.f", "d.b.f."},
        "d.b.f": {"dbf", "d.b.f."},
        "yarn count code": {"yarn count", "count code"},
        "beam no": {"beam no."},
    }
    for tmpl in templates:
        t_base = re.sub(r"[\s.]*(no|number|#|\.)\s*$", "", tmpl.lower()).strip()
        d_syns = synonyms.get(d_base, set())
        if t_base in d_syns or tmpl.lower() in d_syns:
            return tmpl
    return None
