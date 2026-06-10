from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

class Database:
    client: AsyncIOMotorClient = None
    db = None

    async def connect_to_database(self):
        try:
            self.client = AsyncIOMotorClient(settings.MONGODB_URI)
            # Ping to verify connection
            await self.client.admin.command('ping')
            self.db = self.client[settings.DB_NAME]
            print("Successfully connected to MongoDB")
            
            # Initialize collections with proper indexes
            try:
                # Ensure sessions collection has TTL index
                await self.db.sessions.create_index("expiresAt", expireAfterSeconds=0)
                print("[Database] TTL index created for sessions collection")
            except Exception as e:
                print(f"[Database] Note on TTL index: {e}")
                
        except Exception as e:
            print(f"CRITICAL: Failed to connect to MongoDB: {e}")
            self.db = None

    async def close_database_connection(self):
        if self.client:
            self.client.close()
            print("Disconnected from MongoDB")

db = Database()

async def get_database():
    print(f"[Database] get_database() called. db.db is {'None' if db.db is None else 'Not None'}")
    return db.db
