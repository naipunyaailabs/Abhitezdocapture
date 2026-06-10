"""
Register Extractor Service — Multi-stage AI pipeline for extracting
structured table data from handwritten/printed registers.

Pipeline stages:
  1. Document parsing → page images
  2. Image preprocessing (PIL-based enhance + resize)
  3. OCR via domain-specific Vision LLM (textile factory knowledge)
  4. Header detection & column mapping
  5. LLM post-processing & OCR correction
  6. Data structuring & confidence scoring
  7. Multi-page merging
"""

from __future__ import annotations

import base64
import io
import time
import uuid
import os
from typing import Any, Dict, List, Optional

from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np
import fitz  # PyMuPDF

from app.services.register_extractor.ocr_engine import ocr_full_page, DEFAULT_COLUMN_HINTS
from app.services.register_extractor.header_mapper import (
    align_headers_with_template,
    detect_header_row,
    map_rows_to_columns,
)
from app.services.register_extractor.llm_postprocessor import (
    correct_ocr_data,
    validate_rows,
)
from app.services.register_extractor.data_structurer import (
    annotate_row_confidence,
    merge_pages,
    structure_page_result,
)
from app.services.register_extractor.row_normalizer import normalize_rows

MAX_LLM_IMAGE_DIM = 2000
MIN_LLM_IMAGE_DIM = 1200
MAX_PAGES = 200
PDF_RENDER_SCALE = 4  # 4x DPI for sharper handwriting (was 3x)

# ── Column pattern validators (used for shift detection) ────────────────────
import re as _re

_COLUMN_PATTERNS = {
    "style code":   _re.compile(r"^\d{5,6}$"),
    "lot no":       _re.compile(r"^\d{4,6}$"),
    "lot":          _re.compile(r"^\d{4,6}$"),
    "io no":        _re.compile(r"^\d{4,6}$"),
    "io number":    _re.compile(r"^\d{4,6}$"),
    "io#":          _re.compile(r"^\d{4,6}$"),
    "buyer name":   _re.compile(r"^[A-Za-z]"),
    "party name":   _re.compile(r"^[A-Za-z]"),
    "party":        _re.compile(r"^[A-Za-z]"),
    "shade":        _re.compile(r"^[A-Za-z]"),
    "shade name":   _re.compile(r"^[A-Za-z]"),
    "style":        _re.compile(r"^[A-Za-z0-9/]"),
    "grey wt":      _re.compile(r"^\d+\.?\d*$"),
    "after dye wt": _re.compile(r"^\d+\.?\d*$"),
    "pcs":          _re.compile(r"^\d+$"),
    "kgs":          _re.compile(r"^\d+\.?\d*$"),
    "beam no":      _re.compile(r"^[A-Za-z]"),
}


def _detect_and_fix_column_shift(
    mapped_rows: List[Dict[str, str]],
    expected_headers: List[str],
) -> List[Dict[str, str]]:
    """Detect and correct column misalignment using pattern validation.

    For each possible shift offset (-2, -1, +1, +2), check how many column
    values match their expected pattern.  If a shift produces more matches
    than the current alignment, apply it.
    """
    if not mapped_rows or not expected_headers or len(expected_headers) < 3:
        return mapped_rows

    # Build a list of values per column position
    n_cols = len(expected_headers)
    col_values: List[List[str]] = [[] for _ in range(n_cols)]
    for row in mapped_rows:
        for i, col in enumerate(expected_headers):
            val = row.get(col, "").strip()
            if val:
                col_values[i].append(val)

    # Score current alignment
    def _score_alignment(shift: int) -> int:
        score = 0
        for i, col in enumerate(expected_headers):
            pat = _COLUMN_PATTERNS.get(col.strip().lower())
            if not pat:
                continue
            src_idx = i + shift
            if 0 <= src_idx < n_cols:
                for val in col_values[src_idx]:
                    if pat.search(val):
                        score += 1
        return score

    current_score = _score_alignment(0)

    # Try shifts
    best_shift = 0
    best_score = current_score
    for shift in [-3, -2, -1, 1, 2, 3]:
        s = _score_alignment(shift)
        if s > best_score:
            best_score = s
            best_shift = shift

    if best_shift == 0 or best_score <= current_score:
        return mapped_rows

    # Apply shift: realign values
    print(
        f"[RegisterService] Column shift detected (shift={best_shift}, "
        f"score {current_score}->{best_score}). Correcting alignment."
    )
    corrected: List[Dict[str, str]] = []
    for row in mapped_rows:
        new_row: Dict[str, str] = {}
        for i, col in enumerate(expected_headers):
            src_idx = i + best_shift
            if 0 <= src_idx < n_cols:
                src_col = expected_headers[src_idx]
                new_row[col] = row.get(src_col, "")
            else:
                new_row[col] = ""
        corrected.append(new_row)
    return corrected


def _detect_rotation(img: Image.Image) -> int:
    """Detect the dominant orientation of table grid lines.

    Returns the rotation in degrees (0, 90, 180, 270) that should be applied
    to make the table horizontal (rows running left-to-right, columns top-to-bottom).
    Uses Hough lines on edges: if vertical lines dominate, the page is sideways.
    """
    try:
        arr = np.array(img.convert("L"))
        h, w = arr.shape

        # Downsample for speed
        scale = 800 / max(h, w) if max(h, w) > 800 else 1.0
        if scale < 1.0:
            small = cv2.resize(arr, (int(w * scale), int(h * scale)))
        else:
            small = arr

        edges = cv2.Canny(small, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=120)

        if lines is None or len(lines) == 0:
            # Fallback: if aspect is landscape but typical pages are portrait,
            # assume it's sideways.
            return 90 if w > h * 1.2 else 0

        horiz = 0
        vert = 0
        for line in lines[:200]:
            theta = line[0][1]
            # theta near 0 or pi → vertical line; near pi/2 → horizontal line
            deg = (theta * 180.0 / np.pi) % 180
            if deg < 20 or deg > 160:
                vert += 1
            elif 70 < deg < 110:
                horiz += 1

        # If the page has many more vertical lines than horizontal, the table
        # rows are running top-to-bottom — meaning the page is rotated 90°.
        # Long horizontal table rows should produce many horizontal lines.
        # If aspect is landscape AND verticals dominate, rotate 90° CW.
        if vert > horiz * 1.3 and w < h:
            # Portrait page with mostly vertical lines → table flowing vertically → rotate 90 CCW
            return 270
        if w > h and horiz < vert * 1.3:
            # Landscape page that doesn't have clear horizontal rows → rotate
            return 90
        return 0
    except Exception as exc:
        print(f"[RegisterService] rotation detect failed: {exc}")
        return 0


def _crop_to_content(img: Image.Image) -> Image.Image:
    """Crop to the bounding box of the inked content (the table area)
    plus a small margin. Removes scanner whitespace that wastes LLM tokens
    and forces the model to focus on the table.
    """
    try:
        arr = np.array(img.convert("L"))
        h, w = arr.shape
        # Threshold: ink is darker than background. Adaptive threshold handles
        # uneven lighting on photographed pages.
        _, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # Close small gaps so the table reads as one blob
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        coords = cv2.findNonZero(closed)
        if coords is None:
            return img
        x, y, cw, ch = cv2.boundingRect(coords)
        # Reject crop if it's too small (probably noise)
        if cw < w * 0.3 or ch < h * 0.3:
            return img
        # Add a small margin
        margin = max(10, int(min(w, h) * 0.01))
        x0 = max(0, x - margin)
        y0 = max(0, y - margin)
        x1 = min(w, x + cw + margin)
        y1 = min(h, y + ch + margin)
        cropped = img.crop((x0, y0, x1, y1))
        print(f"[RegisterService] Cropped {w}x{h} → {x1 - x0}x{y1 - y0} (removed {100 - int(100 * (x1-x0)*(y1-y0)/(w*h))}% whitespace)")
        return cropped
    except Exception as exc:
        print(f"[RegisterService] crop failed: {exc}")
        return img


def _preprocess_for_llm(img: Image.Image) -> bytes:
    """
    Preprocess image for the Vision LLM:
    - Auto-rotate so the table is horizontal
    - Crop to the table content (drop scanner whitespace)
    - Resize so longest side is between MIN and MAX
    - Contrast/sharpness boost for handwritten text
    - Output as JPEG (much smaller than PNG for API payload limits)
    """
    # Convert to RGB first
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Auto-rotate so the table reads left-to-right
    rotation = _detect_rotation(img)
    if rotation:
        img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
        print(f"[RegisterService] Auto-rotated by {rotation}°")

    # Crop to content
    img = _crop_to_content(img)

    w, h = img.size

    # Upscale very small images
    if max(w, h) < MIN_LLM_IMAGE_DIM:
        scale = MIN_LLM_IMAGE_DIM / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        w, h = new_w, new_h
        print(f"[RegisterService] Upscaled small image to {w}x{h}")

    # Resize large images to fit API limits
    if max(w, h) > MAX_LLM_IMAGE_DIM:
        ratio = MAX_LLM_IMAGE_DIM / max(w, h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        print(f"[RegisterService] Resized image from {w}x{h} → {new_w}x{new_h}")

    # Stronger enhance — handwriting in scanned ledgers is faint and blue ink
    # loses contrast against the printed grid. Boost contrast and sharpness.
    img = ImageEnhance.Contrast(img).enhance(1.4)
    img = ImageEnhance.Sharpness(img).enhance(1.6)

    # JPEG is 5-6x smaller than PNG — critical for API payload limits
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    print(f"[RegisterService] Preprocessed JPEG: {len(buf.getvalue())//1024}KB ({img.size[0]}x{img.size[1]})")
    return buf.getvalue()


class RegisterExtractorService:
    """
    Multi-stage AI pipeline for register/ledger table extraction.
    Uses domain-specific Vision LLM prompts optimized for Indian
    textile factory handwritten registers.
    """

    def __init__(self):
        self.upload_dir = "app/static/uploads/register"
        os.makedirs(self.upload_dir, exist_ok=True)

    # ── PDF / Image splitting ──────────────────────────────────────────────────

    async def split_pdf_to_pages(self, buffer: bytes) -> List[Dict[str, Any]]:
        pages = []
        try:
            doc = fitz.open(stream=buffer, filetype="pdf")
            for i, page in enumerate(doc):
                page_text = page.get_text().strip()
                pix = page.get_pixmap(matrix=fitz.Matrix(PDF_RENDER_SCALE, PDF_RENDER_SCALE))
                img_data = pix.tobytes("png")

                pil_img = Image.open(io.BytesIO(img_data))

                # Detect rotation once and apply to BOTH the display image and
                # the LLM image so the frontend viewer matches what the model
                # actually read. _preprocess_for_llm re-detects from the
                # already-rotated image (it will return 0) and adds the crop.
                rotation = _detect_rotation(pil_img)
                if rotation:
                    pil_img = pil_img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))
                    print(f"[RegisterService] Page {i+1}: rotated by {rotation}° for display")

                # Save the (rotated) full-res PNG for the frontend viewer
                filename = f"reg_page_{uuid.uuid4().hex[:8]}_{i+1}.png"
                filepath = os.path.join(self.upload_dir, filename)
                pil_img.save(filepath, format="PNG")

                image_url = f"/static/uploads/register/{filename}"

                # Preprocess for the LLM (will crop + resize; rotation is no-op now)
                llm_jpg = _preprocess_for_llm(pil_img)
                llm_b64 = base64.b64encode(llm_jpg).decode("utf-8")
                print(f"[RegisterService] Page {i+1}: LLM={len(llm_jpg)//1024}KB")

                pages.append({
                    "page_number": i + 1,
                    "image_url": image_url,
                    "text": page_text,
                    "img_base64": llm_b64,
                })
            doc.close()
        except Exception as e:
            print(f"[RegisterService] PDF split error: {e}")
        return pages

    async def process_image_file(self, buffer: bytes, filename: str) -> List[Dict[str, Any]]:
        try:
            img = Image.open(io.BytesIO(buffer))

            # Save full-res PNG for the frontend viewer
            png_buf = io.BytesIO()
            if img.mode in ("RGBA", "P", "LA"):
                img_rgb = img.convert("RGB")
            else:
                img_rgb = img
            img_rgb.save(png_buf, format="PNG")
            display_data = png_buf.getvalue()

            saved_name = f"reg_img_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(self.upload_dir, saved_name)
            with open(filepath, "wb") as f:
                f.write(display_data)

            image_url = f"/static/uploads/register/{saved_name}"

            # Preprocess for the LLM
            llm_jpg = _preprocess_for_llm(img)
            llm_b64 = base64.b64encode(llm_jpg).decode("utf-8")
            print(f"[RegisterService] Image: display={len(display_data)//1024}KB, LLM={len(llm_jpg)//1024}KB")

            return [{
                "page_number": 1,
                "image_url": image_url,
                "text": "",
                "img_base64": llm_b64,
            }]
        except Exception as e:
            print(f"[RegisterService] Image process error: {e}")
            return []

    # ── Page Processing Pipeline ──────────────────────────────────────────────

    async def _process_page(
        self,
        page_info: Dict[str, Any],
        expected_headers: List[str],
        extraction_hints: Dict[str, str],
    ) -> Dict[str, Any]:
        """Process a single page through the full extraction pipeline."""
        page_num = page_info["page_number"]
        img_b64 = page_info.get("img_base64", "")
        image_url = page_info.get("image_url", "")

        try:
            t_start = time.perf_counter()

            # Stage 3: OCR — full page vision extraction with domain knowledge
            t0 = time.perf_counter()
            ocr_result = await ocr_full_page(
                img_b64,
                expected_headers=expected_headers,
                extraction_hints=extraction_hints,
            )
            t_ocr = time.perf_counter() - t0

            raw_headers = ocr_result.get("headers", [])
            raw_rows = ocr_result.get("rows", [])
            confidence = ocr_result.get("confidence", 0.0)

            if not raw_rows:
                print(f"[RegisterService] Page {page_num}: no rows extracted | ocr={t_ocr:.2f}s")
                return structure_page_result(page_num, image_url, expected_headers, [], confidence)

            # Stage 4: Header detection & column mapping
            t0 = time.perf_counter()
            if raw_headers:
                headers = raw_headers
                data_rows = raw_rows
            else:
                header_idx, detected = detect_header_row(raw_rows)
                headers = detected if detected else [f"Column {i+1}" for i in range(len(raw_rows[0]))]
                data_rows = raw_rows[header_idx + 1:] if header_idx < len(raw_rows) else raw_rows

            # Align with user template columns
            if expected_headers:
                headers = align_headers_with_template(headers, expected_headers)

            mapped_rows = map_rows_to_columns(headers, data_rows)

            # Stage 4b: Column shift detection — fix misaligned columns
            if expected_headers and mapped_rows:
                mapped_rows = _detect_and_fix_column_shift(mapped_rows, expected_headers)

            # Stage 4c: Deterministic normalization — resolve ditto marks
            # (copy values from row above) and blank cells that violate the
            # column's digit-count rule. The LLM is asked to do dittos in the
            # prompt but is unreliable on long pages, so we enforce it here.
            if mapped_rows:
                mapped_rows = normalize_rows(mapped_rows, headers)

            t_header = time.perf_counter() - t0

            # Stage 5: LLM post-processing & correction
            t0 = time.perf_counter()
            if mapped_rows:
                mapped_rows = await correct_ocr_data(mapped_rows, headers, extraction_hints)
            t_correction = time.perf_counter() - t0

            t_total = time.perf_counter() - t_start
            print(
                f"[RegisterService] Page {page_num}: ocr={t_ocr:.2f}s | headers={t_header:.2f}s | "
                f"correction={t_correction:.2f}s | total={t_total:.2f}s | rows={len(mapped_rows)} | "
                f"conf={confidence*100:.0f}%"
            )

            # Stage 6: Validate & annotate confidence
            validation = validate_rows(mapped_rows, extraction_hints)
            annotate_row_confidence(mapped_rows, validation, confidence)

            return structure_page_result(
                page_num, image_url, headers, mapped_rows, confidence,
                validation=validation,
            )

        except Exception as exc:
            print(f"[RegisterService] Page {page_num} extraction failed: {exc}")
            return structure_page_result(page_num, image_url, expected_headers, [], 0.0)

    # ── Main Extraction ───────────────────────────────────────────────────────

    async def extract(
        self,
        buffer: bytes,
        filename: str,
        columns: List[str],
        hints: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        hints = hints or {}
        lower = filename.lower()

        # Stage 1: Parse document into pages
        if lower.endswith(".pdf"):
            pages = await self.split_pdf_to_pages(buffer)
        elif lower.endswith((".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")):
            pages = await self.process_image_file(buffer, filename)
        else:
            raise ValueError(f"Unsupported file: {filename}")

        if not pages:
            raise ValueError("Failed to process document into pages.")

        pages = pages[:MAX_PAGES]
        print(f"[RegisterService] Parsed {len(pages)} pages from {filename}")

        # Process each page through the full pipeline
        page_results = []
        for page_info in pages:
            result = await self._process_page(page_info, columns, hints)
            page_results.append(result)

        # Stage 7: Merge pages into unified dataset
        merged = merge_pages(page_results)

        # Strip internal metadata fields for the flat rows sent to the frontend
        flat_rows = []
        for row in merged["rows"]:
            flat_row = {k: v for k, v in row.items() if not k.startswith("_")}
            flat_rows.append(flat_row)

        avg_conf = merged["average_confidence"]

        return {
            "service": "register_extractor",
            "filename": filename,
            "total_pages": merged["total_pages"],
            "total_rows": len(flat_rows),
            "headers": columns,
            "rows": flat_rows,
            "pages": page_results,
            "average_confidence": avg_conf,
        }


register_extractor_service = RegisterExtractorService()
