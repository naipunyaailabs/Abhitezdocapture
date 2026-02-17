import os
import io
import uuid
import base64
import pytesseract
from PIL import Image
from typing import Dict, Any, Tuple
from app.utils.pdf_parser import pdf_parser
from app.services.llm_service import llm_service
import json

class ExtractService:
    async def extract_doc(self, buffer: bytes, file_name: str, file_type: str) -> str:
        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
        print(f"[extract_doc] file_name: {file_name}, ext: {ext}, file_type: {file_type}")
        
        if (file_type and file_type == "application/pdf") or ext == "pdf":
            return await self.extract_pdf_with_ocr_fallback(buffer)
        
        if (file_type and file_type.startswith("image/")) or ext in ["jpg", "jpeg", "png"]:
            return await self.ocr_image(buffer)

        if ext in ["doc", "docx"] or (file_type and "wordprocessingml" in file_type):
            return await self.extract_word_content(buffer)

        if (file_type and file_type == "text/plain") or ext == "txt":
            try:
                return buffer.decode('utf-8')
            except:
                return buffer.decode('latin-1', errors='ignore')
            
        # Fallback for other files
        b64 = base64.b64encode(buffer[:4000]).decode('utf-8')
        sys_prompt = f"You are an intelligent document parser. Extract ALL text and structure from this {file_type} file."
        usr_prompt = f"Document base64 (truncated): {b64}"
        return await llm_service.unified_chat_completion(sys_prompt, usr_prompt)

    async def extract_word_content(self, buffer: bytes) -> str:
        try:
            from docx import Document
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as tmp:
                tmp.write(buffer)
                tmp_path = tmp.name
            
            doc = Document(tmp_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            
            # Also extract tables
            table_text = []
            for table in doc.tables:
                for row in table.rows:
                    table_text.append(" | ".join(cell.text.strip() for cell in row.cells))
            
            os.unlink(tmp_path)
            return "\n\n".join(paragraphs + table_text)
        except Exception as e:
            print(f"Word Extraction Error: {e}")
            return ""

    async def ocr_image(self, buffer: bytes) -> str:
        try:
            image = Image.open(io.BytesIO(buffer))
            text = pytesseract.image_to_string(image)
            return text.strip()
        except Exception as e:
            print(f"OCR Error: {e}")
            return ""

    async def extract_pdf_with_ocr_fallback(self, buffer: bytes) -> str:
        # Try direct text extraction first
        text = await pdf_parser.extract_text(buffer)
        
        # Heuristic: if very little text, try OCR
        if len(text.strip()) < 50:
            print("[ExtractService] PDF has little text, attempting OCR fallback")
            images = await pdf_parser.pdf_to_images(buffer)
            ocr_text_parts = []
            for img_bytes in images:
                page_text = await self.ocr_image(img_bytes)
                ocr_text_parts.append(page_text)
            text = "\n\n".join(ocr_text_parts)
            
        return text.strip()

    async def structured_extraction(self, text: str) -> Dict[str, Any]:
        system_prompt = """You are an Expert Forensic Data Extractor.
Your Mission: Perform a zero-loss, exhaustive extraction of all data points from the provided document.

CRITICAL RULES:
1. **DO NOT MISS ANY INFORMATION**: If a detail exists in the text (numbers, IDs, names, dates, clauses), it MUST be captured.
2. **Exhaustive key_values**: Any information that does not fit the primary schema fields (title, author, etc.) MUST be included as a highly descriptive key-value pair in the 'key_values' object.
3. **Format Precision**: Output ONLY valid JSON. If a standard field is missing, use null, but prioritize finding it.
4. **Data Normalization**: Format dates as YYYY-MM-DD and normalize currency codes.
5. **Entity Recognition**: Correct any OCR errors by inferring context (e.g., '1nvoice' -> 'invoice')."""

        schema_instructions = """
        Target JSON Schema:
        {
            "title": "Main Document Heading or Primary Subject",
            "author": "The originating entity, person, or organization",
            "date": "Primary document date (normalized to YYYY-MM-DD)",
            "total_amount": "Final numeric value or total cost (number or string)",
            "currency": "3-letter currency code (USD, EUR, etc)",
            "key_values": {
                "invoice_number": "...", 
                "po_number": "...", 
                "delivery_address": "...",
                "payment_terms": "...",
                "tax_id": "...",
                "line_items": "Detailed summary of items if present",
                "notes": "Any extra fine print or remarks",
                ... (EXTRACT EVERY OTHER UNIQUE DATA POINT FOUND AS A KEY:VALUE PAIR)
            }
        }
        """
        user_prompt = f"Perform an exhaustive, detailed extraction of ALL data points from this text:\n\n{text[:20000]}\n\n{schema_instructions}"
        
        raw_response = await llm_service.unified_chat_completion(system_prompt, user_prompt)
        
        # Try to parse JSON
        try:
            # Simple cleanup for common LLM mistakes (Markdown blocks)
            clean_json = raw_response.strip()
            if clean_json.startswith("```"):
                clean_json = clean_json.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_json)
        except Exception as e:
            print(f"Structured extraction parse error: {e}")
            return {"raw_text": raw_response}

    async def extract_and_parse(self, buffer: bytes, file_name: str, file_type: str) -> Tuple[str, Dict[str, Any]]:
        text = await self.extract_doc(buffer, file_name, file_type)
        structured = await self.structured_extraction(text)
        return text, structured

extract_service = ExtractService()
