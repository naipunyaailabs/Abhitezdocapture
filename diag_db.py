from pymongo import MongoClient
from datetime import datetime

def check_db():
    try:
        client = MongoClient("mongodb://localhost:27017/")
        db = client["docapture"]
        
        print("--- SESSIONS ---")
        sessions = list(db.sessions.find())
        print(f"Total sessions: {len(sessions)}")
        for s in sessions:
            print(f"Token: {s.get('token')[:10]}..., UserID: {s.get('userId')}, Expires: {s.get('expiresAt')}")

        print("\n--- USERS ---")
        users = list(db.users.find().limit(5))
        print(f"Total users (sample): {len(users)}")
        for u in users:
            print(f"UserID: {u.get('userId')}, Email: {u.get('email')}, Name: {u.get('name')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_db()
