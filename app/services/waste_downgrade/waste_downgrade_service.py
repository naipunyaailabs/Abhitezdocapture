"""
Waste & Downgrade Service — Vision LLM extraction for the Abhitex
"Wastage + Downgrade" register sheet.

Sheet structure:
    Row 1: DATE | <date value spanning to the right>
    Row 2: super-header "Wastage + Downgrade" spanning the grade columns
    Row 3: IO NO | A-GRADE | B-GRADE | C-GRADE | D-GRADE | CHINDI | POUCHA | SELVAGE | PATTI | Total
    Rows 4+: data

This service has FIXED columns (no template picking). It reuses the
register_extractor PDF/image pipeline for page splitting + OCR, then
extracts the page DATE separately via a small vision call.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.services.llm_service import llm_service
from app.services.register_extractor.register_service import register_extractor_service
from app.services.register_extractor.ocr_engine import ocr_full_page, parse_llm_json


COLUMNS: List[str] = [
    "IO NO",
    "A-GRADE",
    "B-GRADE",
    "C-GRADE",
    "D-GRADE",
    "CHINDI",
    "POUCHA",
    "SELVAGE",
    "PATTI",
    "Total",
]

EXTRACTION_HINTS: Dict[str, str] = {
    "IO NO": "EXACTLY 5 digits IO number (e.g. 84415, 84437, 84569, 85017). Never 6 digits. Never prepend row numbers. Match the exact handwriting.",
    "A-GRADE": "numeric waste/quality weight or quantity. Can be: integer (0, 12, 29), decimal (45.5, 32.2), or empty string (\"\"). Never add letters.",
    "B-GRADE": "numeric waste/quality weight or quantity. Integer, decimal, or empty string. Match handwriting exactly.",
    "C-GRADE": "numeric waste/quality weight or quantity. 0 means zero was written. Empty cell is always \"\".",
    "D-GRADE": "numeric waste/quality weight or quantity. Read exactly what is written.",
    "CHINDI": "numeric waste material weight. Can be 0 (written zero), decimal, or empty. Chindi = waste fibers.",
    "POUCHA": "numeric waste material weight. Poucha = cloth scraps/wastage. Integer, decimal, or empty.",
    "SELVAGE": "numeric selvage waste weight. Selvage = edge waste. Read exactly.",
    "PATTI": "numeric waste weight. Patti = scrap pieces. Integer, decimal, or empty.",
    "Total": "numeric total = sum of all grades and waste for this row. Read what is handwritten. NEVER compute yourself. Can be 0, integer, or decimal.",
}

# Enhanced system prompt specifically for Waste & Downgrade extraction with STRICT column preservation
WASTAGE_SYSTEM_PROMPT = (
    "You are an EXPERT OCR specialist for Indian textile factory 'Waste & Downgrade' registers.\n"
    "Your job is to read EXACTLY what is written, with PERFECT column alignment.\n\n"
    
    "THIS IS A WASTE & DOWNGRADE REGISTER - FIXED 10-COLUMN TABLE:\n"
    "Column 1: IO NO (5-digit item order, e.g., 84415, 85017, 84869, 89808)\n"
    "Column 2: A-GRADE (quality grade 1 weight)\n"
    "Column 3: B-GRADE (quality grade 2 weight)\n"
    "Column 4: C-GRADE (quality grade 3 weight)\n"
    "Column 5: D-GRADE (quality grade 4 weight)\n"
    "Column 6: CHINDI (waste fiber scraps)\n"
    "Column 7: POUCHA (cloth waste scraps)\n"
    "Column 8: SELVAGE (edge trim waste)\n"
    "Column 9: PATTI (scrap pieces waste)\n"
    "Column 10: Total (sum - read, don't calculate)\n\n"
    
    "CRITICAL - ZERO HANDLING (MUST DO THIS CORRECTLY):\n"
    "- If a cell shows '0' (zero digit handwritten), output: \"0\"\n"
    "- If a cell is completely blank (no marking), output: \"\"\n"
    "- DO NOT confuse zero with blank!\n"
    "- Examples: handwritten '0' → \"0\", blank cell → \"\"\n\n"
    
    "CRITICAL - COLUMN ALIGNMENT (MOST IMPORTANT):\n"
    "EVERY ROW MUST HAVE EXACTLY 10 VALUES IN EXACT ORDER:\n"
    "[IO NO, A-GRADE, B-GRADE, C-GRADE, D-GRADE, CHINDI, POUCHA, SELVAGE, PATTI, Total]\n\n"
    "If a cell is blank, use \"\" for that position - DO NOT SKIP IT.\n"
    "If a cell has '0', use \"0\" for that position.\n"
    "Count columns LEFT TO RIGHT. When you reach a blank cell, count it as an empty position.\n"
    "NEVER shift values left to fill blanks.\n"
    "NEVER merge columns.\n"
    "NEVER skip positions.\n\n"
    
    "EXAMPLE ROW READING:\n"
    "If you see: [5-digit] [0] [blank] [blank] [12] [0] [0] [0] [blank] [blank]\n"
    "Output: [\"84869\", \"0\", \"\", \"\", \"12\", \"0\", \"0\", \"0\", \"\", \"\"]\n"
    "NOT: [\"84869\", \"0\", \"12\", \"0\", \"0\", \"0\"] (WRONG - missing columns)\n\n"
    
    "NUMERIC VALUES:\n"
    "- Output '0' if zero is written\n"
    "- Output '' if cell is blank\n"
    "- Output integers as-is: '12', '46', '23'\n"
    "- Output decimals as-is: '45.5', '32.2'\n"
    "- NEVER add units or letters\n\n"
    
    "IO NO SPECIAL RULES:\n"
    "- Must be EXACTLY 5 digits\n"
    "- Examples: 84415, 85017, 84869, 89808, 85000, 85006, 85075, 85019, 85022\n"
    "- NEVER 6 digits, NEVER merge values\n\n"
    
    "OUTPUT FORMAT — RETURN ONLY VALID JSON:\n"
    '{\n'
    '  \"headers\": [\"IO NO\", \"A-GRADE\", \"B-GRADE\", \"C-GRADE\", \"D-GRADE\", \"CHINDI\", \"POUCHA\", \"SELVAGE\", \"PATTI\", \"Total\"],\n'
    '  \"rows\": [\n'
    '    [\"84869\", \"0\", \"\", \"\", \"12\", \"0\", \"0\", \"0\", \"\", \"\"],\n'
    '    [\"85000\", \"0\", \"\", \"\", \"18\", \"0\", \"0\", \"0\", \"\", \"\"],\n'
    '    [\"85006\", \"0\", \"\", \"\", \"10\", \"0\", \"0\", \"0\", \"\", \"\"]\n'
    '  ],\n'
    '  \"confidence\": 0.95\n'
    '}\n\n'
    
    "CONFIDENCE SCORING:\n"
    "- 0.95+: Perfect, all cells clearly readable\n"
    "- 0.85-0.94: Very good, minor ambiguity on 1-2 cells\n"
    "- 0.75-0.84: Good, some unclear cells but readable\n"
    "- Below 0.75: Poor quality, many ambiguous cells\n\n"
    
    "ABSOLUTE RULES:\n"
    "1. EVERY row gets EXACTLY 10 values (never more, never less)\n"
    "2. BLANKS stay as \"\" in their correct column position\n"
    "3. ZEROS are \"0\" not \"\"\n"
    "4. NO value shifting, NO merging, NO skipping\n"
    "5. NO explanations - ONLY JSON output."
)


DATE_SYSTEM_PROMPT = (
    "You are reading a Waste & Downgrade register page from an Indian textile factory.\n"
    "At the TOP of the page, there is a DATE field with a handwritten date value.\n"
    "Your job: Read EXACTLY what is written in the DATE field.\n\n"
    
    "DATE FORMATS IN THESE REGISTERS:\n"
    "- Indian format with slashes: 3/5/96 (day/month/year)\n"
    "- Mixed format: 9.8/5/26 (dots and slashes)\n"
    "- Standard format: 08/06/26, 12/05/25\n"
    "- Other: 5 May 2026, 3 JUN 2025\n\n"
    
    "RULES:\n"
    "1. Preserve EXACTLY what is written: slashes, dots, spacing, numbers, letters\n"
    "2. Do NOT convert formats (e.g., '3/5/96' stays '3/5/96', not '03/05/1996')\n"
    "3. If date is unclear, output your best reading\n"
    "4. If no date visible, output empty string ''\n\n"
    
    "Output JSON: {\"date\": \"<exact_date_string>\"}"
)


async def _extract_page_date(img_base64: str) -> str:
    """Read the DATE header field from a single page image with specialized prompt."""
    try:
        raw = await llm_service.unified_chat_completion(
            DATE_SYSTEM_PROMPT,
            (
                "This is a Waste & Downgrade register page. Read the DATE value shown at the top "
                "(examples: 3/5/96, 08/06/26, 9.8/5/26). "
                "Return EXACTLY what you read, preserving all slashes, dots, and formatting. "
                "Output JSON: {\"date\": \"<value>\"}."
            ),
            image_base64=img_base64,
            image_mime_type="image/jpeg",
            max_tokens=200,
        )
        result = parse_llm_json(raw)
        date_val = (result.get("date") or "").strip() if isinstance(result, dict) else ""
        return date_val
    except Exception as exc:
        print(f"[WasteDowngrade] DATE extract failed: {exc}")
        return ""


async def _extract_page_rows_specialized(img_base64: str, page_num: int) -> tuple[List[Dict[str, str]], float]:
    """
    Extract rows from a Waste & Downgrade page using specialized prompt.
    Returns (rows, confidence)
    """
    try:
        raw = await llm_service.unified_chat_completion(
            WASTAGE_SYSTEM_PROMPT,
            (
                "This is a Waste & Downgrade register page with a table showing:\n"
                "- Column 1: IO NO (5-digit item numbers)\n"
                "- Columns 2-5: A/B/C/D-GRADE waste quantities\n"
                "- Columns 6-9: CHINDI/POUCHA/SELVAGE/PATTI waste types (textile waste)\n"
                "- Column 10: Total (sum of all)\n\n"
                "Read EVERY visible row carefully. For each cell:\n"
                "- If blank: output empty string ''\n"
                "- If shows '0': output '0' (not empty)\n"
                "- If shows number: output exactly (e.g., '12', '45.5')\n"
                "- If cell is blank: output empty string ''\n"
                "- EVERY row must have exactly 10 values (no fewer, no more)\n"
                "- NEVER skip columns, NEVER shift values left\n\n"
                "Return complete JSON with ALL rows, ALL 10 columns per row, high accuracy confidence score."
            ),
            image_base64=img_base64,
            image_mime_type="image/jpeg",
            max_tokens=4000,
        )
        
        result = parse_llm_json(raw)
        if not isinstance(result, dict):
            return [], 0.0
        
        raw_rows: List[List[str]] = result.get("rows", [])
        confidence = float(result.get("confidence", 0.0))
        
        # Map rows to dictionaries with EXACT column preservation
        mapped_rows: List[Dict[str, str]] = []
        for row_idx, r in enumerate(raw_rows):
            if not isinstance(r, list):
                print(f"[WasteDowngrade] Page {page_num}: Skipping row {row_idx} - not a list")
                continue
            
            # Ensure row has exactly 10 values (pad if needed)
            while len(r) < len(COLUMNS):
                r.append("")
            
            row_dict: Dict[str, str] = {}
            for i, col in enumerate(COLUMNS):
                # Get value at position i, use empty string if out of bounds
                val = r[i] if i < len(r) else ""
                
                # Convert to string and strip whitespace
                val_str = str(val).strip() if val is not None else ""
                
                # CRITICAL FIX: Preserve zeros correctly
                # Only treat as empty if truly empty after strip
                # Keep "0" as "0", not as empty string
                row_dict[col] = val_str
            
            # Validate IO NO exists and is 5 digits
            io_no = row_dict.get("IO NO", "").strip()
            if not io_no or len(io_no) != 5 or not io_no.isdigit():
                if io_no:  # Log only if something was there
                    print(f"[WasteDowngrade] Page {page_num}, Row {row_idx}: Invalid IO NO '{io_no}' - skipping")
                continue
            
            # Keep row even if other columns are mostly empty (IO NO is the key identifier)
            mapped_rows.append(row_dict)
        
        print(
            f"[WasteDowngrade] Page {page_num}: "
            f"rows={len(mapped_rows)} conf={confidence*100:.1f}%"
        )
        return mapped_rows, confidence
        
    except Exception as exc:
        print(f"[WasteDowngrade] Row extraction failed (page {page_num}): {exc}")
        import traceback
        traceback.print_exc()
        return [], 0.0


class WasteDowngradeService:
    """Fixed-schema extractor for the Wastage + Downgrade sheet."""

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
        all_rows: List[Dict[str, str]] = []
        confidences: List[float] = []

        for page_info in pages:
            page_num = page_info["page_number"]
            img_b64 = page_info.get("img_base64", "")
            image_url = page_info.get("image_url", "")

            # Extract date using specialized prompt
            date_value = await _extract_page_date(img_b64)
            print(f"[WasteDowngrade] Page {page_num} - Extracted date: '{date_value}'")

            # Extract rows using specialized waste & downgrade prompt
            mapped_rows, confidence = await _extract_page_rows_specialized(img_b64, page_num)

            confidences.append(confidence)
            all_rows.extend(mapped_rows)
            
            # Log detailed row information for debugging
            if mapped_rows:
                print(f"[WasteDowngrade] Page {page_num} extracted {len(mapped_rows)} rows:")
                for idx, row in enumerate(mapped_rows[:3]):  # Show first 3 rows
                    print(f"  Row {idx+1}: IO={row.get('IO NO', '?')} A={row.get('A-GRADE', '?')} B={row.get('B-GRADE', '?')} C={row.get('C-GRADE', '?')} D={row.get('D-GRADE', '?')}")
                if len(mapped_rows) > 3:
                    print(f"  ... and {len(mapped_rows) - 3} more rows")

            page_results.append({
                "page_number": page_num,
                "image_url": image_url,
                "date": date_value,
                "headers": COLUMNS,
                "rows": mapped_rows,
                "confidence": confidence,
            })

            print(
                f"[WasteDowngrade] Page {page_num} complete: "
                f"date='{date_value}' rows={len(mapped_rows)} conf={confidence*100:.1f}%"
            )

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "service": "waste_downgrade",
            "filename": filename,
            "total_pages": len(page_results),
            "total_rows": len(all_rows),
            "headers": COLUMNS,
            "rows": all_rows,
            "pages": page_results,
            "average_confidence": avg_conf,
        }

    async def extract_streaming(self, buffer: bytes, filename: str):
        """
        Extract pages and yield results progressively.
        Yields JSON objects for each completed page, allowing frontend to display as they complete.
        """
        lower = filename.lower()

        if lower.endswith(".pdf"):
            pages = await register_extractor_service.split_pdf_to_pages(buffer)
        elif lower.endswith((".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")):
            pages = await register_extractor_service.process_image_file(buffer, filename)
        else:
            raise ValueError(f"Unsupported file: {filename}")

        if not pages:
            raise ValueError("Failed to parse document into pages.")

        # Yield metadata first
        yield json.dumps({
            "type": "metadata",
            "total_pages": len(pages),
            "filename": filename
        }).encode() + b"\n"

        all_confidences: List[float] = []

        for idx, page_info in enumerate(pages, start=1):
            page_num = page_info["page_number"]
            img_b64 = page_info.get("img_base64", "")
            image_url = page_info.get("image_url", "")

            try:
                # Extract date using specialized prompt
                date_value = await _extract_page_date(img_b64)
                print(f"[WasteDowngrade] Page {page_num} - Extracted date: '{date_value}'")

                # Extract rows using specialized waste & downgrade prompt
                mapped_rows, confidence = await _extract_page_rows_specialized(img_b64, page_num)

                all_confidences.append(confidence)

                page_result = {
                    "type": "page",
                    "page_number": page_num,
                    "image_url": image_url,
                    "date": date_value,
                    "headers": COLUMNS,
                    "rows": mapped_rows,
                    "confidence": confidence,
                    "page_index": idx,
                }

                # Yield this page's result immediately
                yield json.dumps(page_result).encode() + b"\n"
                print(f"[WasteDowngrade] Streamed page {page_num}")

            except Exception as e:
                print(f"[WasteDowngrade] Error processing page {page_num}: {e}")
                import traceback
                traceback.print_exc()
                # Yield error result for this page
                yield json.dumps({
                    "type": "page_error",
                    "page_number": page_num,
                    "error": str(e)
                }).encode() + b"\n"

        # Yield final summary
        avg_conf = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
        yield json.dumps({
            "type": "complete",
            "total_pages": len(pages),
            "average_confidence": avg_conf
        }).encode() + b"\n"


waste_downgrade_service = WasteDowngradeService()
