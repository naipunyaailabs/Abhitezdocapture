import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os

async def check_db():
    client = AsyncIOMotorClient("mongodb://localhost:27017/docapture")
    db = client["docapture"]
    
    sessions = await db.sessions.find().to_list(length=100)
    print(f"Total sessions in DB: {len(sessions)}")
    for s in sessions:
        print(f"Token: {s.get('token')[:10]}..., User: {s.get('userId')}, Expires: {s.get('expiresAt')}")

    users = await db.users.find().to_list(length=10)
    print(f"Total users in DB: {len(users)}")
    for u in users:
        print(f"User: {u.get('userId')}, Email: {u.get('email')}")

if __name__ == "__main__":
    asyncio.run(check_db())
