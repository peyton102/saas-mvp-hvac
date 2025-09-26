# app/deps.py
from typing import Optional
from fastapi import Header, Query, HTTPException, Request
from app import config

def _tenant_keys() -> dict:
    if hasattr(config, "TENANT_KEYS") and isinstance(getattr(config, "TENANT_KEYS"), dict):
        return getattr(config, "TENANT_KEYS") or {}
    if hasattr(config, "settings") and hasattr(config.settings, "TENANT_KEYS"):
        return getattr(config.settings, "TENANT_KEYS") or {}
    return {}

def _tenant_from_key(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return _tenant_keys().get(key.strip())

async def get_tenant_id(
    request: Request,
    x_api_key: Optional[str] = Header(None, convert_underscores=False),
    tenant_key: Optional[str] = Query(None),
) -> str:
    # 1) Prefer explicit key (header or query)
    key = x_api_key or tenant_key
    tenant = _tenant_from_key(key)

    # 2) Fallback: middleware-populated request.state.tenant_id
    if not tenant:
        tenant = getattr(request.state, "tenant_id", None)

    if not tenant:
        raise HTTPException(status_code=401, detail="Missing or unknown tenant key")
    return tenant
