from fastapi import APIRouter, HTTPException, Depends
from app.services.history_service import history_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
from typing import Optional

router = APIRouter()

@router.get("")
async def get_history(
    limit: int = 50, 
    offset: int = 0, 
    current_user: UserResponse = Depends(get_current_user)
):
    history = await history_service.get_user_history(current_user.userId, limit, offset)
    return {"success": True, "data": history}

@router.get("/analytics")
async def get_analytics(days: int = 30, current_user: UserResponse = Depends(get_current_user)):
    analytics = await history_service.get_analytics(current_user.userId, days)
    return {"success": True, "data": analytics}

@router.post("")
async def create_history_record(data: dict, current_user: UserResponse = Depends(get_current_user)):
    data["userId"] = current_user.userId
    record = await history_service.create_record(data)
    if not record:
        raise HTTPException(status_code=500, detail="Failed to create history record")
    return {"success": True, "data": record}
