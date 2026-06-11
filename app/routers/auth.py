from fastapi import APIRouter, Header, Depends, HTTPException, BackgroundTasks, Response
from datetime import datetime, timedelta
from app.models.user import LoginRequest, LoginResponse, VerifyEmailRequest, UserResponse, UserUpdate
from app.services.auth_service import auth_service
from app.services.email_service import email_service
from app.utils.auth import get_current_user
from app.database import get_database
from typing import Optional

router = APIRouter()

@router.post("/login", response_model=LoginResponse)
async def login(login_req: LoginRequest, response: Response):
    user = await auth_service.find_user_by_email(login_req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    hashed_password = auth_service.hash_password(login_req.password)
    # Note: user.password is hashed
    if user.password != hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.emailVerified:
        raise HTTPException(status_code=403, detail="Please verify your email address before logging in")

    if getattr(user, "status", "active") == "blocked":
        raise HTTPException(status_code=403, detail="Your account has been suspended. Please contact your administrator.")

    # Update last login
    await auth_service.update_user(user.userId, {"lastLoginAt": datetime.now()})

    token = await auth_service.create_session(user.userId)
    
    # Set cookie for server-rendered pages
    response.set_cookie(
        key="token", 
        value=token, 
        max_age=60 * 60 * 24 * 7, # 1 week
        path="/",
        samesite="lax",
        httponly=False
    )
    
    return LoginResponse(
        token=token,
        user=UserResponse.from_orm(user)
    )

@router.post("/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    token = authorization.split(" ")[1]
    await auth_service.invalidate_session(token)
    return {"message": "Logged out successfully"}

@router.get("/profile", response_model=UserResponse)
async def profile(current_user: UserResponse = Depends(get_current_user)):
    return current_user

@router.get("/verify")
async def verify_email(token: str):
    user = await auth_service.find_user_by_verification_token(token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    
    updated_user = await auth_service.update_user(user.userId, {
        "emailVerified": True,
        "emailVerificationToken": None,
        "emailVerificationTokenExpiry": None
    })
    
    if not updated_user:
        raise HTTPException(status_code=500, detail="Failed to verify email")
        
    return {"message": "Email verified successfully. You can now login to your account."}

@router.post("/resend-verification")
async def resend_verification(email: str, background_tasks: BackgroundTasks):
    user = await auth_service.find_user_by_email(email)
    if not user:
        return {"message": "If an account exists with this email, a verification email has been sent."}
    
    if user.emailVerified:
        raise HTTPException(status_code=400, detail="Email is already verified")
        
    new_token = auth_service.generate_token()
    expiry = datetime.now() + timedelta(hours=24)
    
    await auth_service.update_user(user.userId, {
        "emailVerificationToken": new_token,
        "emailVerificationTokenExpiry": expiry
    })
    
    background_tasks.add_task(
        email_service.send_verification_email, 
        user.email, 
        new_token
    )
    
    return {"message": "Verification email sent successfully."}

@router.put("/profile", response_model=UserResponse)
async def update_profile(updates: dict, current_user: UserResponse = Depends(get_current_user)):
    allowed_fields = {"name", "designation", "companyName", "useCase", "subscribedToNewsletter"}
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    
    updated_user = await auth_service.update_user(current_user.userId, filtered)
    if not updated_user:
        raise HTTPException(status_code=500, detail="Failed to update profile")
    return UserResponse.from_orm(updated_user)

@router.post("/set-password")
async def set_password(data: dict):
    """Activate an invited client account: validate the invite/reset token and
    set the chosen password. No auth required — the token is the credential."""
    token = data.get("token")
    new_pw = data.get("newPassword")
    if not token or not new_pw:
        raise HTTPException(status_code=400, detail="Token and new password are required")
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    db = await get_database()
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")

    user_doc = await db.users.find_one({
        "passwordResetToken": token,
        "passwordResetTokenExpiry": {"$gt": datetime.now()},
    })
    if not user_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired activation link")

    await db.users.update_one(
        {"_id": user_doc["_id"]},
        {"$set": {
            "password": auth_service.hash_password(new_pw),
            "emailVerified": True,
            "passwordResetToken": None,
            "passwordResetTokenExpiry": None,
        }},
    )
    return {"message": "Password set successfully. You can now sign in."}


@router.post("/change-password")
async def change_password(data: dict, current_user: UserResponse = Depends(get_current_user)):
    current_pw = data.get("currentPassword")
    new_pw = data.get("newPassword")
    
    if not current_pw or not new_pw:
        raise HTTPException(status_code=400, detail="Both current and new passwords are required")
    
    user = await auth_service.find_user_by_id(current_user.userId)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.password != auth_service.hash_password(current_pw):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    hashed_new = auth_service.hash_password(new_pw)
    await auth_service.update_user(current_user.userId, {"password": hashed_new})
    
    return {"message": "Password updated successfully"}

# Additional routes for password reset follow similar pattern...
