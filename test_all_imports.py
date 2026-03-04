import time
import sys

print("Testing all imports from main.py...")

start_total = time.time()

def profile_import(module_name):
    print(f"[TEST] Importing {module_name}...", end="", flush=True)
    start = time.time()
    try:
        __import__(module_name)
        print(f" DONE ({time.time() - start:.2f}s)")
    except Exception as e:
        print(f" FAILED: {e}")
        import traceback
        traceback.print_exc()

# Core
profile_import("fastapi")
profile_import("app.config")
profile_import("app.database")

# Routers
routers = [
    "app.routers.auth",
    "app.routers.rfp",
    "app.routers.extract",
    "app.routers.history",
    "app.routers.subscription",
    "app.routers.services",
    "app.routers.summarize",
    "app.routers.compare",
    "app.routers.summarize_rfp",
    "app.routers.upload",
    "app.routers.invoice",
    "app.routers.bank_reconciliation",
    "app.routers.deep_parse_router",
    "app.routers.extract_iq_router"
]

for r in routers:
    profile_import(r)

# Services
services = [
    "app.services.subscription_service",
    "app.services.history_service",
    "app.services.auth_service"
]

for s in services:
    profile_import(s)

print(f"Total import time: {time.time() - start_total:.2f}s")
print("All imports successful.")
