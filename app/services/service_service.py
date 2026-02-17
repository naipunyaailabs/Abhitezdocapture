from typing import List, Optional, Any
from app.database import get_database
from datetime import datetime

class ServiceService:
    async def find_all_services(self) -> List[dict]:
        db = await get_database()
        if db is None: return []
        
        cursor = db.services.find({"isActive": True})
        services = await cursor.to_list(length=100)
        for s in services:
            s["id"] = str(s["_id"])
            del s["_id"]
        return services

    async def find_service_by_id(self, service_id: str) -> Optional[dict]:
        db = await get_database()
        if db is None: return None
        service = await db.services.find_one({"id": service_id, "isActive": True})
        if service:
            service["id"] = str(service["_id"])
            del service["_id"]
        return service

    async def find_service_by_slug(self, slug: str) -> Optional[dict]:
        db = await get_database()
        if db is None: return None
        service = await db.services.find_one({"slug": slug, "isActive": True})
        if service:
            service["id"] = str(service["_id"])
            del service["_id"]
        return service

service_service = ServiceService()
