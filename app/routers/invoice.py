from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.invoice_service import invoice_service
from app.services.history_service import history_service
from app.services.subscription_service import subscription_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
import time

router = APIRouter()

@router.post("/extract")
async def extract_invoice(
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
        
        result = await invoice_service.process_invoice(buffer, document.filename, document.content_type)
        
        if not result["success"]:
            raise HTTPException(status_code=502, detail=result.get("error", "AI Extraction failed"))
            
        processing_time = int((time.time() - start_time) * 1000)
        
        # Record history
        await history_service.create_record({
            "userId": current_user.userId,
            "serviceId": "invoice-agent",
            "serviceName": "Invoice Intelligence",
            "fileName": document.filename,
            "fileSize": len(buffer),
            "format": "json",
            "status": "success",
            "result": result["data"],
            "processingTime": processing_time
        })
        
        # Increment usage
        await subscription_service.increment_usage(current_user.userId)
        
        return {
            "success": True,
            "data": {
                "result": result["data"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[InvoiceRouter] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
