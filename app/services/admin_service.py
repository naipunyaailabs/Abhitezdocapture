"""
Admin service — aggregates per-user monitoring data for the Admin Access page.

For every user it combines:
  - account info (name, email, role, verified, last login)
  - subscription / credits (documentsUsed, documentsLimit)
  - files extracted (count of history docs) + per-service breakdown
  - this month's token usage and the configured monthly token cap

It also exposes admin setters for credits and the monthly token limit.
"""

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

    async def set_role(self, user_id: str, role: str) -> bool:
        db = await get_database()
        if db is None:
            return False
        res = await db.users.update_one({"userId": user_id}, {"$set": {"role": role}})
        return res.matched_count > 0


admin_service = AdminService()
