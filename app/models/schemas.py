from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
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

class BankTransaction(BaseModel):
    date: str
    description: str
    amount: float
    type: str  # credit or debit
    balance: Optional[float] = None
    reference: Optional[str] = None

class LedgerEntry(BaseModel):
    date: str
    description: str
    amount: float
    type: str  # credit or debit
    reference: Optional[str] = None

class ReconciliationMatch(BaseModel):
    bank_transaction: BankTransaction
    ledger_entry: LedgerEntry
    match_score: float
    match_reason: str

class ReconciliationResult(BaseModel):
    matches: List[ReconciliationMatch]
    unmatched_bank: List[BankTransaction]
    unmatched_ledger: List[LedgerEntry]
    summary: Dict[str, Any]
