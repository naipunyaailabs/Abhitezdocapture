"""
Usage / token accounting service.

Tracks LLM token consumption per user per calendar month, so the Admin Access
page can monitor usage and enforce a monthly cap that resets on the 1st.

Two collections are used:
  - token_usage      : one document per LLM call (the raw ledger / audit trail)
  - monthly_usage    : rolled-up counters keyed by (userId, period) where period
                       is "YYYY-MM". This is what we read for fast dashboards and
                       cap enforcement. It resets implicitly: a new month is a new
                       period key, so counts start at 0 on the 1st automatically.
"""

import contextvars
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from app.database import get_database

# Per-request attribution. Routers set this once they know the authenticated
# user; llm_service reads it so the 27 existing call sites need no changes.
_current_user_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "usage_current_user_id", default=None
)
_current_service_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "usage_current_service_id", default=None
)


def set_usage_context(user_id: Optional[str], service_id: Optional[str] = None):
    """Call at the start of a request handler to attribute LLM token usage."""
    _current_user_id.set(user_id)
    _current_service_id.set(service_id)


def get_usage_context():
    return _current_user_id.get(), _current_service_id.get()


def current_period(now: Optional[datetime] = None) -> str:
    """Return the calendar-month period key, e.g. '2026-06'. Month boundary is
    the 1st (00:00). Using UTC keeps the boundary consistent across machines."""
    now = now or datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


class UsageService:
    async def record(
        self,
        user_id: str,
        service_id: Optional[str],
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        model: Optional[str] = None,
    ):
        """Append a raw ledger entry and increment the monthly rollup."""
        db = await get_database()
        if db is None or not user_id:
            return
        if not total_tokens:
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        period = current_period()
        now = datetime.now()

        try:
            await db.token_usage.insert_one({
                "userId": user_id,
                "serviceId": service_id,
                "model": model,
                "promptTokens": prompt_tokens,
                "completionTokens": completion_tokens,
                "totalTokens": total_tokens,
                "period": period,
                "createdAt": now,
            })
            await db.monthly_usage.update_one(
                {"userId": user_id, "period": period},
                {
                    "$inc": {
                        "totalTokens": total_tokens,
                        "promptTokens": prompt_tokens,
                        "completionTokens": completion_tokens,
                        "calls": 1,
                    },
                    "$set": {"updatedAt": now},
                    "$setOnInsert": {
                        "userId": user_id,
                        "period": period,
                        "createdAt": now,
                    },
                },
                upsert=True,
            )
        except Exception as e:
            print(f"[UsageService] record failed: {e}")

    async def get_month_usage(self, user_id: str, period: Optional[str] = None) -> Dict[str, Any]:
        """Token counters for a user in the given (default current) month."""
        db = await get_database()
        period = period or current_period()
        empty = {"period": period, "totalTokens": 0, "promptTokens": 0,
                 "completionTokens": 0, "calls": 0}
        if db is None:
            return empty
        doc = await db.monthly_usage.find_one({"userId": user_id, "period": period})
        if not doc:
            return empty
        doc.pop("_id", None)
        return {**empty, **doc}

    async def get_month_limit(self, user_id: str) -> Optional[int]:
        """Per-user monthly token cap, or None if unlimited."""
        db = await get_database()
        if db is None:
            return None
        doc = await db.usage_limits.find_one({"userId": user_id})
        return (doc or {}).get("monthlyTokenLimit")

    async def set_month_limit(self, user_id: str, monthly_token_limit: Optional[int]):
        db = await get_database()
        if db is None:
            return
        await db.usage_limits.update_one(
            {"userId": user_id},
            {"$set": {"monthlyTokenLimit": monthly_token_limit,
                      "updatedAt": datetime.now()}},
            upsert=True,
        )

    async def within_limit(self, user_id: str) -> bool:
        """True if the user is still under their monthly token cap (or no cap)."""
        limit = await self.get_month_limit(user_id)
        if not limit:
            return True
        used = (await self.get_month_usage(user_id)).get("totalTokens", 0)
        return used < limit


usage_service = UsageService()
