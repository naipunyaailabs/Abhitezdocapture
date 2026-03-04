import time
print("Starting import of app.routers.extract...")
s = time.time()
try:
    from app.routers import extract
    print(f"Successfully imported app.routers.extract in {time.time()-s:.2f}s")
except Exception as e:
    print(f"FAILED to import app.routers.extract: {e}")
