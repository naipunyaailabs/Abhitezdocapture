import json
from typing import List, Dict, Any, Tuple
from app.services.llm_service import llm_service
from app.services.extract_service import extract_service
from app.models.schemas import BankTransaction, LedgerEntry, ReconciliationResult, ReconciliationMatch

class BankReconciliationService:
    async def extract_bank_transactions(self, buffer: bytes, file_name: str, file_type: str) -> List[BankTransaction]:
        text = await extract_service.extract_doc(buffer, file_name, file_type)
        
        system_prompt = """You are an Expert Forensic Data Extractor specializing in bank statements.
Extract ALL transactions from the provided bank statement text.
For each transaction, identify:
- date (YYYY-MM-DD)
- description (as it appears)
- amount (positive number)
- type (credit or debit)
- balance (optional)
- reference (optional check number or ID)

Output ONLY a JSON array of transaction objects."""

        user_prompt = f"Extract transactions from this bank statement text:\n\n{text[:20000]}"
        
        raw_response = await llm_service.unified_chat_completion(system_prompt, user_prompt)
        
        try:
            clean_json = raw_response.strip()
            if clean_json.startswith("```"):
                clean_json = clean_json.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            return [BankTransaction(**t) for t in data]
        except Exception as e:
            print(f"Bank transaction extraction error: {e}")
            return []

    async def extract_ledger_entries(self, buffer: bytes, file_name: str, file_type: str) -> List[LedgerEntry]:
        text = await extract_service.extract_doc(buffer, file_name, file_type)
        
        system_prompt = """You are an Expert Forensic Data Extractor specializing in accounting ledgers.
Extract ALL ledger entries from the provided text.
For each entry, identify:
- date (YYYY-MM-DD)
- description
- amount (positive number)
- type (credit or debit)
- reference (optional)

Output ONLY a JSON array of ledger entry objects."""

        user_prompt = f"Extract ledger entries from this text:\n\n{text[:20000]}"
        
        raw_response = await llm_service.unified_chat_completion(system_prompt, user_prompt)
        
        try:
            clean_json = raw_response.strip()
            if clean_json.startswith("```"):
                clean_json = clean_json.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            return [LedgerEntry(**t) for t in data]
        except Exception as e:
            print(f"Ledger entry extraction error: {e}")
            return []

    async def reconcile(self, bank_transactions: List[BankTransaction], ledger_entries: List[LedgerEntry]) -> ReconciliationResult:
        if not bank_transactions or not ledger_entries:
            return ReconciliationResult(
                matches=[],
                unmatched_bank=bank_transactions,
                unmatched_ledger=ledger_entries,
                summary={
                    "total_bank": len(bank_transactions),
                    "total_ledger": len(ledger_entries),
                    "matched_count": 0,
                    "discrepancy_count": len(bank_transactions) + len(ledger_entries)
                }
            )

        system_prompt = """You are an Expert Financial Auditor.
Your task is to reconcile bank transactions against ledger entries.
Match each bank transaction to exactly one ledger entry where possible.

Rules:
1. Same amount is a strong signal.
2. Similar dates (nearby days) is a signal.
3. Description matching (e.g., vendor names).

Output a JSON object with:
- matches: list of { "bank_idx": int, "ledger_idx": int, "score": float, "reason": str }
- unmatched_bank_indices: list of int
- unmatched_ledger_indices: list of int
"""

        bank_data = [t.model_dump() for t in bank_transactions]
        ledger_data = [e.model_dump() for e in ledger_entries]
        
        user_prompt = f"Bank Transactions:\n{json.dumps(bank_data)}\n\nLedger Entries:\n{json.dumps(ledger_data)}"
        
        raw_response = await llm_service.unified_chat_completion(system_prompt, user_prompt)
        
        try:
            clean_json = raw_response.strip()
            if clean_json.startswith("```"):
                clean_json = clean_json.replace("```json", "").replace("```", "").strip()
            recon_data = json.loads(clean_json)
            
            matches = []
            for m in recon_data.get("matches", []):
                matches.append(ReconciliationMatch(
                    bank_transaction=bank_transactions[m["bank_idx"]],
                    ledger_entry=ledger_entries[m["ledger_idx"]],
                    match_score=m["score"],
                    match_reason=m["reason"]
                ))
            
            unmatched_bank = [bank_transactions[i] for i in recon_data.get("unmatched_bank_indices", [])]
            unmatched_ledger = [ledger_entries[i] for i in recon_data.get("unmatched_ledger_indices", [])]
            
            summary = {
                "total_bank": len(bank_transactions),
                "total_ledger": len(ledger_entries),
                "matched_count": len(matches),
                "discrepancy_count": len(unmatched_bank) + len(unmatched_ledger)
            }
            
            return ReconciliationResult(
                matches=matches,
                unmatched_bank=unmatched_bank,
                unmatched_ledger=unmatched_ledger,
                summary=summary
            )
        except Exception as e:
            print(f"Reconciliation error: {e}")
            # Return naive result on failure
            return ReconciliationResult(
                matches=[],
                unmatched_bank=bank_transactions,
                unmatched_ledger=ledger_entries,
                summary={"error": str(e)}
            )

bank_reconciliation_service = BankReconciliationService()
