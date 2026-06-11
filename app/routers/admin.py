"""Admin API — all endpoints require an admin account (allowlist or role=admin)."""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import Optional
from pydantic import BaseModel, EmailStr

from app.utils.auth import require_admin
from app.models.user import UserResponse
from app.services.admin_service import admin_service
from app.services.email_service import email_service

router = APIRouter()


class ClientCreate(BaseModel):
    email: EmailStr
    name: str
    monthlyLimit: int = 100


class CreditsUpdate(BaseModel):
    documentsLimit: Optional[int] = None
    documentsUsed: Optional[int] = None


class TokenLimitUpdate(BaseModel):
    monthlyTokenLimit: Optional[int] = None  # null = unlimited


class RoleUpdate(BaseModel):
    role: str


@router.get("/users")
async def list_users(_: UserResponse = Depends(require_admin)):
    metrics = await admin_service.list_user_metrics()
    totals = await admin_service.get_totals(metrics)
    return {"users": metrics, "totals": totals}


@router.post("/users", status_code=201)
async def create_client(body: ClientCreate, background_tasks: BackgroundTasks,
                        _: UserResponse = Depends(require_admin)):
    if body.monthlyLimit < 0:
        raise HTTPException(status_code=400, detail="monthlyLimit must be >= 0")
    try:
        result = await admin_service.create_client(
            email=str(body.email), name=body.name, monthly_limit=body.monthlyLimit,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create client: {e}")

    # Send the activation/invite email in the background.
    background_tasks.add_task(
        email_service.send_invite_email,
        str(body.email), body.name, result["inviteToken"], body.monthlyLimit,
    )
    return {"message": "Client created. An invitation email has been sent.",
            "userId": result["userId"]}


@router.put("/users/{user_id}/credits")
async def update_credits(user_id: str, body: CreditsUpdate,
                         _: UserResponse = Depends(require_admin)):
    ok = await admin_service.set_credits(
        user_id, body.documentsLimit, body.documentsUsed
    )
    if not ok:
        raise HTTPException(status_code=404, detail="User subscription not found")
    return {"message": "Credits updated"}


@router.put("/users/{user_id}/token-limit")
async def update_token_limit(user_id: str, body: TokenLimitUpdate,
                             _: UserResponse = Depends(require_admin)):
    await admin_service.set_token_limit(user_id, body.monthlyTokenLimit)
    return {"message": "Token limit updated"}


@router.put("/users/{user_id}/role")
async def update_role(user_id: str, body: RoleUpdate,
                      _: UserResponse = Depends(require_admin)):
    if body.role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="role must be 'user' or 'admin'")
    ok = await admin_service.set_role(user_id, body.role)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Role updated"}
