import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App Config
    APP_NAME: str = "Docapture API"
    API_V1_STR: str = "/api"
    PORT: int = 5000
    
    # MongoDB Config
    MONGODB_URI: str = "mongodb://localhost:27017/docapture"
    DB_NAME: str = "docapture"
    
    # Security
    API_KEY: str = os.getenv("API_KEY", "dev_key")
    SECRET_KEY: str = "your-secret-key" # SHOULD BE CHANGED IN PROD
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 # 24 hours
    
    # LLM Config
    AI_CLIENT: str = "groq"
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # Email Config
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASS: str = os.getenv("SMTP_PASS", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "Docapture <noreply@docapture.com>")
    SMTP_SECURE: bool = True
    
    # URLs
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "*")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

settings = Settings()
