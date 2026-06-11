"""
Admin service — aggregates per-user monitoring data for the Admin Access page.

For every user it combines:
  - account info (name, email, role, verified, last login)
  - subscription / credits (documentsUsed, documentsLimit)
  - files extracted (count of history docs) + per-service breakdown
  - this month's token usage and the configured monthly token cap

It also exposes admin setters for credits and the monthly token limit.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.database import get_database
from app.services.usage_service import usage_service, current_period


def _to_int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class AdminService:
    async def list_user_metrics(self) -> List[Dict[str, Any]]:
        db = await get_database()
        if db is None:
            return []

        # Pull everything once, then join in memory (user counts are small here).
        users = await db.users.find({}).to_list(length=2000)
        subs = await db.subscriptions.find({}).to_list(length=5000)
        sub_by_user = {s.get("userId"): s for s in subs}

        # Files extracted + per-service breakdown, grouped by user.
        history_agg = await db.history.aggregate([
            {"$group": {
                "_id": {"userId": "$userId", "serviceName": "$serviceName"},
                "count": {"$sum": 1},
            }},
        ]).to_list(length=100000)
        files_by_user: Dict[str, int] = {}
        services_by_user: Dict[str, Dict[str, int]] = {}
        for row in history_agg:
            uid = row["_id"].get("userId")
            sname = row["_id"].get("serviceName") or "Unknown"
            c = _to_int(row.get("count"))
            files_by_user[uid] = files_by_user.get(uid, 0) + c
            services_by_user.setdefault(uid, {})[sname] = c

        # This month's token usage, grouped by user.
        period = current_period()
        usage_docs = await db.monthly_usage.find({"period": period}).to_list(length=5000)
        usage_by_user = {u.get("userId"): u for u in usage_docs}

        # Per-user monthly token caps.
        limit_docs = await db.usage_limits.find({}).to_list(length=5000)
        limit_by_user = {l.get("userId"): l.get("monthlyTokenLimit") for l in limit_docs}

        result = []
        for u in users:
            uid = u.get("userId")
            sub = sub_by_user.get(uid, {})
            usage = usage_by_user.get(uid, {})
            services_map = services_by_user.get(uid, {})
            result.append({
                "userId": uid,
                "name": u.get("name"),
                "email": u.get("email"),
                "role": u.get("role", "user"),
                "emailVerified": bool(u.get("emailVerified")),
                "lastLoginAt": u.get("lastLoginAt"),
                "createdAt": u.get("createdAt"),
                # credits
                "documentsUsed": _to_int(sub.get("documentsUsed")),
                "documentsLimit": _to_int(sub.get("documentsLimit")),
                "planName": sub.get("planName") or "—",
                # activity
                "filesExtracted": files_by_user.get(uid, 0),
                "services": services_map,
                "servicesCount": len(services_map),
                # tokens (this calendar month)
                "tokensThisMonth": _to_int(usage.get("totalTokens")),
                "callsThisMonth": _to_int(usage.get("calls")),
                "monthlyTokenLimit": limit_by_user.get(uid),  # None = unlimited
            })
        # Sort: admins first, then by tokens used desc.
        result.sort(key=lambda r: (r["role"] != "admin", -r["tokensThisMonth"]))
        return result

    async def get_totals(self, metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "period": current_period(),
            "totalUsers": len(metrics),
            "totalFiles": sum(m["filesExtracted"] for m in metrics),
            "totalTokens": sum(m["tokensThisMonth"] for m in metrics),
            "totalCredits": sum(m["documentsUsed"] for m in metrics),
        }

    async def set_credits(self, user_id: str, documents_limit: Optional[int] = None,
                          documents_used: Optional[int] = None) -> bool:
        db = await get_database()
        if db is None:
            return False
        updates = {}
        if documents_limit is not None:
            updates["documentsLimit"] = int(documents_limit)
        if documents_used is not None:
            updates["documentsUsed"] = int(documents_used)
        if not updates:
            return False
        res = await db.subscriptions.update_one({"userId": user_id}, {"$set": updates})
        return res.matched_count > 0

    async def set_token_limit(self, user_id: str, monthly_token_limit: Optional[int]) -> bool:
        await usage_service.set_month_limit(user_id, monthly_token_limit)
        return True

    async def create_client(self, email: str, name: str,
                            monthly_limit: int) -> Dict[str, Any]:
        """Create a non-admin client account in an un-activated state and return
        the invite token. The client has no password until they set one via the
        emailed link. Raises ValueError if the email already exists."""
        db = await get_database()
        if db is None:
            raise RuntimeError("Database unavailable")

        email = email.strip()
        existing = await db.users.find_one(
            {"email": {"$regex": f"^{email}$", "$options": "i"}}
        )
        if existing:
            raise ValueError("A user with this email already exists")

        user_id = str(uuid.uuid4())
        invite_token = str(uuid.uuid4())
        invite_expiry = datetime.now() + timedelta(hours=48)
        now = datetime.now()

        user_doc = {
            "name": (name or email.split("@")[0]).strip(),
            "email": email,
            "userId": user_id,
            "role": "user",            # never admin
            "password": "",            # set later via invite link
            "emailVerified": False,    # activated when password is set
            "passwordResetToken": invite_token,
            "passwordResetTokenExpiry": invite_expiry,
            "createdAt": now,
            "agreedToTermsAt": now,
            "preferences": {},
            "subscribedToNewsletter": False,
        }
        await db.users.insert_one(user_doc)

        # Monthly document credits subscription. Period runs for the current
        # calendar month; can_process rolls it over on the 1st.
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        sub = {
            "userId": user_id,
            "planId": "managed",
            "planName": "Managed",
            "documentsLimit": int(monthly_limit),
            "documentsUsed": 0,
            "status": "active",
            "currentPeriodStart": period_start,
            "currentPeriodEnd": None,  # calendar-month based, recomputed on use
            "createdAt": now,
            "updatedAt": now,
        }
        await db.subscriptions.insert_one(sub)

        return {"userId": user_id, "inviteToken": invite_token,
                "inviteExpiry": invite_expiry}

    async def set_role(self, user_id: str, role: str) -> bool:
        db = await get_database()
        if db is None:
            return False
        res = await db.users.update_one({"userId": user_id}, {"$set": {"role": role}})
        return res.matched_count > 0


admin_service = AdminService()
