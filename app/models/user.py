from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Any, Dict
from datetime import datetime

class UserBase(BaseModel):
    name: str
    email: EmailStr
    designation: Optional[str] = None
    companyName: Optional[str] = None
    useCase: Optional[str] = None
    subscribedToNewsletter: bool = False

class UserCreate(UserBase):
    password: str
    agreedToTerms: bool

class UserUpdate(BaseModel):
    name: Optional[str] = None
    designation: Optional[str] = None
    companyName: Optional[str] = None
    useCase: Optional[str] = None
    subscribedToNewsletter: Optional[bool] = None
    emailVerified: Optional[bool] = None
    emailVerificationToken: Optional[str] = None
    emailVerificationTokenExpiry: Optional[datetime] = None
    passwordResetToken: Optional[str] = None
    passwordResetTokenExpiry: Optional[datetime] = None
    lastLoginAt: Optional[datetime] = None
    preferences: Optional[Any] = None
    password: Optional[str] = None

class UserInDB(UserBase):
    userId: str
    role: str = "user"
    password: str # Hashed
    emailVerified: bool = False
    emailVerificationToken: Optional[str] = None
    emailVerificationTokenExpiry: Optional[datetime] = None
    passwordResetToken: Optional[str] = None
    passwordResetTokenExpiry: Optional[datetime] = None
    createdAt: datetime = datetime.now()
    lastLoginAt: Optional[datetime] = None
    agreedToTermsAt: datetime = datetime.now()
    preferences: Optional[Any] = {}

class UserResponse(UserBase):
    userId: str
    role: str
    emailVerified: bool
    createdAt: datetime
    lastLoginAt: Optional[datetime]
    preferences: Optional[Any]
    agreedToTermsAt: datetime
    
    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterResponse(BaseModel):
    token: str
    user: UserResponse
    message: str

class LoginResponse(BaseModel):
    token: str
    user: UserResponse

class VerifyEmailRequest(BaseModel):
    token: str
