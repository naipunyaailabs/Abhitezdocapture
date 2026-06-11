"""
One-time migration: copy collection STRUCTURE (collections + indexes) from the
old client database to the new client's database, plus only the data needed for
the current login user to work.

SAFETY:
  - The OLD database is opened READ-ONLY. This script never writes to or drops
    anything on the old server.
  - It only writes to the NEW database.

What it migrates:
  - Every collection that exists in the old DB is (re)created in the new DB.
  - All indexes on each old collection are recreated on the new collection.
  - DATA copied: only the single user `MIGRATE_USER_EMAIL`, that user's
    matching subscription document, and the full `services` collection
    (app configuration, not client business data).
  - No other documents (history, sessions, sequences, templates, other users)
    are copied — structure only.

Usage:
  Set OLD_MONGODB_URI and NEW_MONGODB_URI below (or via env vars), then:
      python scripts/migrate_to_new_db.py
"""

import os
from urllib.parse import quote_plus

import pymongo

# ── Configuration ───────────────────────────────────────────────────────────
OLD_MONGODB_URI = os.getenv(
    "OLD_MONGODB_URI",
    "mongodb://docapture:docaptureai@69.62.83.244:27017/docapture"
    "?authSource=admin&retryWrites=true&w=majority",
)
OLD_DB_NAME = os.getenv("OLD_DB_NAME", "docapture")

# NEW: build from raw parts so special chars in the password are escaped safely.
_NEW_USER = os.getenv("NEW_DB_USER", "mongo")
_NEW_PASS = os.getenv("NEW_DB_PASS", "Admin@123,.")
_NEW_HOST = os.getenv("NEW_DB_HOST", "")  # e.g. external IP:port from Dokploy
# If you have a full URI already, set NEW_MONGODB_URI directly and it wins.
NEW_MONGODB_URI = os.getenv("NEW_MONGODB_URI", "")
if not NEW_MONGODB_URI:
    if not _NEW_HOST:
        raise SystemExit(
            "Set NEW_MONGODB_URI (full URI) or NEW_DB_HOST (host:port) env var."
        )
    NEW_MONGODB_URI = (
        f"mongodb://{quote_plus(_NEW_USER)}:{quote_plus(_NEW_PASS)}@{_NEW_HOST}"
        f"/?authSource=admin&directConnection=true"
    )
NEW_DB_NAME = os.getenv("NEW_DB_NAME", "docapture")

MIGRATE_USER_EMAIL = os.getenv("MIGRATE_USER_EMAIL", "AjayKumarB@cognitbotz.com")
COPY_SERVICES_DATA = True


def recreate_indexes(old_coll, new_coll):
    """Recreate every index from old_coll on new_coll (skips the default _id)."""
    created = 0
    for idx in old_coll.list_indexes():
        name = idx.get("name")
        if name == "_id_":
            continue
        keys = list(idx["key"].items())
        opts = {
            k: v
            for k, v in idx.items()
            if k not in ("v", "key", "ns")
        }
        # 'name' is allowed; keep unique/sparse/expireAfterSeconds/partial etc.
        try:
            new_coll.create_index(keys, **opts)
            created += 1
        except Exception as e:
            print(f"      ! index '{name}' skipped: {e}")
    return created


def main():
    print("Connecting to OLD database (read-only)...")
    old_client = pymongo.MongoClient(OLD_MONGODB_URI, serverSelectionTimeoutMS=10000)
    old_client.admin.command("ping")
    old_db = old_client[OLD_DB_NAME]

    print("Connecting to NEW database...")
    new_client = pymongo.MongoClient(NEW_MONGODB_URI, serverSelectionTimeoutMS=10000)
    new_client.admin.command("ping")
    new_db = new_client[NEW_DB_NAME]

    collections = old_db.list_collection_names()
    print(f"\nFound {len(collections)} collections in old DB: {collections}\n")

    for name in collections:
        old_coll = old_db[name]
        new_coll = new_db[name]
        # Ensure the collection exists in the new DB even if empty.
        if name not in new_db.list_collection_names():
            new_db.create_collection(name)
        n_idx = recreate_indexes(old_coll, new_coll)
        print(f"  [{name}] structure ready ({n_idx} index(es) recreated)")

    # ── Copy only the data we actually need ────────────────────────────────
    print("\nCopying required data...")

    # 1) The single login user (case-insensitive email match)
    user = old_db.users.find_one(
        {"email": {"$regex": f"^{MIGRATE_USER_EMAIL}$", "$options": "i"}}
    )
    if not user:
        print(f"  ! WARNING: user '{MIGRATE_USER_EMAIL}' not found in old DB.")
        user_id = None
    else:
        user_id = user.get("userId")
        new_db.users.replace_one({"_id": user["_id"]}, user, upsert=True)
        print(f"  + user '{user.get('email')}' (userId={user_id}) copied")

    # 2) That user's subscription, so the dashboard renders
    if user_id is not None:
        sub = old_db.subscriptions.find_one({"userId": user_id})
        if sub:
            new_db.subscriptions.replace_one({"_id": sub["_id"]}, sub, upsert=True)
            print("  + subscription for user copied")
        else:
            print("  - no subscription found for user (app will create a trial)")

    # 3) services collection (app configuration)
    if COPY_SERVICES_DATA and "services" in collections:
        count = 0
        for doc in old_db.services.find({}):
            new_db.services.replace_one({"_id": doc["_id"]}, doc, upsert=True)
            count += 1
        print(f"  + {count} services document(s) copied")

    print("\nMigration complete.")
    print(f"  New DB '{NEW_DB_NAME}' now has collections: "
          f"{new_db.list_collection_names()}")

    old_client.close()
    new_client.close()


if __name__ == "__main__":
    main()
