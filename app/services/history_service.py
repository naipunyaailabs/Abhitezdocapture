from typing import List, Optional, Any
from app.database import get_database
from app.models.schemas import ProcessingHistoryBase, ProcessingHistoryInDB
from datetime import datetime, timedelta
from bson import ObjectId

class HistoryService:
    async def get_user_history(self, user_id: str, limit: int = 50, offset: int = 0) -> List[dict]:
        db = await get_database()
        if db is None: return []
        
        cursor = db.history.find({"userId": user_id}).sort("processedAt", -1).skip(offset).limit(limit)
        history = await cursor.to_list(length=limit)
        for h in history:
            h["id"] = str(h["_id"])
            del h["_id"]
        return history

    async def create_record(self, data: dict) -> Optional[dict]:
        db = await get_database()
        if db is None: return None
        
        data["processedAt"] = datetime.now()
        result = await db.history.insert_one(data)
        data["id"] = str(result.inserted_id)
        if "_id" in data:
            del data["_id"]
        return data

    async def get_analytics(self, user_id: str, days: int = 30) -> dict:
        db = await get_database()
        if db is None: return {}
        
        since = datetime.now() - timedelta(days=days)
        total = await db.history.count_documents({"userId": user_id, "processedAt": {"$gte": since}})
        success = await db.history.count_documents({"userId": user_id, "status": "success", "processedAt": {"$gte": since}})
        
        return {
            "totalProcessed": total,
            "successCount": success,
            "errorCount": total - success,
            "days": days
        }

history_service = HistoryService()
