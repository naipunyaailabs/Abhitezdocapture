from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.extract_service import extract_service
from app.services.rfp_agent_service import rfp_agent_service
from app.services.history_service import history_service
from app.services.subscription_service import subscription_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
import time

router = APIRouter()

@router.post("")
async def summarize_rfp_endpoint(
    document: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user)
):
    start_time = time.time()
    try:
        # Check if user can process
        can_process, sub, message = await subscription_service.can_process(current_user.userId)
        if not can_process:
            raise HTTPException(
                status_code=403,
                detail=f"Processing limit reached. {message}. Please upgrade your plan."
            )
        
        buffer = await document.read()
        text = await extract_service.extract_doc(buffer, document.filename, document.content_type)
        
        # TOON format
        clean_text = text.replace('\n', ' ').replace(',', ';')
        document_toon = f"rfp{{filename,content}}:\n{document.filename},{clean_text}"
        
        result = await rfp_agent_service.summarize_rfp(document_toon)
        
        if not result["success"]:
            raise HTTPException(status_code=502, detail=result["error"])
            
        processing_time = int((time.time() - start_time) * 1000)
        
        # Record history
        await history_service.create_record({
            "userId": current_user.userId,
            "serviceId": "rfp-summarizer",
            "serviceName": "RFP Summarization",
            "fileName": document.filename,
            "fileSize": len(buffer),
            "format": "html",
            "status": "success",
            "result": result["html"],
            "processingTime": processing_time
        })
        
        # Increment usage
        await subscription_service.increment_usage(current_user.userId)
        
        return {
            "success": True,
            "data": {
                "result": {
                    "html": result["html"]
                },
                "logs": []
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
