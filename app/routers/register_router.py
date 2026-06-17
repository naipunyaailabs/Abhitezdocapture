"""
Register Extractor Router — API endpoints for register/ledger extraction.

Endpoints:
  POST /api/register/extract              → Extract single document using a user template
  POST /api/register/export               → Export extracted data as Excel
  GET  /api/register/user-templates       → List user's saved templates
  POST /api/register/user-templates       → Create a new user template
  GET  /api/register/user-templates/{id}  → Get a single user template
  PUT  /api/register/user-templates/{id}  → Update a user template
  DELETE /api/register/user-templates/{id}→ Delete a user template
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services.register_extractor.register_service import register_extractor_service
from app.services.register_extractor.export_engine import export_register_data
from app.services.register_extractor.user_template_service import user_template_service
from app.services.subscription_service import subscription_service
from app.services.history_service import history_service
from app.utils.auth import get_current_user, require_service
from app.models.user import UserResponse

# Per-user access guard for this service (admins bypass; None = all allowed).
# Applied to extract/export only — template CRUD stays available to any user.
require_reg = require_service("register-extractor")

router = APIRouter()

ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp",
}
MAX_FILE_SIZE_MB = 20


def _validate_file(filename: str, size: int):
    if not filename:
        raise HTTPException(400, "No filename provided.")
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"Unsupported file type '{ext}'.")
    if size > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large. Max: {MAX_FILE_SIZE_MB} MB.")


# ── Pydantic models ────────────────────────────────────────────────────────────

class CreateTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    register_type: str = Field("custom", max_length=60)
    description: str = Field("", max_length=500)
    columns: List[str] = Field(..., min_length=1)
    extraction_hints: Optional[Dict[str, str]] = None


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    register_type: Optional[str] = Field(None, max_length=60)
    description: Optional[str] = Field(None, max_length=500)
    columns: Optional[List[str]] = None
    extraction_hints: Optional[Dict[str, str]] = None


class ExportRequest(BaseModel):
    rows: List[Dict] = []
    headers: List[str] = []
    title: str = "Register_Export"


# ═══════════════════════════════════════════════════════════════════════════════
#  EXTRACT — single document using a user template
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/extract")
async def register_extract(
    document: UploadFile = File(...),
    user_template_id: str = Form(...),
    current_user: UserResponse = Depends(require_reg),
):
    """
    Extract tabular data from a register document using a saved user template.
    The user_template_id must belong to the authenticated user.
    """
    buffer = await document.read()
    _validate_file(document.filename, len(buffer))

    # Check subscription
    can_process, _sub, message = await subscription_service.can_process(current_user.userId)
    if not can_process:
        raise HTTPException(
            status_code=403,
            detail=f"Processing limit reached. {message}. Please upgrade your plan.",
        )

    # Resolve user template
    tmpl = await user_template_service.get_template(current_user.userId, user_template_id)
    if not tmpl:
        raise HTTPException(404, "Template not found.")

    columns: List[str] = tmpl.get("columns", [])
    hints: Dict[str, str] = tmpl.get("extraction_hints") or {}

    if not columns:
        raise HTTPException(400, "Template has no columns defined.")

    start = time.time()
    try:
        result = await register_extractor_service.extract(
            buffer, document.filename, columns, hints
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        print(f"[RegisterRouter] Extraction error: {e}")
        raise HTTPException(500, str(e))

    processing_time = int((time.time() - start) * 1000)

    await subscription_service.increment_usage(current_user.userId)

    await history_service.create_record({
        "userId": current_user.userId,
        "serviceId": "register-extractor",
        "serviceName": "Abhitex Register Extractor",
        "fileName": document.filename,
        "fileSize": len(buffer),
        "format": "excel",
        "status": "success",
        "result": f"Extracted {result['total_rows']} rows across {result['total_pages']} pages",
        "processingTime": processing_time,
    })

    return {"success": True, "data": result}


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/export")
async def register_export(
    body: ExportRequest,
    current_user: UserResponse = Depends(require_reg),
):
    if not body.rows or not body.headers:
        raise HTTPException(400, "rows and headers are required.")
    return export_register_data(body.rows, body.headers, title=body.title)


# ═══════════════════════════════════════════════════════════════════════════════
#  USER TEMPLATES — CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/user-templates")
async def list_user_templates(
    current_user: UserResponse = Depends(get_current_user),
):
    templates = await user_template_service.list_templates(current_user.userId)
    return {"success": True, "data": {"templates": templates}}


@router.post("/user-templates")
async def create_user_template(
    body: CreateTemplateRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    columns = [c.strip() for c in body.columns if c.strip()]
    if not columns:
        raise HTTPException(400, "At least one column is required.")
    tmpl = await user_template_service.create_template(
        user_id=current_user.userId,
        name=body.name,
        columns=columns,
        register_type=body.register_type,
        description=body.description,
        extraction_hints=body.extraction_hints,
    )
    return {"success": True, "data": tmpl}


@router.get("/user-templates/{template_id}")
async def get_user_template(
    template_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    tmpl = await user_template_service.get_template(current_user.userId, template_id)
    if not tmpl:
        raise HTTPException(404, "Template not found.")
    return {"success": True, "data": tmpl}


@router.put("/user-templates/{template_id}")
async def update_user_template(
    template_id: str,
    body: UpdateTemplateRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    updates = body.model_dump(exclude_none=True)
    if "columns" in updates:
        updates["columns"] = [c.strip() for c in updates["columns"] if c.strip()]
        if not updates["columns"]:
            raise HTTPException(400, "At least one column is required.")
    tmpl = await user_template_service.update_template(
        current_user.userId, template_id, updates
    )
    if not tmpl:
        raise HTTPException(404, "Template not found.")
    return {"success": True, "data": tmpl}


@router.delete("/user-templates/{template_id}")
async def delete_user_template(
    template_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    deleted = await user_template_service.delete_template(current_user.userId, template_id)
    if not deleted:
        raise HTTPException(404, "Template not found.")
    return {"success": True, "message": "Template deleted."}
