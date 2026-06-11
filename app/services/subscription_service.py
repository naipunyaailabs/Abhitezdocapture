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

    async def can_process(self, user_id: str) -> Tuple[bool, Optional[dict], str]:
        sub = await self.get_user_subscription(user_id)
        if not sub:
            return False, None, "No active subscription"

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
