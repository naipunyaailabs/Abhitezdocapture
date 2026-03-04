from pymongo import MongoClient
import time

uri = "mongodb://docapture:docaptureai@69.62.83.244:27017/docapture?authSource=admin&retryWrites=true&w=majority"
print(f"Connecting to {uri}...")
start = time.time()
try:
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    print(f"Connected in {time.time() - start:.2f}s")
    
    print("Testing query...")
    print("Fetching one user...")
    db = client["docapture"]
    user = db.users.find_one()
    print(f"User: {user}")
except Exception as e:
    print(f"Failed to connect: {e}")
