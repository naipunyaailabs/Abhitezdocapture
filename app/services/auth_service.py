import base64
import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from app.database import get_database
from app.models.user import UserInDB, UserCreate, UserUpdate

# In-memory stores fallback
in_memory_users: Dict[str, dict] = {}

class AuthService:
    
    # --- Password Hashing (Should actully be bcrypt, but matching legacy btoa) ---
    def hash_password(self, password: str) -> str:
        # User provided implementation used btoa (Base64)
        return base64.b64encode(password.encode('utf-8')).decode('utf-8')

    # --- Session Management ---
    # --- Session Management ---
    async def create_session(self, user_id: str) -> str:
        db = await get_database()
        token = self.generate_token()
        expires_at = datetime.now() + timedelta(days=7) # 1 week sessions
        
        session_doc = {
            "token": token,
            "userId": user_id,
            "createdAt": datetime.now(),
            "expiresAt": expires_at
        }
        
        try:
            print(f"[AuthService] Creating session for user: {user_id}")
            if db is not None:
                await db.sessions.insert_one(session_doc)
                print(f"[AuthService] Session saved to DB: {token[:10]}...")
            else:
                print(f"[AuthService] ERROR: Database connection is None during create_session")
            return token
        except Exception as e:
            print(f"[AuthService] Error creating session: {e}")
            return token # Return token anyway as fallback

    async def get_user_id_from_token(self, token: str) -> Optional[str]:
        db = await get_database()
        print(f"[AuthService] Checking token: {token[:10]}...")
        try:
            if db is not None:
                now = datetime.now()
                session = await db.sessions.find_one({
                    "token": token,
                    "expiresAt": {"$gt": now}
                })
                if session:
                    print(f"[AuthService] Session found for user: {session.get('userId')}")
                    return session.get("userId")
                else:
                    # Check if session exists but expired
                    expired_session = await db.sessions.find_one({"token": token})
                    if expired_session:
                        print(f"[AuthService] Session exists but expired at: {expired_session.get('expiresAt')}")
                    else:
                        print(f"[AuthService] No session found for token")
            else:
                print(f"[AuthService] Database connection is None")
            return None
        except Exception as e:
            print(f"Error getting user from token: {e}")
            return None

    async def invalidate_session(self, token: str):
        db = await get_database()
        try:
            if db is not None:
                await db.sessions.delete_one({"token": token})
        except Exception as e:
            print(f"Error invalidating session: {e}")

    def generate_token(self) -> str:
        return str(uuid.uuid4())

    # --- User Management ---
    
    async def create_user(self, user_create: UserCreate) -> Optional[UserInDB]:
        db = await get_database()
        
        user_id = str(uuid.uuid4())
        hashed_password = self.hash_password(user_create.password)
        verification_token = self.generate_token()
        verification_expiry = datetime.now() + timedelta(hours=24)
        
        user_in_db = UserInDB(
            **user_create.model_dump(exclude={'password', 'agreedToTerms'}),
            userId=user_id,
            password=hashed_password,
            emailVerificationToken=verification_token,
            emailVerificationTokenExpiry=verification_expiry,
            agreedToTermsAt=datetime.now()
        )
        
        user_dict = user_in_db.model_dump()
        
        try:
            if db is not None:
                await db.users.insert_one(user_dict)
            else:
                in_memory_users[user_id] = user_dict
            return user_in_db
        except Exception as e:
            print(f"Error creating user: {e}")
            return None

    async def find_user_by_email(self, email: str) -> Optional[UserInDB]:
        db = await get_database()
        try:
            if db is not None:
                user_doc = await db.users.find_one({"email": email})
                if user_doc:
                    return UserInDB(**user_doc)
            else:
                # Fallback
                for u in in_memory_users.values():
                    if u['email'] == email:
                        return UserInDB(**u)
        except Exception as e:
            print(f"Error finding user by email: {e}")
        return None

    async def find_user_by_id(self, user_id: str) -> Optional[UserInDB]:
        db = await get_database()
        try:
            if db is not None:
                user_doc = await db.users.find_one({"userId": user_id})
                if user_doc:
                    return UserInDB(**user_doc)
            else:
                u = in_memory_users.get(user_id)
                if u:
                    return UserInDB(**u)
        except Exception as e:
            print(f"Error finding user by id: {e}")
        return None

    async def find_user_by_verification_token(self, token: str) -> Optional[UserInDB]:
        db = await get_database()
        try:
            if db is not None:
                # Logic: token matches AND expiry > now
                user_doc = await db.users.find_one({
                    "emailVerificationToken": token,
                    "emailVerificationTokenExpiry": {"$gt": datetime.now()}
                })
                if user_doc:
                    return UserInDB(**user_doc)
            else:
                for u in in_memory_users.values():
                    if (u.get('emailVerificationToken') == token and 
                        u.get('emailVerificationTokenExpiry') and 
                        u['emailVerificationTokenExpiry'] > datetime.now()):
                        return UserInDB(**u)
        except Exception as e:
            print(f"Error finding user by verification token: {e}")
        return None

    async def update_user(self, user_id: str, updates: Dict[str, Any]) -> Optional[UserInDB]:
        db = await get_database()
        try:
            if db is not None:
                result = await db.users.find_one_and_update(
                    {"userId": user_id},
                    {"$set": updates},
                    return_document=True
                )
                if result:
                    return UserInDB(**result)
            else:
                u = in_memory_users.get(user_id)
                if u:
                    u.update(updates)
                    in_memory_users[user_id] = u
                    return UserInDB(**u)
        except Exception as e:
            print(f"Error updating user: {e}")
        return None

auth_service = AuthService()
