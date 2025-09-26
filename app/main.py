# app/main.py
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from collections import defaultdict
from typing import Optional
import time

from app import config
from app import models          # your existing models
from app import models_finance  # registers Revenue/Cost tables
from app.db import create_db_and_tables
from app.deps import get_tenant_id

# Routers
from app.routers.leads import router as leads_router
from app.routers.voice import router as voice_router
from app.routers.calendly import router as calendly_router
from app.routers.reminders import router as reminders_router
from app.routers.tasks import router as tasks_router
from app.routers.reviews import router as reviews_router
from app.routers.oauth_google import router as google_oauth_router
from app.routers.availability import router as availability_router
from app.routers.bookings import router as bookings_router
from app.routers.public import router as public_router
from app.routers.admin import router as admin_router
from app.routers.sms_debug import router as sms_debug_router
from app.routers.debug_misc import router as debug_misc_router
from app.routers import finance  # /finance endpoints

app = FastAPI(title="HVAC SaaS Bot (MVP)", version="0.1.0")

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
    auth = request.headers.get("authorization") or ""
    x_api_key = request.headers.get("x-api-key") or ""
    keys = _tenant_keys()
    return {
        "request_state_tenant": getattr(request.state, "tenant_id", None),
        "headers": {
            "authorization_head": (auth[:20] + "...") if auth else "",
            "x_api_key_value": x_api_key,
        },
        "mapping_has_devkey": "devkey" in keys,
        "mapping_sample": list(keys.items())[:5],
    }

# ---------- Tenant middleware ----------
@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    x_api_key = (request.headers.get("x-api-key") or "").strip()
    tenant_key_qs = (request.query_params.get("tenant_key") or "").strip()
    auth = (request.headers.get("authorization") or "")
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    token = x_api_key or tenant_key_qs or bearer

    tenant_map = _tenant_keys()
    tenant = tenant_map.get(token, "public")
    request.state.tenant_id = tenant

    try:
        print(f"[tenant_middleware] token='{(token[:6] + '...') if token else ''}' -> tenant='{tenant}'")
    except Exception:
        pass

    return await call_next(request)

# ---------- Protect ONLY /debug/* ----------
@app.middleware("http")
async def debug_auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/debug/") or path == "/debug":
        if request.method == "OPTIONS":
            return await call_next(request)

        expected = _debug_bearer()
        auth = (request.headers.get("authorization") or "").strip()
        x_api_key = (request.headers.get("x-api-key") or "").strip()
        tenant_map = _tenant_keys()

        bearer_ok = auth.lower().startswith("bearer ") and expected and (auth[7:].strip() == expected)
        key_ok = bool(x_api_key) and (x_api_key in tenant_map)

        _log_guard(f"path={path} method={request.method} bearer_ok={bearer_ok} key_ok={key_ok} x_api_key_present={bool(x_api_key)}")

        if not (bearer_ok or key_ok):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return await call_next(request)

# ---------- Simple health/root ----------
@app.get("/")
def root():
    return {"ok": True, "msg": "root alive"}

@app.get("/health")
def health():
    env = getattr(config, "ENV", getattr(getattr(config, "settings", object()), "ENV", "dev"))
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

@app.middleware("http")
async def per_tenant_rate_limit(request: Request, call_next):
    bucket = _bucket_for_path(request.url.path)
    if not bucket:
        return await call_next(request)
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return await call_next(request)

    tenant_id = getattr(request.state, "tenant_id", "public")
    limit = RATE_LIMITS.get(bucket, 0)
    if limit <= 0:
        return await call_next(request)

    minute_window = int(time.time() // 60)
    key = (tenant_id, bucket, minute_window)
    _RATE_COUNTS[key] += 1
    if _RATE_COUNTS[key] > limit:
        return JSONResponse({"detail": f"Rate limit exceeded for tenant '{tenant_id}' on {bucket}"}, status_code=429)
    return await call_next(request)

# ---------- Routers ----------
# Require tenant on these
app.include_router(leads_router,     dependencies=[Depends(get_tenant_id)])
app.include_router(reviews_router,   dependencies=[Depends(get_tenant_id)])
app.include_router(bookings_router,  dependencies=[Depends(get_tenant_id)])
app.include_router(calendly_router,  dependencies=[Depends(get_tenant_id)])
app.include_router(reminders_router, dependencies=[Depends(get_tenant_id)])
app.include_router(voice_router,     dependencies=[Depends(get_tenant_id)])

# Public/admin/etc.
app.include_router(google_oauth_router)
app.include_router(availability_router)
app.include_router(tasks_router)
app.include_router(public_router)
app.include_router(admin_router)
app.include_router(sms_debug_router)
app.include_router(debug_misc_router)

# Finance
app.include_router(finance.router)

# ---------- Startup ----------
@app.on_event("startup")
def on_startup():
    create_db_and_tables()
