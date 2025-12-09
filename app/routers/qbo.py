# app/routers/qbo.py
from __future__ import annotations
import os, time, uuid, base64, logging
from typing import Optional
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Tenant

router = APIRouter(tags=["qbo"])

# =========================
# Env / Config
# =========================
QBO_ENV = os.getenv("QBO_ENV", "sandbox").lower()
QBO_AUTH_URL  = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QBO_API_HOST  = "https://sandbox-quickbooks.api.intuit.com" if QBO_ENV == "sandbox" else "https://quickbooks.api.intuit.com"

CLIENT_ID     = os.getenv("QBO_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET", "")
REDIRECT_URI  = os.getenv("QBO_REDIRECT_URI", "")

# Force accounting-only during debug
SCOPES = "com.intuit.quickbooks.accounting"


logging.getLogger().setLevel(logging.INFO)
logging.info(f"[qbo] env={QBO_ENV} redirect={REDIRECT_URI} scopes='{SCOPES}'")

# =========================
# Helpers
# =========================
def _now() -> int:
    return int(time.time())

def _basic_auth() -> str:
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("utf-8")

def _ensure_env():
    if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
        raise HTTPException(500, "Missing QBO env: QBO_CLIENT_ID/SECRET/REDIRECT_URI")

def _tenant(session: Session, slug="public") -> Tenant:
    t = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not t:
        t = Tenant(slug=slug)
        session.add(t); session.commit(); session.refresh(t)
    return t

def _api_base(realm: str) -> str:
    return f"{QBO_API_HOST}/v3/company/{realm}"

def _needs_refresh(expires_at: Optional[int]) -> bool:
    try:
        return not expires_at or _now() >= (int(expires_at) - 90)  # refresh ~90s early
    except Exception:
        return True

def _refresh(session: Session, t: Tenant) -> Tenant:
    if not t.qbo_refresh_token:
        raise HTTPException(400, "No refresh_token; reconnect with 'offline_access' to enable refresh.")
    r = requests.post(
        QBO_TOKEN_URL,
        headers={
            "Authorization": _basic_auth(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={"grant_type": "refresh_token", "refresh_token": t.qbo_refresh_token},
        timeout=30,
    )
    if not r.ok:
        raise HTTPException(r.status_code, f"QBO refresh failed: {r.text}")
    tok = r.json()
    t.qbo_access_token = tok.get("access_token", "")
    # Intuit rotates refresh tokens
    if tok.get("refresh_token"):
        t.qbo_refresh_token = tok["refresh_token"]
    t.qbo_token_expires_at = _now() + int(tok.get("expires_in", 3600))
    session.add(t); session.commit(); session.refresh(t)
    return t

# =========================
# 1) Start OAuth (cookie-backed state)
# =========================
@router.get("/qbo/connect")
def qbo_connect(session: Session = Depends(get_session), tenant: str = Query("public")):
    _ensure_env(); _tenant(session, tenant)
    state = uuid.uuid4().hex

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": state,
    }
    url = f"{QBO_AUTH_URL}?{urlencode(params)}"
    logging.info(f"[qbo] authorize_url: {url}")

    resp = RedirectResponse(url)
    # Persist state & tenant in httpOnly cookies to survive dev reloads
    resp.set_cookie("qbo_state", state, max_age=600, httponly=True, secure=True, samesite="lax")
    resp.set_cookie("qbo_tenant", tenant, max_age=600, httponly=True, secure=True, samesite="lax")
    return resp

# Debug helper to inspect the built URL & scopes (no redirect)
@router.get("/qbo/connect/url")
def qbo_connect_url():
    q = urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": "DEBUGONLY",
    })
    return {"authorize_url": f"{QBO_AUTH_URL}?{q}", "scopes": SCOPES}

# =========================
# 2) Callback: code -> tokens
# =========================
@router.get("/oauth/qbo/callback")
def qbo_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    realmId: Optional[str] = None,
    session: Session = Depends(get_session),
):
    _ensure_env()

    # If Intuit rejected at authorize time, surface that plainly.
    if request.query_params.get("error"):
        return {
            "ok": False,
            "note": "Provider returned an error before code exchange.",
            "debug_url": str(request.url),
        }

    if not code or not realmId:
        raise HTTPException(400, "Missing authorization code or realmId (start at /qbo/connect).")

    cookie_state = request.cookies.get("qbo_state")
    if not cookie_state or state != cookie_state:
        raise HTTPException(400, "State mismatch (don’t open callback directly; start at /qbo/connect).")

    tenant_slug = request.cookies.get("qbo_tenant", "public")
    t = _tenant(session, tenant_slug)

    r = requests.post(
        QBO_TOKEN_URL,
        headers={
            "Authorization": _basic_auth(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
        timeout=30,
    )
    if not r.ok:
        raise HTTPException(r.status_code, f"QBO token exchange failed: {r.text}")
    tok = r.json()

    t.qbo_realm_id = realmId
    t.qbo_access_token = tok.get("access_token", "")
    t.qbo_refresh_token = tok.get("refresh_token", "")  # requires offline_access to be present
    t.qbo_token_expires_at = _now() + int(tok.get("expires_in", 3600))
    session.add(t); session.commit(); session.refresh(t)

    # Clear cookies on success (optional)
    resp = JSONResponse({
        "ok": True,
        "tenant": tenant_slug,
        "realmId": realmId,
        "has_refresh": bool(t.qbo_refresh_token)
    })
    resp.set_cookie("qbo_state", "", max_age=0)
    resp.set_cookie("qbo_tenant", "", max_age=0)
    return resp

# =========================
# 3) Status (friendly)
# =========================
@router.get("/qbo/status")
def qbo_status(session: Session = Depends(get_session), tenant: str = Query("public")):
    t = _tenant(session, tenant)
    minutes = None
    if t.qbo_token_expires_at:
        minutes = max(0, int((t.qbo_token_expires_at - _now()) / 60))

    connected = bool(t.qbo_realm_id and t.qbo_access_token)
    return {
        "connected": connected,
        "tenant": tenant,
        "env": QBO_ENV,
        "realmId": t.qbo_realm_id or "",
        "has_access_token": bool(t.qbo_access_token),
        "has_refresh_token": bool(t.qbo_refresh_token),
        "minutes_left": minutes,
        "scopes": SCOPES,
        "redirect": REDIRECT_URI,
    }

# =========================
# 4) Manual refresh (prove rotation)
# =========================
@router.post("/qbo/refresh")
def qbo_refresh(session: Session = Depends(get_session), tenant: str = Query("public")):
    t = _tenant(session, tenant)
    if not t.qbo_refresh_token:
        raise HTTPException(400, "No refresh_token available. Reconnect with 'offline_access'.")
    t = _refresh(session, t)
    return {"ok": True, "access_expires_in": max(0, (t.qbo_token_expires_at or 0) - _now())}

# Optional: quiet auto-refresh hook (won’t spam logs if no refresh_token yet)
from fastapi import Response

@router.post("/qbo/refresh-if-needed")
def qbo_refresh_if_needed(session: Session = Depends(get_session), tenant: str = Query("public")):
    t = _tenant(session, tenant)
    if not t.qbo_refresh_token:
        # 204 MUST be an empty body
        return Response(status_code=204)
    did = False
    if _needs_refresh(t.qbo_token_expires_at):
        _refresh(session, t)
        did = True
    return {"ok": True, "did_refresh": did}


# =========================
# 5) CompanyInfo sanity (POST)
# =========================
@router.post("/finance/sync/test")
def finance_sync_test(session: Session = Depends(get_session), tenant: str = Query("public")):
    t = _tenant(session, tenant)
    if not (t.qbo_realm_id and t.qbo_access_token):
        raise HTTPException(400, "QBO not connected (missing realm or access token).")
    if t.qbo_refresh_token and _needs_refresh(t.qbo_token_expires_at):
        t = _refresh(session, t)

    r = requests.get(
        f"{_api_base(t.qbo_realm_id)}/companyinfo/{t.qbo_realm_id}",
        headers={"Authorization": f"Bearer {t.qbo_access_token}", "Accept": "application/json"},
        timeout=30,
    )
    if not r.ok:
        raise HTTPException(r.status_code, r.text)
    return r.json()

# =========================
# 6) Disconnect (clear saved tokens)
# =========================
@router.post("/qbo/disconnect")
def qbo_disconnect(session: Session = Depends(get_session), tenant: str = Query("public")):
    t = _tenant(session, tenant)
    t.qbo_realm_id = None
    t.qbo_access_token = None
    t.qbo_refresh_token = None
    t.qbo_token_expires_at = None
    session.add(t); session.commit()
    return {"ok": True, "disconnected": tenant}
