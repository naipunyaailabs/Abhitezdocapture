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
        # Check if user can process
        can_process, sub, message = await subscription_service.can_process(current_user.userId)
        if not can_process:
            raise HTTPException(
                status_code=403,
                detail=f"Processing limit reached. {message}. Please upgrade your plan."
            )
        
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
            "confidence": None,
            "document_id": file_name
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

@router.post("/export")
async def export_extraction(
    data: dict,
    current_user: UserResponse = Depends(get_current_user)
):
    print(f"[DEBUG] Export endpoint hit by user {current_user.userId}")
    try:
        from app.utils.excel_exporter import excel_exporter
        from fastapi.responses import Response
        
        # Extract metadata if available
        document_id = data.get("document_id", "EXTRACTED_DOC")
        extracted_data = data.get("extracted", data)
        
        xlsx_buffer = excel_exporter.export_to_template(extracted_data, document_id)
        
        filename = f"GoodsReceipt_{int(time.time())}.xlsx"
        
        return Response(
            content=xlsx_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    except Exception as e:
        print(f"Export Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate Excel: {str(e)}")
