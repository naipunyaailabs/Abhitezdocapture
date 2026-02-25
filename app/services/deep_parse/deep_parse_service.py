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

class DeepParseService:
    def __init__(self):
        self.upload_dir = "app/static/uploads/deep-parse"
        os.makedirs(self.upload_dir, exist_ok=True)

    async def split_pdf_to_pages(self, buffer: bytes) -> List[Dict[str, Any]]:
        """Splits PDF into pages. Returns list of dicts with page_num, image_url, text, and img_base64."""
        pages = []
        try:
            doc = fitz.open(stream=buffer, filetype="pdf")
            for i, page in enumerate(doc):
                # 1. Extract text directly from the page (works for digital PDFs)
                page_text = page.get_text().strip()

                # 2. Render page to high-res image for display + vision
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))  # Higher DPI for better vision accuracy
                img_data = pix.tobytes("png")

                # Save image for the frontend viewer
                filename = f"page_{uuid.uuid4()}_{i+1}.png"
                filepath = os.path.join(self.upload_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(img_data)

                image_url = f"/static/uploads/deep-parse/{filename}"
                img_base64 = base64.b64encode(img_data).decode("utf-8")

                pages.append({
                    "page_number": i + 1,
                    "image_url": image_url,
                    "text": page_text,
                    "img_base64": img_base64
                })
            doc.close()
        except Exception as e:
            print(f"[DeepParseService] Error splitting PDF: {e}")
        return pages

    def _ensure_all_fields(self, extracted_fields: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Ensures all standard fields are present with default values if missing."""
        standard_fields = [
            "supplier_name", "gst_no", "invoice_no", "invoice_date",
            "buyer_name", "buyer_gst", "buyer_address",
            "challan_no", "challan_date", "gate_entry_no", "gate_entry_date",
            "document_id", "po_number", "item_code", "item_description",
            "hsn_code", "quantity", "unit_price", "total_amount",
            "cgst_amount", "sgst_amount", "igst_amount", "total_tax_amount", "grand_total", "discount"
        ]

        result = {}
        for field in standard_fields:
            if field in extracted_fields:
                # Ensure value is always a string
                val = extracted_fields[field]
                if isinstance(val, dict):
                    if val.get("value") is not None:
                        val["value"] = str(val["value"])
                    else:
                        val["value"] = ""
                    result[field] = val
                else:
                    result[field] = {"value": str(val) if val else "", "confidence": 0.5}
            else:
                result[field] = {"value": "", "confidence": 0.0}

        return result

    def _post_process_fields(self, fields: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Post-process extracted fields to clean up common issues."""
        
        # Clean GSTIN format - remove spaces
        for gst_field in ["gst_no", "buyer_gst"]:
            if gst_field in fields and fields[gst_field].get("value"):
                val = fields[gst_field]["value"].strip().replace(" ", "")
                fields[gst_field]["value"] = val

        # Clean numeric amounts - remove currency symbols, extra spaces
        numeric_fields = ["total_amount", "cgst_amount", "sgst_amount", "igst_amount", 
                         "total_tax_amount", "grand_total", "discount"]
        for nf in numeric_fields:
            if nf in fields and fields[nf].get("value"):
                val = fields[nf]["value"].strip()
                # Remove Rs., INR, etc. prefixes but keep the number with commas
                val = re.sub(r'^(Rs\.?|INR|₹)\s*', '', val, flags=re.IGNORECASE).strip()
                # Remove trailing /-
                val = re.sub(r'\s*/\-\s*$', '', val).strip()
                fields[nf]["value"] = val

        # Normalize "N/A", "NA", "None", "null" to empty string
        for key in fields:
            val = fields[key].get("value", "")
            if val and val.strip().lower() in ["n/a", "na", "none", "null", "not found", "not available", "required"]:
                fields[key]["value"] = ""
                fields[key]["confidence"] = 0.0

        return fields

    async def process_page(self, page_info: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
        """Performs extraction for a single page using vision (always) + text as supplementary context."""
        page_num = page_info["page_number"]
        image_url = page_info["image_url"]
        page_text = page_info["text"]
        img_base64 = page_info["img_base64"]

        try:
            system_prompt = (
                "You are an Expert Forensic Data Extractor specializing in Indian GST Tax Invoices, "
                "Delivery Challans, and Goods Receipt documents.\n\n"
                "Your Mission: Perform a ZERO-LOSS, exhaustive extraction of ALL data points from the "
                "provided document page image.\n\n"
                "DOCUMENT FORMAT CONTEXT:\n"
                "These are Indian GST invoices, typically containing:\n"
                "- A header section with supplier/seller details (company name, GSTIN, address)\n"
                "- Buyer/recipient details (name, GSTIN, address) - labeled 'Bill to', 'Billed to', "
                "'Buyer', 'Details of Receiver', 'Recipient Detail'\n"
                "- Invoice metadata (invoice number, date, PO number, vehicle number)\n"
                "- An items/goods table with HSN codes, quantities, rates, amounts\n"
                "- Tax breakdown (CGST, SGST, IGST percentages and amounts)\n"
                "- Grand total / Total invoice value\n"
                "- Often a GATE ENTRY STAMP (rectangular stamp with 'INWARD/OUT WARD' text containing: "
                "Date, Sr. No./Serial Number, Time, and a signature area)\n"
                "- Delivery/Challan reference numbers\n\n"
                "CRITICAL EXTRACTION RULES:\n\n"
                "1. **SUPPLIER NAME**: The company that ISSUED the invoice. Found in the header/letterhead "
                "area at the top. This is the SELLER, not the buyer.\n\n"
                "2. **GST NO (Supplier GSTIN)**: The GSTIN of the supplier/seller. Format: 2-digit state "
                "code + 10-char PAN + 1 + 1 + 1 check digit (e.g., '06ACEFA2270L1ZH'). Found near supplier name.\n\n"
                "3. **INVOICE NO**: The invoice reference number. Labels: 'Invoice No', 'Bill No', 'Inv. No.'\n\n"
                "4. **INVOICE DATE**: Date of the invoice. Output as DD-MM-YYYY. Labels: 'Date', 'Dated', 'Invoice Date'.\n\n"
                "5. **BUYER NAME**: The company RECEIVING goods. Labels: 'Bill to', 'Billed to', 'Buyer', "
                "'Recipient', 'Details of Receiver/Buyer'.\n\n"
                "6. **BUYER GST**: The GSTIN of the buyer/recipient.\n\n"
                "7. **BUYER ADDRESS**: Full address of the buyer/recipient.\n\n"
                "8. **CHALLAN NO**: Delivery challan number. Labels: 'Challan No', 'Delivery Note', "
                "'D.C. No.', 'IGP & Challan No'.\n\n"
                "9. **CHALLAN DATE**: Date on the delivery challan. Output as DD-MM-YYYY.\n\n"
                "10. **GATE ENTRY NO**: From the rectangular stamp labeled 'INWARD/OUT WARD'. "
                "Extract the 'Sr. No.' or serial number from this stamp.\n\n"
                "11. **GATE ENTRY DATE**: From the same INWARD/OUT WARD stamp. Extract the 'Date' field. "
                "Output as DD-MM-YYYY.\n\n"
                "12. **PO NUMBER**: Purchase Order number. Labels: 'PO No', 'P.O. No', 'Buyer\\'s Order No'.\n\n"
                "13. **ITEM DESCRIPTION**: Full description of goods/services. If multiple line items, "
                "combine ALL with ' | ' separator.\n\n"
                "14. **ITEM CODE**: Product/SKU code. If multiple, combine with ' | '.\n\n"
                "15. **HSN CODE**: HSN/SAC code (Indian tax classification). 4-8 digit number. "
                "If multiple, combine with ' | '.\n\n"
                "16. **QUANTITY**: Quantity of goods. Include unit if present (e.g., '2000 KG', '890 Boxes'). "
                "If multiple line items, combine with ' | '.\n\n"
                "17. **UNIT PRICE**: Rate per unit. If multiple line items, combine with ' | '.\n\n"
                "18. **TOTAL AMOUNT**: Taxable value before tax. Sum of line item amounts before GST.\n\n"
                "19. **CGST AMOUNT**: Central GST amount (numeric value only).\n\n"
                "20. **SGST AMOUNT**: State GST amount (numeric value only).\n\n"
                "21. **IGST AMOUNT**: Integrated GST amount (numeric value only). Often 0 for intra-state.\n\n"
                "22. **TOTAL TAX AMOUNT**: Sum of all taxes (CGST + SGST + IGST).\n\n"
                "23. **GRAND TOTAL**: Final invoice value including taxes. Labels: 'Grand Total', 'Total', "
                "'Net Amount', 'Invoice Value'.\n\n"
                "24. **DISCOUNT**: Any discount amount. If none found, use '0'.\n\n"
                "IMPORTANT NOTES:\n"
                "- ALWAYS read the IMAGE carefully. Text OCR may be garbled but the image is clear.\n"
                "- For handwritten fields (gate entry stamp, dates), read directly from the image.\n"
                "- Numbers with commas (e.g., '2,40,000.00') should be preserved as-is.\n"
                "- If a field is genuinely not present, use empty string '' for value and 0.0 for confidence.\n"
                "- NEVER guess or fabricate data. Only extract what is actually visible.\n"
                "- Confidence: 0.95+ for clear printed text, 0.7-0.9 for partially obscured, 0.5-0.7 for handwritten.\n\n"
                "OUTPUT FORMAT: Return ONLY valid JSON with ALL 24 fields (excluding document_id). "
                "Each field must have 'value' (string) and 'confidence' (float 0.0-1.0):\n"
                "{\n"
                '  "supplier_name": {"value": "COMPANY NAME", "confidence": 0.95},\n'
                '  "gst_no": {"value": "06XXXXX1234X1ZX", "confidence": 0.9},\n'
                "  ...all 24 fields...\n"
                "}"
            )

            # ALWAYS use vision for these invoice documents - text OCR is unreliable for scanned docs
            print(f"[DeepParseService] Page {page_num}: Using Vision LLM (text length: {len(page_text)} chars)")
            
            text_context = ""
            if page_text and len(page_text) > 20:
                text_context = (
                    "\n\nSUPPLEMENTARY OCR TEXT (may contain errors, use image as primary source):\n"
                    + page_text[:8000]
                )
            
            user_prompt = (
                f"Extract ALL 24 fields from this Indian GST invoice/bill image (Page {page_num}). "
                "Read the image carefully for handwritten stamps and gate entry details. "
                "Return valid JSON only. DO NOT return document_id."
                + text_context
            )
            
            raw_response = await llm_service.unified_chat_completion(
                system_prompt, user_prompt,
                image_base64=img_base64,
                image_mime_type="image/png"
            )

            # Parse JSON and ensure all fields
            extracted_fields = self._parse_llm_json(raw_response)
            extracted_fields = self._ensure_all_fields(extracted_fields)
            
            # Post-processing: clean up common issues
            extracted_fields = self._post_process_fields(extracted_fields)
            
            # FORCE injecting the generated document_id
            extracted_fields["document_id"] = {"value": doc_id, "confidence": 1.0}

            return {
                "page_number": page_num,
                "image_url": image_url,
                "fields": extracted_fields
            }
        except Exception as e:
            print(f"[DeepParseService] Error processing page {page_num}: {e}")
            return {
                "page_number": page_num,
                "image_url": image_url,
                "fields": self._ensure_all_fields({}),
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
            print(f"[DeepParseService] JSON parse error: {e}")
            print(f"[DeepParseService] Raw LLM response (first 500 chars): {raw_text[:500]}")
            return {}

    async def _get_next_document_id(self, user_id: str) -> str:
        """Fetches and increments the document sequence for a user."""
        try:
            database = await db.get_database() if callable(getattr(db, 'get_database', None)) else db.db
            if database is None:
                return f"A{str(int(time.time()))[-8:]}"

            seq_doc = await database["document_sequences"].find_one_and_update(
                {"user_id": user_id},
                {"$inc": {"sequence": 1}},
                upsert=True,
                return_document=True
            )
            seq_num = seq_doc["sequence"]
            return f"A{seq_num:08d}"
        except Exception as e:
            print(f"[DeepParseService] Error generating document ID: {e}")
            return f"A{str(int(time.time()))[-8:]}"

    async def extract_multi_page(self, buffer: bytes, user_id: str) -> Dict[str, Any]:
        """Orchestrates the extraction of all PDF pages."""
        # 1. Split PDF into pages with text + images
        pages = await self.split_pdf_to_pages(buffer)

        if not pages:
            raise Exception("Failed to split PDF into pages")

        # Cap at 100 pages for safety
        pages = pages[:100]

        # 2. Process pages sequentially to avoid Groq API rate limits
        records = []
        for page_info in pages:
            doc_id = await self._get_next_document_id(user_id)
            record = await self.process_page(page_info, doc_id)
            records.append(record)

        return {
            "service": "deep_parse",
            "total_pages": len(records),
            "records": records
        }

deep_parse_service = DeepParseService()
