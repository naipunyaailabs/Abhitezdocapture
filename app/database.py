from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

class Database:
    client: AsyncIOMotorClient = None
    db = None

    async def connect_to_database(self):
        self.client = AsyncIOMotorClient(settings.MONGODB_URI)
        self.db = self.client[settings.DB_NAME]
        print("Connected to MongoDB")

    async def close_database_connection(self):
        if self.client:
            self.client.close()
            print("Disconnected from MongoDB")

db = Database()

async def get_database():
    return db.db
