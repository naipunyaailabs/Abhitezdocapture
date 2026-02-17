from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.extract_service import extract_service
from app.services.history_service import history_service
from app.services.subscription_service import subscription_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
import time
import json

router = APIRouter()

@router.post("")
async def extract_document(
    document: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user)
):
    start_time = time.time()
    try:
        buffer = await document.read()
        file_name = document.filename
        file_type = document.content_type
        
        text, structured = await extract_service.extract_and_parse(buffer, file_name, file_type)
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Record history
        await history_service.create_record({
            "userId": current_user.userId,
            "serviceId": "groq-extraction",
            "serviceName": "Document Extraction",
            "fileName": file_name,
            "fileSize": len(buffer),
            "format": "json",
            "status": "success",
            "result": json.dumps(structured),
            "processingTime": processing_time
        })
        
        # Increment usage
        await subscription_service.increment_usage(current_user.userId)
        
        result = {
            "extracted": structured,
            "textLength": len(text),
            "usedTemplate": False,
            "templateId": None,
            "confidence": None
        }
        
        return {
            "success": True,
            "data": {
                "result": result,
                "logs": []
            }
        }
    except Exception as e:
        print(f"Extraction Route Error: {e}")
        raise HTTPException(status_code=500, detail=f"Document extraction failed: {str(e)}")
