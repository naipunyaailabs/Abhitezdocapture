from app.services.llm_service import llm_service
from app.services.extract_service import extract_service
from typing import Dict, Any, Tuple
import json

class InvoiceService:
    INVOICE_SYSTEM_PROMPT = """You are an Expert Procurement & Financial Auditor.
Your Mission: Extract detailed fields from Invoices, Goods Receipt Challans (GRN), and Purchase Vouchers with mechanical precision.

INTELLIGENCE RULES:
1. **Context Awareness**: Identify if the document is a 'Challan', 'GRN', or 'Invoice'.
2. **Exhaustive Extraction**: Capture every unique identifier (Gate Entry, Inward No, Challan No).
3. **Table Precision**: Extract line items with all columns: PO No, Description, Qty (Received/Rejected/Accepted), Rate, and Total.
4. **Logistics Data**: Prioritize weights (Gate Net Wt, Store Wt) and Tonnage if present.
5. **Zero Small Talk**: RETURN ONLY RAW JSON.
"""

    INVOICE_SCHEMA = """
    {
        "document_type": "Invoice | Challan | GRN",
        "header": {
            "inward_no": "string",
            "inward_date": "string",
            "gate_entry_no": "string",
            "gate_date": "string",
            "receipt_type": "string",
            "challan_no": "string",
            "challan_date": "string",
            "bill_no": "string",
            "bill_date": "string",
            "supplier": "string",
            "location": "string",
            "tech_head": "string",
            "dept_head": "string"
        },
        "financials": {
            "currency": "string",
            "subtotal": "number",
            "tax_amount": "number",
            "total_amount": "number",
            "vehicle_tonnage": "number or null",
            "gate_net_weight": "number or null",
            "store_weight": "number or null"
        },
        "line_items": [
            {
                "s_no": "number",
                "po_no": "string",
                "description": "string",
                "sub_group": "string",
                "unit": "string",
                "received_qty": "number",
                "rejected_qty": "number",
                "accepted_qty": "number",
                "accepted_weight": "number",
                "rate": "number",
                "gst_percent": "number",
                "amount": "number"
            }
        ],
        "payment_info": {
            "bank_details": "string or null",
            "terms": "string or null"
        }
    }
    """

    async def process_invoice(self, buffer: bytes, file_name: str, file_type: str) -> Dict[str, Any]:
        text = await extract_service.extract_doc(buffer, file_name, file_type)
        user_prompt = f"Extract all fields from this invoice/GRN text into the provided JSON schema. Text:\n\n{text[:25000]}\n\nSchema:\n{self.INVOICE_SCHEMA}"
        
        raw_response = await llm_service.unified_chat_completion(self.INVOICE_SYSTEM_PROMPT, user_prompt)
        
        try:
            # Robust JSON cleaning
            clean_json = raw_response.strip()
            
            # Remove Markdown code blocks if present
            import re
            json_match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if json_match:
                clean_json = json_match.group(0)
            
            # Remove potential trailing commas before closing braces/brackets
            clean_json = re.sub(r',\s*([\]\}])', r'\1', clean_json)
            
            data = json.loads(clean_json)
            return {"success": True, "data": data}
        except Exception as e:
            print(f"Invoice Parse Error: {e}")
            print(f"Raw Response: {raw_response[:500]}...")
            return {"success": False, "error": f"Failed to parse intelligence structure: {str(e)}", "raw": raw_response}

invoice_service = InvoiceService()
