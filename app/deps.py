# app/deps.py
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, Query
from sqlmodel import Session, select

from app import config
from app.db import get_session
from app.models import ApiKey, Tenant
from app.routers.auth import parse_token  # reuse the same parser


def _tenant_keys() -> dict:
    """
    Return the token->tenant mapping from config.

    Prefers module-level TENANT_KEYS, falls back to settings.TENANT_KEYS.
    """
    if hasattr(config, "TENANT_KEYS") and isinstance(getattr(config, "TENANT_KEYS"), dict):
        return getattr(config, "TENANT_KEYS") or {}
    if hasattr(config, "settings") and hasattr(config.settings, "TENANT_KEYS"):
        return getattr(config.settings, "TENANT_KEYS") or {}
    return {}


def _tenant_from_key_legacy(key: Optional[str]) -> Optional[str]:
    """
    Look up tenant slug from a raw API key using legacy TENANT_KEYS.
    """
    if not key:
        return None
    return _tenant_keys().get(key.strip())


async def get_tenant_id(
    request: Request,
    # public pages
    tenant: Optional[str] = Query(None),
    tenant_key: Optional[str] = Query(None),
    # headers (for tests / legacy)
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    session: Session = Depends(get_session),  # not used yet, but kept for future
) -> str:
    """
    Central tenant resolver for *handlers*.

    Priority:

    1. request.state.tenant_id (set by tenant_middleware via JWT / X-API-Key)
    2. ?tenant=slug (public booking/lead pages)
    3. legacy ?tenant_key=... (if still used anywhere)
    4. Bearer JWT directly (for direct testing without middleware)
    5. X-API-Key -> TENANT_KEYS (legacy)
    6. fallback 'default'
    """

    # 1) Middleware already decided → trust it
    state_tenant = getattr(request.state, "tenant_id", None)
    if state_tenant:
        return str(state_tenant)

    # 2) Public pages: ?tenant=slug
    if tenant:
        return str(tenant)

    # 3) Legacy query: ?tenant_key=...
    if tenant_key:
        return str(tenant_key)

    # 4) Direct Bearer JWT (for cases where middleware is bypassed)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            info = parse_token(token)
            tenant_from_jwt = info.get("tenant_slug") or info.get("tenant")
            if tenant_from_jwt:
                return str(tenant_from_jwt)
        except Exception:
            # fall through to other methods
            pass

    # 5) Legacy X-API-Key → TENANT_KEYS
    if x_api_key:
        slug = _tenant_from_key_legacy(x_api_key)
        if slug:
            return slug

    raise HTTPException(status_code=401, detail="Tenant not resolved")

