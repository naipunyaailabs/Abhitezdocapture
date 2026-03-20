"""
User Template Service — MongoDB CRUD for user-specific register templates.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

COLLECTION = "register_templates"


class UserTemplateService:
    """CRUD for user-specific register templates stored in MongoDB."""

    def _col(self):
        from app.database import db
        return db.db[COLLECTION]

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_template(
        self,
        user_id: str,
        name: str,
        columns: List[str],
        *,
        register_type: str = "custom",
        description: str = "",
        extraction_hints: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        template_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        doc = {
            "_id": template_id,
            "user_id": user_id,
            "name": name.strip(),
            "register_type": register_type,
            "description": description.strip(),
            "columns": [c.strip() for c in columns if c.strip()],
            "extraction_hints": extraction_hints or {},
            "created_at": now,
            "updated_at": now,
        }
        await self._col().insert_one(doc)
        return self._serialize(doc)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def list_templates(self, user_id: str) -> List[Dict[str, Any]]:
        cursor = self._col().find(
            {"user_id": user_id}, {"user_id": 0}
        ).sort("created_at", -1)
        docs = await cursor.to_list(length=500)
        return [self._serialize(d) for d in docs]

    async def get_template(self, user_id: str, template_id: str) -> Optional[Dict[str, Any]]:
        doc = await self._col().find_one(
            {"_id": template_id, "user_id": user_id}, {"user_id": 0}
        )
        return self._serialize(doc) if doc else None

    # ── Update ────────────────────────────────────────────────────────────────

    async def update_template(
        self,
        user_id: str,
        template_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        allowed = {"name", "register_type", "description", "columns", "extraction_hints"}
        patch = {k: v for k, v in updates.items() if k in allowed}
        if "columns" in patch:
            patch["columns"] = [c.strip() for c in patch["columns"] if str(c).strip()]
        if "name" in patch:
            patch["name"] = str(patch["name"]).strip()
        if not patch:
            return await self.get_template(user_id, template_id)
        patch["updated_at"] = datetime.now(timezone.utc)
        result = await self._col().find_one_and_update(
            {"_id": template_id, "user_id": user_id},
            {"$set": patch},
            return_document=True,
        )
        return self._serialize(result) if result else None

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_template(self, user_id: str, template_id: str) -> bool:
        result = await self._col().delete_one({"_id": template_id, "user_id": user_id})
        return result.deleted_count > 0

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _serialize(doc: Dict) -> Dict:
        if not doc:
            return {}
        out = dict(doc)
        out["id"] = out.pop("_id", out.get("id", ""))
        # Serialize datetime fields
        for key in ("created_at", "updated_at"):
            if key in out and isinstance(out[key], datetime):
                out[key] = out[key].isoformat()
        return out


user_template_service = UserTemplateService()
