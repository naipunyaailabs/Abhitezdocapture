import os
import io
import uuid
import base64
import asyncio
import json
import re
import time
from typing import Dict, Any, List, Tuple
from PIL import Image
import fitz  # PyMuPDF
from app.services.llm_service import llm_service
from app.database import db


class ExtractIQService:
    """
    ExtractIQ - Intelligent Handwritten & Printed Data Extraction Service.
    
    Extracts data from documents (handwritten + printed) and maps them to
    user-defined column fields. The extracted data is editable and exportable
    as an Excel file.
    
    Key difference from Deep Parse:
    - User defines their own fields/columns (dynamic schema)
    - Optimized for handwritten content recognition
    - Generic document support (not limited to GST invoices)
    """

    def __init__(self):
        self.upload_dir = "app/static/uploads/extract-iq"
        os.makedirs(self.upload_dir, exist_ok=True)

    async def split_pdf_to_pages(self, buffer: bytes) -> List[Dict[str, Any]]:
        """Splits PDF into pages. Returns list of dicts with page_num, image_url, text, and img_base64."""
        pages = []
        try:
            doc = fitz.open(stream=buffer, filetype="pdf")
            for i, page in enumerate(doc):
                # Extract text directly from the page (works for digital PDFs)
                page_text = page.get_text().strip()

                # Render page to high-res image for display + vision
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))  # 300 DPI+ for better vision accuracy
                img_data = pix.tobytes("png")

                # Save image for the frontend viewer
                filename = f"eiq_page_{uuid.uuid4()}_{i+1}.png"
                filepath = os.path.join(self.upload_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(img_data)

                image_url = f"/static/uploads/extract-iq/{filename}"
                img_base64 = base64.b64encode(img_data).decode("utf-8")

                pages.append({
                    "page_number": i + 1,
                    "image_url": image_url,
                    "text": page_text,
                    "img_base64": img_base64
                })
            doc.close()
        except Exception as e:
            print(f"[ExtractIQService] Error splitting PDF: {e}")
        return pages

    async def process_image_file(self, buffer: bytes, filename: str) -> List[Dict[str, Any]]:
        """Process a single image file (JPG, PNG, etc). Returns a single-page list."""
        pages = []
        try:
            img = Image.open(io.BytesIO(buffer))
            # Convert to PNG for consistency
            png_buffer = io.BytesIO()
            img.save(png_buffer, format="PNG")
            img_data = png_buffer.getvalue()

            saved_filename = f"eiq_img_{uuid.uuid4()}.png"
            filepath = os.path.join(self.upload_dir, saved_filename)
            with open(filepath, "wb") as f:
                f.write(img_data)

            image_url = f"/static/uploads/extract-iq/{saved_filename}"
            img_base64 = base64.b64encode(img_data).decode("utf-8")

            pages.append({
                "page_number": 1,
                "image_url": image_url,
                "text": "",  # Images don't have embedded text
                "img_base64": img_base64
            })
        except Exception as e:
            print(f"[ExtractIQService] Error processing image: {e}")
        return pages

    def _build_system_prompt(self, field_definitions: List[Dict[str, str]]) -> str:
        """Builds a dynamic system prompt based on user-defined fields."""
        
        field_list = ""
        for i, field in enumerate(field_definitions, 1):
            field_key = field.get("key", f"field_{i}")
            field_label = field.get("label", field_key)
            field_desc = field.get("description", "")
            desc_part = f" - {field_desc}" if field_desc else ""
            field_list += f"{i}. **{field_label}** (key: `{field_key}`){desc_part}\n"

        system_prompt = (
            "You are an Expert Forensic Data Extractor specializing in reading HANDWRITTEN "
            "and PRINTED content from document images.\n\n"
            "Your Mission: Perform ZERO-LOSS extraction of ALL requested data fields from the "
            "provided document page image. You must read both printed text AND handwritten entries "
            "with maximum accuracy.\n\n"
            "EXTRACTION GUIDELINES:\n"
            "- READ THE IMAGE CAREFULLY. The image is your PRIMARY source of truth.\n"
            "- For handwritten text, examine the writing patterns, curves of letters, and context.\n"
            "- For stamps and seals, identify text within rectangular/circular boundaries.\n"
            "- Numbers with commas (e.g., '2,40,000.00') should be preserved as-is.\n"
            "- Dates should be preserved in whatever format they appear.\n"
            "- If supplementary OCR text is provided, use it as a cross-reference only.\n"
            "- NEVER guess or fabricate data. Only extract what is actually visible.\n"
            "- If a field is genuinely not present in the document, use empty string '' for value.\n\n"
            "CONFIDENCE SCORING:\n"
            "- 0.95+: Clear, printed text easily readable\n"
            "- 0.80-0.94: Printed text with minor quality issues\n"
            "- 0.60-0.79: Handwritten text that is legible\n"
            "- 0.40-0.59: Handwritten text that is partially legible\n"
            "- 0.0-0.39: Unclear/uncertain, or field not found\n\n"
            "FIELDS TO EXTRACT:\n"
            f"{field_list}\n"
            "OUTPUT FORMAT: Return ONLY valid JSON with ALL requested fields. "
            "Each field must have 'value' (string) and 'confidence' (float 0.0-1.0):\n"
            "{\n"
            '  "field_key_1": {"value": "extracted text", "confidence": 0.85},\n'
            '  "field_key_2": {"value": "extracted text", "confidence": 0.92},\n'
            "  ...all requested fields...\n"
            "}"
        )
        return system_prompt

    def _ensure_all_fields(self, extracted_fields: Dict[str, Dict[str, Any]], 
                           field_definitions: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
        """Ensures all user-defined fields are present with default values if missing."""
        result = {}
        for field in field_definitions:
            key = field.get("key", "")
            if not key:
                continue
            if key in extracted_fields:
                val = extracted_fields[key]
                if isinstance(val, dict):
                    if val.get("value") is not None:
                        val["value"] = str(val["value"])
                    else:
                        val["value"] = ""
                    result[key] = val
                else:
                    result[key] = {"value": str(val) if val else "", "confidence": 0.5}
            else:
                result[key] = {"value": "", "confidence": 0.0}
        return result

    def _post_process_fields(self, fields: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Post-process extracted fields to clean up common issues."""
        for key in fields:
            val = fields[key].get("value", "")
            # Normalize N/A variants to empty string
            if val and val.strip().lower() in [
                "n/a", "na", "none", "null", "not found", 
                "not available", "required", "not applicable",
                "not present", "not visible", "cannot read"
            ]:
                fields[key]["value"] = ""
                fields[key]["confidence"] = 0.0
            
            # Clean up extra whitespace
            if val:
                fields[key]["value"] = " ".join(val.split())
        
        return fields

    async def process_page(self, page_info: Dict[str, Any], 
                           field_definitions: List[Dict[str, str]],
                           doc_id: str) -> Dict[str, Any]:
        """Performs extraction for a single page using vision AI + text as supplementary context."""
        page_num = page_info["page_number"]
        image_url = page_info["image_url"]
        page_text = page_info["text"]
        img_base64 = page_info["img_base64"]

        try:
            system_prompt = self._build_system_prompt(field_definitions)

            # Build field list for user prompt
            field_names = ", ".join([f.get("label", f.get("key", "")) for f in field_definitions])

            print(f"[ExtractIQService] Page {page_num}: Using Vision LLM (text length: {len(page_text)} chars)")
            
            text_context = ""
            if page_text and len(page_text) > 20:
                text_context = (
                    "\n\nSUPPLEMENTARY OCR TEXT (may contain errors, use image as primary source):\n"
                    + page_text[:8000]
                )
            
            user_prompt = (
                f"Extract ALL of the following fields from this document image (Page {page_num}): "
                f"{field_names}. "
                "Read the image carefully for both printed and handwritten content. "
                "Return valid JSON only with 'value' and 'confidence' for each field."
                + text_context
            )
            
            raw_response = await llm_service.unified_chat_completion(
                system_prompt, user_prompt,
                image_base64=img_base64,
                image_mime_type="image/png"
            )

            # Parse JSON and ensure all fields
            extracted_fields = self._parse_llm_json(raw_response)
            extracted_fields = self._ensure_all_fields(extracted_fields, field_definitions)
            
            # Post-processing: clean up common issues
            extracted_fields = self._post_process_fields(extracted_fields)

            return {
                "page_number": page_num,
                "image_url": image_url,
                "fields": extracted_fields
            }
        except Exception as e:
            print(f"[ExtractIQService] Error processing page {page_num}: {e}")
            return {
                "page_number": page_num,
                "image_url": image_url,
                "fields": self._ensure_all_fields({}, field_definitions),
                "error": str(e)
            }

    def _parse_llm_json(self, raw_text: str) -> Dict[str, Dict[str, Any]]:
        try:
            # Try ```json ... ``` block first
            json_match = re.search(r'```json\s*(.*?)\s*```', raw_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            # Try ``` ... ``` block
            json_match = re.search(r'```\s*(.*?)\s*```', raw_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            # Try raw { ... }
            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
            return {}
        except Exception as e:
            print(f"[ExtractIQService] JSON parse error: {e}")
            print(f"[ExtractIQService] Raw LLM response (first 500 chars): {raw_text[:500]}")
            return {}

    async def extract_multi_page(self, buffer: bytes, filename: str,
                                  field_definitions: List[Dict[str, str]], 
                                  user_id: str) -> Dict[str, Any]:
        """Orchestrates the extraction of all pages from a document."""
        
        # Determine file type and split accordingly
        lower_name = filename.lower()
        if lower_name.endswith('.pdf'):
            pages = await self.split_pdf_to_pages(buffer)
        elif lower_name.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp')):
            pages = await self.process_image_file(buffer, filename)
        else:
            raise Exception(f"Unsupported file format: {filename}. Supported: PDF, JPG, PNG, BMP, TIFF, WebP")

        if not pages:
            raise Exception("Failed to process document into pages")

        # Cap at 100 pages for safety
        pages = pages[:100]

        # Process pages sequentially to avoid API rate limits
        records = []
        for page_info in pages:
            doc_id = f"EIQ-{uuid.uuid4().hex[:8].upper()}"
            record = await self.process_page(page_info, field_definitions, doc_id)
            records.append(record)

        return {
            "service": "extract_iq",
            "total_pages": len(records),
            "field_definitions": field_definitions,
            "records": records
        }


extract_iq_service = ExtractIQService()
