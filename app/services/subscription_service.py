from typing import Optional, Tuple
from app.database import get_database
from app.models.schemas import SubscriptionInDB
from datetime import datetime, timedelta

class SubscriptionService:
    async def get_user_subscription(self, user_id: str) -> Optional[dict]:
        db = await get_database()
        if db is None: return None
        return await db.subscriptions.find_one({"userId": user_id})

    async def create_trial(self, user_id: str) -> Optional[dict]:
        db = await get_database()
        if db is None: return None
        
        sub = {
            "userId": user_id,
            "planId": "trial",
            "planName": "Free Trial",
            "documentsLimit": 5,
            "documentsUsed": 0,
            "status": "active",
            "currentPeriodStart": datetime.now(),
            "currentPeriodEnd": datetime.now() + timedelta(days=30)
        }
        await db.subscriptions.insert_one(sub)
        return sub

    async def _maybe_reset_month(self, sub: dict) -> dict:
        """Reset documentsUsed to 0 when the calendar month has rolled over since
        currentPeriodStart. Credits renew on the 1st of each month."""
        start = sub.get("currentPeriodStart")
        now = datetime.now()
        # Treat as needing reset if we've moved into a later (year, month).
        if isinstance(start, datetime):
            same_month = (start.year == now.year and start.month == now.month)
        else:
            same_month = False
        if same_month:
            return sub
        db = await get_database()
        new_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if db is not None:
            updated = await db.subscriptions.find_one_and_update(
                {"userId": sub["userId"]},
                {"$set": {"documentsUsed": 0, "currentPeriodStart": new_start,
                          "updatedAt": now}},
                return_document=True,
            )
            if updated:
                return updated
        sub["documentsUsed"] = 0
        sub["currentPeriodStart"] = new_start
        return sub

    async def can_process(self, user_id: str) -> Tuple[bool, Optional[dict], str]:
        # Reject blocked accounts even if they hold a valid session.
        db = await get_database()
        if db is not None:
            u = await db.users.find_one({"userId": user_id}, {"status": 1})
            if u and u.get("status") == "blocked":
                return False, None, "Account suspended"

        sub = await self.get_user_subscription(user_id)
        if not sub:
            return False, None, "No active subscription"

        # Renew monthly document credits on the 1st.
        sub = await self._maybe_reset_month(sub)

        if int(sub.get("documentsUsed", 0)) >= int(sub.get("documentsLimit", 0)):
            return False, sub, "Document limit reached"

        # Monthly token cap (admin-configurable, resets on the 1st).
        try:
            from app.services.usage_service import usage_service
            if not await usage_service.within_limit(user_id):
                return False, sub, "Monthly token limit reached"
        except Exception as e:
            # Never block processing because the usage check itself errored.
            print(f"[SubscriptionService] token-limit check skipped: {e}")

        return True, sub, "OK"

    async def increment_usage(self, user_id: str) -> Optional[dict]:
        db = await get_database()
        if db is None: return None
        
        return await db.subscriptions.find_one_and_update(
            {"userId": user_id},
            {"$inc": {"documentsUsed": 1}},
            return_document=True
        )

subscription_service = SubscriptionService()
