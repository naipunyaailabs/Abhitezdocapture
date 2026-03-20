"""
Data Structuring for Register Extraction.

Handles confidence scoring, page result structuring,
multi-page merging, and column filtering.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def annotate_row_confidence(
    rows: List[Dict[str, Any]],
    validation: Optional[List[Dict]],
    page_confidence: float,
) -> List[Dict[str, Any]]:
    """Annotate each row with _confidence and _cell_conf dict."""
    bad_col_map: Dict[int, set] = {}
    for val_result in (validation or []):
        idx = val_result.get("row_index", -1)
        if idx >= 0:
            bad_col_map[idx] = {issue["column"] for issue in val_result.get("issues", [])}

    for i, row in enumerate(rows):
        bad_cols = bad_col_map.get(i, set())
        cell_conf: Dict[str, Optional[float]] = {}
        for col in row:
            if col.startswith("_"):
                continue
            val = row[col]
            if val is None or str(val).strip() == "":
                cell_conf[col] = None
            elif col in bad_cols:
                cell_conf[col] = round(page_confidence * 0.5, 3)
            else:
                cell_conf[col] = round(page_confidence, 3)
        row["_confidence"] = round(page_confidence, 3)
        row["_cell_conf"] = cell_conf

    return rows


def structure_page_result(
    page_number: int,
    image_url: str,
    headers: List[str],
    rows: List[Dict[str, str]],
    confidence: float,
    *,
    validation: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    return {
        "page_number": page_number,
        "image_url": image_url,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "col_count": len(headers),
        "confidence": round(confidence, 3),
        "validation": validation or [],
    }


def merge_pages(
    page_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge multiple page results into a unified dataset."""
    if not page_results:
        return {
            "headers": [],
            "rows": [],
            "total_rows": 0,
            "total_pages": 0,
            "average_confidence": 0.0,
        }

    canonical_headers = page_results[0].get("headers", [])

    all_rows: List[Dict[str, str]] = []
    confidences: List[float] = []

    for page in page_results:
        page_headers = page.get("headers", [])
        for row in page.get("rows", []):
            if page_headers != canonical_headers:
                remapped = _remap_row(row, page_headers, canonical_headers)
                all_rows.append(remapped)
            else:
                all_rows.append(row)

        conf = page.get("confidence", 0.0)
        if conf > 0:
            confidences.append(conf)

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    return {
        "headers": canonical_headers,
        "rows": all_rows,
        "total_rows": len(all_rows),
        "total_pages": len(page_results),
        "average_confidence": round(avg_conf, 3),
    }


def filter_columns(
    rows: List[Dict[str, str]],
    selected_columns: List[str],
) -> List[Dict[str, str]]:
    if not selected_columns:
        return rows

    selected_lower = {c.strip().lower(): c.strip() for c in selected_columns}
    filtered = []
    for row in rows:
        new_row = {}
        for key, val in row.items():
            if key.strip().lower() in selected_lower:
                new_row[selected_lower[key.strip().lower()]] = val
        if new_row:
            filtered.append(new_row)
    return filtered


def _remap_row(
    row: Dict[str, str],
    source_headers: List[str],
    target_headers: List[str],
) -> Dict[str, str]:
    remapped = {h: "" for h in target_headers}
    target_lower = {h.lower(): h for h in target_headers}

    for key, val in row.items():
        if key.startswith("_"):
            remapped[key] = val
            continue
        key_lower = key.strip().lower()
        if key_lower in target_lower:
            remapped[target_lower[key_lower]] = val
    return remapped
