from fastapi import APIRouter, HTTPException, Depends
from app.services.subscription_service import subscription_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse

router = APIRouter()

@router.get("/current")
async def get_current_subscription(current_user: UserResponse = Depends(get_current_user)):
    sub = await subscription_service.get_user_subscription(current_user.userId)
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription found")
    
    # Clean up _id for JSON response
    if "_id" in sub:
        sub["id"] = str(sub["_id"])
        del sub["_id"]
        
    return {"success": True, "data": sub}

@router.get("/usage")
async def get_usage_status(current_user: UserResponse = Depends(get_current_user)):
    can_process, sub, message = await subscription_service.can_process(current_user.userId)
    if not sub:
        raise HTTPException(status_code=404, detail=message)
        
    return {
        "success": True,
        "data": {
            "canProcess": can_process,
            "documentsUsed": sub["documentsUsed"],
            "documentsLimit": sub["documentsLimit"],
            "planId": sub["planId"],
            "planName": sub["planName"],
            "message": message
        }
    }

@router.post("/increment")
async def increment_usage(current_user: UserResponse = Depends(get_current_user)):
    sub = await subscription_service.increment_usage(current_user.userId)
    if not sub:
        raise HTTPException(status_code=500, detail="Failed to increment usage")
        
    return {
        "success": True,
        "data": {
            "documentsUsed": sub["documentsUsed"],
            "documentsLimit": sub["documentsLimit"]
        }
    }
