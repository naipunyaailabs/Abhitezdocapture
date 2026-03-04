import time
import sys

def profile_import(module_name):
    start = time.time()
    __import__(module_name)
    print(f"Imported {module_name} in {time.time() - start:.2f}s")

print("Profiling imports...")
profile_import("fastapi")
profile_import("app.config")
profile_import("app.database")
profile_import("app.routers.auth")
profile_import("app.routers.rfp")
profile_import("app.routers.extract")
profile_import("app.routers.history")
profile_import("app.routers.subscription")
profile_import("app.routers.services")
profile_import("app.routers.summarize")
profile_import("app.routers.compare")
profile_import("app.routers.summarize_rfp")
profile_import("app.routers.upload")
profile_import("app.routers.invoice")
profile_import("app.routers.bank_reconciliation")
profile_import("app.routers.deep_parse_router")
profile_import("app.routers.extract_iq_router")
print("All imports done.")
