"""
Service registry — the canonical list of dashboard services for per-user
access control.

Each dashboard service card is hardcoded in `dashboard_services.html`. To gate
access per user, every card carries a stable `data-service-id` (see the
`card_form` ids below) and the admin assigns each user a subset of these ids.

The id strings here are the contract shared by:
  - the admin "Manage Services" UI (checkbox list),
  - `users.allowedServices` stored in MongoDB, and
  - the dashboard card filtering (server-side render + client-side hide).

`allowedServices == None` (the default / absent) means ALL services are
allowed — this preserves existing behavior for every pre-existing user.
"""

from typing import List, Optional

# Ordered to match the dashboard card layout.
SERVICES = [
    {"id": "invoice-extraction",   "name": "Invoice Extraction (Fixed Template)"},
    {"id": "extract-iq",           "name": "Invoice Extraction (Custom Templates)"},
    {"id": "register-extractor",   "name": "Abhitex Register Extractor"},
    {"id": "waste-downgrade",      "name": "Waste & Downgrade"},
    {"id": "lot-history-cards",    "name": "Lot History Cards Extraction"},
    {"id": "production-sheets",    "name": "Production Sheets"},
]

VALID_SERVICE_IDS = {s["id"] for s in SERVICES}


def normalize_allowed(allowed: Optional[List[str]]) -> Optional[List[str]]:
    """Validate/clean an allowedServices value coming from the API.

    Returns None (= all allowed) when `allowed` is None, otherwise a list of the
    valid known service ids (unknown ids are dropped, order from SERVICES kept).
    """
    if allowed is None:
        return None
    requested = {a for a in allowed if a in VALID_SERVICE_IDS}
    return [s["id"] for s in SERVICES if s["id"] in requested]


def is_service_allowed(allowed: Optional[List[str]], service_id: str) -> bool:
    """True if a user with this allowedServices value may use `service_id`."""
    if allowed is None:
        return True
    return service_id in allowed
