from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from app.services.rfp_service import rfp_service
from app.services.history_service import history_service
from app.services.subscription_service import subscription_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
from fastapi.responses import Response
import time
import json

router = APIRouter()

class RfpSection(BaseModel):
    title: str
    content: str

class CreateRfpRequest(BaseModel):
    title: str
    organization: str
    deadline: str
    sections: Optional[List[RfpSection]] = None

@router.post("/create")
async def create_rfp(request: CreateRfpRequest, current_user: UserResponse = Depends(get_current_user)):
    start_time = time.time()
    try:
        if request.sections and len(request.sections) > 0:
            sections_list = [s.model_dump() for s in request.sections]
            rfp_content = await rfp_service.create_rfp(
                request.title, 
                request.organization, 
                request.deadline, 
                sections_list
            )
        else:
            rfp_content = await rfp_service.create_standard_rfp(
                request.title, 
                request.organization, 
                request.deadline
            )
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Record history
        await history_service.create_record({
            "userId": current_user.userId,
            "serviceId": "rfp-creator",
            "serviceName": "RFP Generation",
            "fileName": f"{request.title}_RFP",
            "fileSize": 0,
            "format": "json",
            "status": "success",
            "result": json.dumps(rfp_content),
            "processingTime": processing_time
        })
        
        # Increment usage
        await subscription_service.increment_usage(current_user.userId)
        
        return {
            "success": True,
            "data": {
                "result": rfp_content,
                "message": "RFP content generated successfully"
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/download")
async def download_rfp(request: CreateRfpRequest, current_user: UserResponse = Depends(get_current_user)):
    try:
        if request.sections and len(request.sections) > 0:
            sections_list = [s.model_dump() for s in request.sections]
            rfp_content = await rfp_service.create_rfp(
                request.title, 
                request.organization, 
                request.deadline, 
                sections_list
            )
        else:
            rfp_content = await rfp_service.create_standard_rfp(
                request.title, 
                request.organization, 
                request.deadline
            )
            
        docx_bytes = rfp_service.create_rfp_word_document(rfp_content)
        
        filename = f"{request.title.replace(' ', '_')}_RFP.docx"
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
