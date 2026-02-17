from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime, timedelta

class SubscriptionBase(BaseModel):
    userId: str
    planId: str
    planName: str
    documentsLimit: int = 10
    documentsUsed: int = 0
    status: str = "active"
    currentPeriodStart: datetime = Field(default_factory=datetime.now)
    currentPeriodEnd: datetime = Field(default_factory=lambda: datetime.now() + timedelta(days=30))

class SubscriptionInDB(SubscriptionBase):
    id: Optional[str] = Field(None, alias="_id")
    paymentCustomerId: Optional[str] = None
    paymentSubscriptionId: Optional[str] = None

class ProcessingHistoryBase(BaseModel):
    userId: str
    serviceId: str
    serviceName: str
    fileName: str
    fileSize: int = 0
    format: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    logs: Optional[List[str]] = []
    processedAt: datetime = Field(default_factory=datetime.now)
    processingTime: Optional[float] = 0

class ProcessingHistoryInDB(ProcessingHistoryBase):
    id: Optional[str] = Field(None, alias="_id")
