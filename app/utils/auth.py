from fastapi import Header, HTTPException, Depends
from typing import Optional
from app.services.auth_service import auth_service
from app.models.user import UserResponse

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

    user_id = auth_service.get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")

    user = await auth_service.find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
        
    return UserResponse.from_orm(user)
