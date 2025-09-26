# app/routers/debug_misc.py
from fastapi import APIRouter, Request
from app import config

router = APIRouter(prefix="", tags=["debug"])

def _tenant_keys():
    if hasattr(config, "TENANT_KEYS") and isinstance(getattr(config, "TENANT_KEYS"), dict):
        return getattr(config, "TENANT_KEYS") or {}
    if hasattr(config, "settings") and hasattr(config.settings, "TENANT_KEYS"):
        return getattr(config.settings, "TENANT_KEYS") or {}
    return {}

@router.get("/debug/whoami-verbose")
def whoami_verbose(request: Request):
    auth = request.headers.get("authorization") or ""
    x_api_key = request.headers.get("x-api-key") or ""
    return {
        "tenant_id": getattr(request.state, "tenant_id", None),
        "headers_seen": {
            "authorization_startswith": (auth[:20] + "..." if auth else ""),
            "x_api_key_present": bool(x_api_key),
            "x_api_key_value": x_api_key,
        },
        "mapping_has_devkey": "devkey" in _tenant_keys().keys(),
        "mapping_sample": list(_tenant_keys().items())[:5],
    }
