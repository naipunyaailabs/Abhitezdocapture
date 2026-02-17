from fastapi import APIRouter, HTTPException, Depends
from app.services.service_service import service_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
from typing import List

router = APIRouter()

@router.get("")
async def list_services(current_user: UserResponse = Depends(get_current_user)):
    services = await service_service.find_all_services()
    return {"success": True, "data": services}

@router.get("/{service_id}")
async def get_service(service_id: str, current_user: UserResponse = Depends(get_current_user)):
    service = await service_service.find_service_by_id(service_id)
    if not service:
        service = await service_service.find_service_by_slug(service_id)
    
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
        
    return {"success": True, "data": service}
