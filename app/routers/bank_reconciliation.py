from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.bank_reconciliation_service import bank_reconciliation_service
from app.services.history_service import history_service
from app.services.subscription_service import subscription_service
from app.utils.auth import get_current_user
from app.models.user import UserResponse
import time
import json

router = APIRouter()

@router.post("")
async def reconcile_bank_account(
    bank_statement: UploadFile = File(...),
    ledger_file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user)
):
    start_time = time.time()
    try:
        # Check if user can process
        can_process, sub, message = await subscription_service.can_process(current_user.userId)
        if not can_process:
            raise HTTPException(
                status_code=403,
                detail=f"Processing limit reached. {message}. Please upgrade your plan."
            )
        
        # Read bank statement
        bank_buffer = await bank_statement.read()
        bank_name = bank_statement.filename
        bank_type = bank_statement.content_type
        
        # Read ledger file
        ledger_buffer = await ledger_file.read()
        ledger_name = ledger_file.filename
        ledger_type = ledger_file.content_type
        
        # Extract and reconcile
        bank_transactions = await bank_reconciliation_service.extract_bank_transactions(
            bank_buffer, bank_name, bank_type
        )
        ledger_entries = await bank_reconciliation_service.extract_ledger_entries(
            ledger_buffer, ledger_name, ledger_type
        )
        
        result = await bank_reconciliation_service.reconcile(bank_transactions, ledger_entries)
        
        processing_time = int((time.time() - start_time) * 1000)
        
        # Record history
        await history_service.create_record({
            "userId": current_user.userId,
            "serviceId": "bank-reconciliation",
            "serviceName": "Bank Reconciliation",
            "fileName": f"{bank_name} vs {ledger_name}",
            "fileSize": len(bank_buffer) + len(ledger_buffer),
            "format": "json",
            "status": "success",
            "result": result.model_dump_json(),
            "processingTime": processing_time
        })
        
        # Increment usage
        await subscription_service.increment_usage(current_user.userId)
        
        return {
            "success": True,
            "data": {
                "result": result,
                "logs": []
            }
        }
    except Exception as e:
        print(f"Reconciliation Route Error: {e}")
        raise HTTPException(status_code=500, detail=f"Bank reconciliation failed: {str(e)}")
