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


class StatusUpdate(BaseModel):
    status: str  # "active" | "blocked"


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None


class AddCredits(BaseModel):
    amount: int  # documents to add to the monthly limit


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


@router.put("/users/{user_id}/status")
async def update_status(user_id: str, body: StatusUpdate,
                        _: UserResponse = Depends(require_admin)):
    try:
        ok = await admin_service.set_status(user_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": f"User {body.status}"}


@router.put("/users/{user_id}/profile")
async def update_user_profile(user_id: str, body: ProfileUpdate,
                              _: UserResponse = Depends(require_admin)):
    try:
        ok = await admin_service.update_profile(
            user_id, body.name, str(body.email) if body.email else None
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not ok:
        raise HTTPException(status_code=400, detail="Nothing to update or user not found")
    return {"message": "Profile updated"}


@router.post("/users/{user_id}/add-credits")
async def add_credits(user_id: str, body: AddCredits,
                      _: UserResponse = Depends(require_admin)):
    ok = await admin_service.add_credits(user_id, body.amount)
    if not ok:
        raise HTTPException(status_code=404, detail="User subscription not found")
    return {"message": f"Added {body.amount} document credits"}


@router.post("/users/{user_id}/resend-invite")
async def resend_invite(user_id: str, background_tasks: BackgroundTasks,
                        _: UserResponse = Depends(require_admin)):
    info = await admin_service.regenerate_invite(user_id)
    if not info:
        raise HTTPException(status_code=404, detail="User not found")
    background_tasks.add_task(
        email_service.send_invite_email,
        info["email"], info["name"], info["token"], info["monthlyLimit"],
    )
    return {"message": "Invitation email re-sent"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, _: UserResponse = Depends(require_admin)):
    try:
        ok = await admin_service.delete_user(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted"}
