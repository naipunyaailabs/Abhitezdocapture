from fastapi import Header, HTTPException, Depends
from typing import Optional
from app.services.auth_service import auth_service
from app.models.user import UserResponse
from app.config import settings


def user_is_admin(user: UserResponse) -> bool:
    """A user is an admin if flagged in DB OR present in the ADMIN_EMAILS allowlist."""
    return getattr(user, "role", "user") == "admin" or settings.is_admin_email(
        getattr(user, "email", None)
    )

async def get_current_user(authorization: Optional[str] = Header(None)) -> UserResponse:
    print(f"[Auth] Authorization Header: {authorization[:20]}..." if authorization else "[Auth] No Authorization Header")
    if not authorization or not authorization.startswith("Bearer "):
         raise HTTPException(status_code=401, detail="Unauthorized")

    token = authorization.split(" ")[1]
    print(f"[Auth] Extracted Token: {token[:10]}...")
    
    # Check if it is an API Key first (Dev mode)
    # The original code logic prioritized User Token if present, otherwise API Key.
    # Here we assume token is session token. If we want to support API Key we need to check both.
    
    # If token matches configured API KEY
    from app.config import settings
    if settings.API_KEY and token == settings.API_KEY:
        # Return a mock admin user or handle appropriately
        # For now, let's assume API Key access doesn't require a user object, 
        # but this dependency returns a User.
        # This might be tricky if downstream expects a user.
        # Let's create a dummy system user.
        return UserResponse(
            name="System Admin", 
            email="admin@system.com", 
            userId="admin", 
            role="admin", 
            emailVerified=True
        )

    print(f"[Auth] Calling get_user_id_from_token for: {token[:10]}...")
    user_id = await auth_service.get_user_id_from_token(token)
    print(f"[Auth] Result from auth_service: user_id={user_id}")
    if not user_id:
        print("[Auth] Session invalid or expired")
        raise HTTPException(status_code=401, detail="Invalid session")

    user = await auth_service.find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Attribute any LLM token usage during this request to this user.
    try:
        from app.services.usage_service import set_usage_context
        set_usage_context(user_id)
    except Exception:
        pass

    return UserResponse.from_orm(user)


async def require_admin(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
    """Dependency that allows only admin accounts (allowlist or role=admin)."""
    if not user_is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
