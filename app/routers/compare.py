from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from app.services.extract_service import extract_service
from app.services.llm_service import llm_service
from app.services.history_service import history_service
from app.services.subscription_service import subscription_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
from typing import List
import time

router = APIRouter()

@router.post("")
async def compare_quotations(
    documents: List[UploadFile] = File(...),
    criteria: str = Form(""),
    current_user: UserResponse = Depends(get_current_user)
):
    start_time = time.time()
    if len(documents) < 2:
        raise HTTPException(status_code=400, detail="Please upload at least 2 quotations to compare.")
    
    try:
        quotation_texts = []
        total_size = 0
        for doc in documents:
            buffer = await doc.read()
            total_size += len(buffer)
            text = await extract_service.extract_doc(buffer, doc.filename, doc.content_type)
            vendor_name = doc.filename.split(".")[0]
            quotation_texts.append({"vendor": vendor_name, "content": text})
            
        # TOON format
        quotations_toon = f"quotations[{len(quotation_texts)}]{{vendor,content}}:\n"
        for q in quotation_texts:
            escaped = q["content"].replace("\n", " ").replace(",", ";")
            quotations_toon += f"{q['vendor']},{escaped}\n"
            
        system_prompt = """You are an expert Procurement & Vendor Analysis Agent.
Your task is to analyze multiple vendor quotations and provide a strategic, heavy-hitting comparison.
You must identify the best option based on the criteria.
Output Format: Professional Markdown. Use clear headings, bullet points, and tables."""

        user_prompt = f"""Compare the following vendor quotations.

Quotations (TOON Format):
{quotations_toon}

Specific Criteria: {criteria or 'Price, Quality, Delivery, and terms'}

Structure your response exactly as follows:

# 1. Executive Comparison
Briefly summarize the contenders and the primary trade-offs.

# 2. Detailed Feature Analysis
Compare line items, specifications, and scope coverage.

# 3. Commercial Evaluation
- **Total Cost Analysis**: Compare total pricing.
- **Payment Terms**: Analyze flexibility.
- **Hidden Costs**: Identify potential extra charges.

# 4. Comparative Matrix
Create a markdown table comparing key attributes side-by-side:
| Feature | Vendor A | Vendor B | ... |
|---------|----------|----------|-----|
| Price   | ...      | ...      | ... |
| Speed   | ...      | ...      | ... |

# 5. Risk & Compliance
Identify any red flags, exclusions, or validities.

# 6. Final Recommendation
**Winner**: [Vendor Name]
**Reasoning**: Why this is the best choice.
"""

        comparison = await llm_service.unified_chat_completion(system_prompt, user_prompt)
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Record history
        await history_service.create_record({
            "userId": current_user.userId,
            "serviceId": "quotation-compare",
            "serviceName": "Quotation Comparison",
            "fileName": ", ".join([d.filename for d in documents]),
            "fileSize": total_size,
            "format": "markdown",
            "status": "success",
            "result": comparison,
            "processingTime": processing_time
        })
        
        # Increment usage
        await subscription_service.increment_usage(current_user.userId)
        
        return {
            "success": True,
            "data": {
                "result": {
                    "comparison": comparison.strip(),
                    "vendorCount": len(quotation_texts),
                    "vendors": [q["vendor"] for q in quotation_texts]
                },
                "logs": []
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
