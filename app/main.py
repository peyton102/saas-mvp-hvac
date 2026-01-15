# app/main.py
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from app.routers import public
from collections import defaultdict
from typing import Optional
import logging
import time
import asyncio
import httpx
import os
import urllib.request
from app.routers import backup as backup_router
from app.logging_config import setup_logging
from app.services.alerts import alert_error
from app.routers.auth import parse_token
from app.routers import finance_export as finance_export_router
from app.routers.qbo_client import export_finance  # noqa: F401 (import kept for side-effects)
from app.routers import qbo_export as qbo_export_router
from app.routers.admin_tenants import router as admin_tenants_router
from app.routers import qbo as qbo_router
from app.routers.public import router as public_router
from app.routers import backup
from app import config
from app import models  # noqa: F401
from app import models_finance  # noqa: F401
from app.db import create_db_and_tables
from app.deps import get_tenant_id
from app.routers.demo import router as demo_router
from app.routers.leads import router as leads_router
from app.routers.voice import router as voice_router
from app.routers.calendly import router as calendly_router
from app.routers.reminders import router as reminders_router
from app.routers.tasks import router as tasks_router
from app.routers.reviews import router as reviews_router
from app.routers.oauth_google import router as google_oauth_router
from app.routers.availability import router as availability_router
from app.routers.bookings import router as bookings_router
from app.routers.admin import router as admin_router
from app.routers.sms_debug import router as sms_debug_router
from app.routers.debug_misc import router as debug_misc_router
from app.routers import tenant as tenant_router  # noqa: F401 (if still used elsewhere)
from app.routers import finance_parts
from app.routers import health, finance, finance_debug, sms_debug, voice, calendly, leads  # noqa: F401
from app import tenantold
from app.routers import auth
from app.routers.invites import router as invite_router
from app.routers import cron

def gen_op_id(route: APIRoute):
    method = next(iter(route.methods)).lower() if route.methods else "get"
    path = route.path_format.replace("/", "_").replace("{", "").replace("}", "")
    return f"{method}{path}"


app = FastAPI(
    title="HVAC SaaS Bot (MVP)",
    version="0.1.0",
    generate_unique_id_function=gen_op_id,
)

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PORT = int(os.getenv("PORT", "8799"))

# ---------- GLOBAL ERROR HANDLER ----------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for unhandled exceptions:
    - log full traceback
    - send a short SMS alert to Peyton
    - return generic 500 to client
    """
    logging.error("🔥 UNHANDLED SERVER ERROR", exc_info=exc)

    try:
        path = request.url.path
        subject = f"{type(exc).__name__} on {path}"
        details = str(exc)[:500]
        alert_error(subject, details)
    except Exception as alert_err:
        logging.error("Failed to send alert SMS", exc_info=alert_err)

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ---------- helpers ----------
def _tenant_keys():
    if hasattr(config, "TENANT_KEYS") and isinstance(getattr(config, "TENANT_KEYS"), dict):
        return getattr(config, "TENANT_KEYS") or {}
    if hasattr(config, "settings") and hasattr(config.settings, "TENANT_KEYS"):
        return getattr(config.settings, "TENANT_KEYS") or {}
    return {}


def _debug_bearer():
    return (getattr(config, "DEBUG_BEARER_TOKEN", None) or getattr(config, "DEBUG_BEARER", None) or "").strip()


def _log_guard(msg: str):
    try:
        if str(getattr(config, "DEBUG_GUARD_LOG", "0")) == "1":
            print(f"[debug_guard] {msg}")
    except Exception:
        pass


# ---------- raw probe ----------
@app.get("/_int/whoami-raw")
def whoami_raw(request: Request):
    auth_header = request.headers.get("authorization") or ""
    x_api_key = request.headers.get("x-api-key") or ""
    keys = _tenant_keys()
    return {
        "request_state_tenant": getattr(request.state, "tenant_id", None),
        "headers": {
            "authorization_head": (auth_header[:20] + "...") if auth_header else "",
            "x_api_key_value": x_api_key,
        },
        "mapping_has_devkey": "devkey" in keys,
        "mapping_sample": list(keys.items())[:5],
    }


# ---------- SECURE TENANT MIDDLEWARE ----------
OPEN_PATHS = {
    "/",  # root
    "/health",
    "/auth/login",
    "/auth/signup",
    "/_int/whoami-raw",
    "/whoami",
    "/debug/whoami-verbose",
    # docs + schema
    "/openapi.json",
    "/docs",
    "/redoc",
    # backup admin endpoints (they do their own bearer auth)
    "/backup/debug-admin-env",
    "/backup/sqlite",
}

IS_DEV = (str(os.getenv("ENV") or getattr(config, "ENV", "dev")).lower() == "dev")

OPEN_PREFIXES = (
    "/public/",
    "/book",
    "/lead",
    "/twilio/voice",
    "/webhooks/calendly",
    "/backup/",
    "/cron/",
      ) + (("/debug/",) if IS_DEV else tuple())



@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    """
    Secure tenant resolution.

    Only allowed sources:
    1) Authorization: Bearer <JWT>
    2) X-API-Key -> TENANT_KEYS

    BUT:
    - Always allow OPTIONS (CORS)
    - Always allow OPEN_PATHS + OPEN_PREFIXES without auth
    """
    # Always allow CORS preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if path.startswith("/cron/"):
        return await call_next(request)

    # HARD bypass for internal cron routes (cron has its own admin-key auth)
    if path.startswith("/cron/"):
        return await call_next(request)

    # Whitelist auth + health + public endpoints
    if path in OPEN_PATHS or any(path.startswith(prefix) for prefix in OPEN_PREFIXES):
        return await call_next(request)

    tenant_id: Optional[str] = None

    # --- 1) Bearer token ---
    auth_header = (request.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header[7:].strip()
        try:
            payload = parse_token(raw_token)
            tenant_id = str(
                payload.get("tenant_slug")
                or payload.get("tenant")
                or ""
            ).strip()
        except Exception as e:
            print(f"[tenant_middleware] parse_token error: {e!r}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid bearer token"},
            )

    # --- 2) X-API-Key ---
    if not tenant_id:
        api_key = (request.headers.get("x-api-key") or "").strip()
        keys = _tenant_keys()
        if api_key and api_key in keys:
            tenant_id = str(keys[api_key]).strip()

    # --- 3) Final validation ---
    if not tenant_id:
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized: missing or invalid tenant credentials"},
        )

    request.state.tenant_id = tenant_id
    return await call_next(request)


# ---------- Simple health/root ----------
@app.get("/")
def root():
    return {"ok": True, "msg": "root alive"}


@app.get("/health")
def health():
    env = str(getattr(config, "ENV", "") or getattr(getattr(config, "settings", object()), "ENV", "") or os.getenv("ENV") or "dev")
    return {"ok": True, "env": env}



# ---------- Simple per-tenant rate limiting ----------
RATE_LIMITS = {"lead": 30, "book": 20, "voice": 60, "calendly": 60}
_RATE_COUNTS = defaultdict(int)


def _bucket_for_path(path: str) -> Optional[str]:
    if path == "/lead":
        return "lead"
    if path == "/book":
        return "book"
    if path == "/twilio/voice":
        return "voice"
    if path == "/webhooks/calendly":
        return "calendly"
    return None


PORT = int(os.getenv("PORT", "8799"))

API_BASE = os.getenv("API_BASE", f"http://127.0.0.1:{PORT}")

# (rate limit middleware can be added back later if you want)


# ---------- Routers ----------
app.include_router(leads_router, dependencies=[Depends(get_tenant_id)])
app.include_router(reviews_router, dependencies=[Depends(get_tenant_id)])
app.include_router(bookings_router, dependencies=[Depends(get_tenant_id)])
app.include_router(calendly_router, dependencies=[Depends(get_tenant_id)])






app.include_router(voice_router)
app.include_router(finance_debug.router)
app.include_router(backup.router)
app.include_router(tenantold.router)
app.include_router(admin_tenants_router)
app.include_router(google_oauth_router)
app.include_router(availability_router)
app.include_router(tasks_router)
app.include_router(backup_router.router)
app.include_router(public_router)
app.include_router(admin_router)
app.include_router(sms_debug_router)
app.include_router(debug_misc_router)
app.include_router(demo_router)
app.include_router(finance.router)
app.include_router(finance_parts.router)
app.include_router(qbo_router.router)
app.include_router(qbo_export_router.router)
app.include_router(finance_export_router.router)
app.include_router(auth.router)
app.include_router(invite_router)
app.include_router(cron.router)
app.include_router(reminders_router)
# ---------- Startup ----------
@app.on_event("startup")
def on_startup():
    setup_logging()
    create_db_and_tables()
    logging.warning
    logging.info("✅ Startup complete")
