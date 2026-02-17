from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.database import db
from app.routers import auth, rfp, extract, history, subscription, services, summarize, compare, summarize_rfp, upload, invoice
from app.utils.auth import get_current_user
from app.services.subscription_service import subscription_service
from app.services.history_service import history_service
from app.services.auth_service import auth_service
from app.models.user import UserResponse
import uvicorn
import os

app = FastAPI(title=settings.APP_NAME)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(rfp.router, prefix="/rfp", tags=["rfp"])
app.include_router(extract.router, prefix="/extract", tags=["extract"])
app.include_router(history.router, prefix="/history", tags=["history"])
app.include_router(subscription.router, prefix="/subscription", tags=["subscription"])
app.include_router(services.router, prefix="/services", tags=["services"])
app.include_router(summarize.router, prefix="/summarize", tags=["summarize"])
app.include_router(compare.router, prefix="/compare-quotations", tags=["compare"])
app.include_router(summarize_rfp.router, prefix="/summarize-rfp", tags=["summarize-rfp"])
app.include_router(invoice.router, prefix="/invoice", tags=["invoice"])
app.include_router(upload.router, prefix="/upload", tags=["upload"])

# Static files
static_path = os.path.join(os.path.dirname(__file__), "app/static")
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Sitemap and Robots
@app.get("/sitemap.xml")
async def sitemap():
    return FileResponse("app/static/sitemap.xml", media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    return FileResponse("app/static/robots.txt")

@app.on_event("startup")
async def startup_db_client():
    await db.connect_to_database()

@app.on_event("shutdown")
async def shutdown_db_client():
    await db.close_database_connection()


# ─── Public Pages ───────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    return templates.TemplateResponse("pricing.html", {"request": request})

@app.get("/enterprise", response_class=HTMLResponse)
async def enterprise(request: Request):
    return templates.TemplateResponse("enterprise.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/verify-email-sent", response_class=HTMLResponse)
async def verify_email_sent_page(request: Request, email: str = ""):
    return templates.TemplateResponse("verify_email_sent.html", {"request": request, "email": email})

@app.get("/verify-email", response_class=HTMLResponse)
async def verify_email_page(request: Request, token: str = ""):
    if not token:
        return templates.TemplateResponse("verify_email.html", {
            "request": request, "success": False, "error": "No verification token provided."
        })
    
    user = await auth_service.find_user_by_verification_token(token)
    if not user:
        return templates.TemplateResponse("verify_email.html", {
            "request": request, "success": False, "error": "Invalid or expired verification token."
        })
    
    await auth_service.update_user(user.userId, {
        "emailVerified": True,
        "emailVerificationToken": None,
        "emailVerificationTokenExpiry": None
    })
    
    return templates.TemplateResponse("verify_email.html", {
        "request": request, "success": True
    })


# ─── Dashboard Pages (Server-rendered with user context) ────

async def get_dashboard_context(request: Request, active_page: str):
    """Helper to build shared dashboard template context from cookie/header token."""
    token = request.cookies.get("token") or request.query_params.get("token")
    if not token:
        return None
    
    user_id = auth_service.get_user_id_from_token(token)
    if not user_id:
        return None

    user = await auth_service.find_user_by_id(user_id)
    if not user:
        return None
    
    sub = await subscription_service.get_user_subscription(user_id)
    if not sub:
        # Create trial if none exists
        sub = await subscription_service.create_trial(user_id)
    
    # Clean ObjectId
    if sub and "_id" in sub:
        del sub["_id"]

    return {
        "request": request,
        "current_user": UserResponse.model_validate(user) if hasattr(UserResponse, 'model_validate') else UserResponse.from_orm(user),
        "subscription": sub or {"planId": "trial", "planName": "Free Trial", "documentsUsed": 0, "documentsLimit": 5, "status": "active"},
        "active_page": active_page,
        "api_key": settings.API_KEY
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    ctx = await get_dashboard_context(request, "dashboard")
    if not ctx:
        return RedirectResponse("/?login=true", status_code=302)
    
    user_id = ctx["current_user"].userId
    analytics = await history_service.get_analytics(user_id, 30)
    history_data = await history_service.get_user_history(user_id, 10)
    
    ctx["analytics"] = analytics or {"totalProcessed": 0, "successCount": 0, "errorCount": 0, "days": 30}
    ctx["history"] = history_data or []
    
    return templates.TemplateResponse("dashboard.html", ctx)


@app.get("/dashboard/services", response_class=HTMLResponse)
async def dashboard_services_page(request: Request):
    ctx = await get_dashboard_context(request, "services")
    if not ctx:
        return RedirectResponse("/?login=true", status_code=302)
    return templates.TemplateResponse("dashboard_services.html", ctx)


@app.get("/dashboard/integrations", response_class=HTMLResponse)
async def dashboard_integrations_page(request: Request):
    ctx = await get_dashboard_context(request, "integrations")
    if not ctx:
        return RedirectResponse("/?login=true", status_code=302)
    return templates.TemplateResponse("dashboard_integrations.html", ctx)


@app.get("/dashboard/analytics", response_class=HTMLResponse)
async def dashboard_analytics_page(request: Request):
    ctx = await get_dashboard_context(request, "analytics")
    if not ctx:
        return RedirectResponse("/?login=true", status_code=302)
    
    user_id = ctx["current_user"].userId
    analytics = await history_service.get_analytics(user_id, 30)
    history_data = await history_service.get_user_history(user_id, 50)
    
    ctx["analytics"] = analytics or {"totalProcessed": 0, "successCount": 0, "errorCount": 0, "days": 30}
    ctx["history"] = history_data or []
    
    # Build service usage breakdown
    service_counts = {}
    for item in (history_data or []):
        sname = item.get("serviceName", "Unknown")
        service_counts[sname] = service_counts.get(sname, 0) + 1
    
    total = sum(service_counts.values()) if service_counts else 1
    colors = ["#fbbf24", "#22c55e", "#6366f1", "#ef4444", "#14b8a6", "#f97316"]
    service_usage = []
    for i, (name, count) in enumerate(sorted(service_counts.items(), key=lambda x: -x[1])):
        service_usage.append({
            "name": name,
            "count": count,
            "percent": round(count / total * 100, 1),
            "color": colors[i % len(colors)]
        })
    
    ctx["service_usage"] = service_usage
    
    return templates.TemplateResponse("dashboard_analytics.html", ctx)


@app.get("/dashboard/settings", response_class=HTMLResponse)
async def dashboard_settings_page(request: Request):
    ctx = await get_dashboard_context(request, "settings")
    if not ctx:
        return RedirectResponse("/?login=true", status_code=302)
    return templates.TemplateResponse("dashboard_settings.html", ctx)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
