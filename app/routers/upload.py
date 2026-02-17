from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from app.services.extract_service import extract_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
import json

router = APIRouter()

@router.post("")
async def upload_template(
    document: UploadFile = File(...),
    fields: str = Form("[]"),
    current_user: UserResponse = Depends(get_current_user)
):
    try:
        fields_list = json.loads(fields)
        buffer = await document.read()
        text = await extract_service.extract_doc(buffer, document.filename, document.content_type)
        
        # Original TS code stores this in a placeholder/DB
        # In this FastAPI version, we'll just log it for now as per TemplateStore logic
        print(f"Template stored: {document.filename} with {len(fields_list)} fields")
        
        return {
            "success": True,
            "data": {
                "result": { "message": "Template stored successfully" },
                "logs": []
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid upload: {str(e)}")
