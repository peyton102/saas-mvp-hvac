import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Tenant
from app.services.google_calendar import build_flow, save_creds

router = APIRouter()


@router.get("/oauth/google/start")
def oauth_google_start(
    tenant: str = Query(..., description="Tenant slug to connect Google Calendar for"),
):
    """
    Begin the Google OAuth flow for a specific tenant.
    Send this URL to the customer during onboarding — they open it in their browser,
    sign in to Google, and click Allow. Google then redirects to /oauth/google/callback.
    Example: /oauth/google/start?tenant=acme
    """
    flow = build_flow()
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=tenant,
    )
    return RedirectResponse(url)


@router.get("/oauth/google/callback")
def oauth_google_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Google redirects here after the customer approves access.
    Reads the tenant slug from the OAuth state param and saves tokens to that tenant's DB row.
    """
    try:
        code = request.query_params.get("code")
        if not code:
            raise HTTPException(status_code=400, detail="Missing authorization code from Google")

        tenant_slug = request.query_params.get("state", "").strip()

        flow = build_flow()
        flow.fetch_token(code=code)
        creds = flow.credentials

        if tenant_slug:
            tenant_row = session.exec(
                select(Tenant).where(Tenant.slug == tenant_slug)
            ).first()
            if not tenant_row:
                raise HTTPException(
                    status_code=404, detail=f"Tenant '{tenant_slug}' not found"
                )

            tenant_row.gcal_refresh_token = creds.refresh_token
            tenant_row.gcal_access_token = creds.token
            if creds.expiry:
                tenant_row.gcal_token_expires_at = int(creds.expiry.timestamp())
            session.add(tenant_row)
            session.commit()

            return {
                "ok": True,
                "tenant": tenant_slug,
                "msg": "Google Calendar connected. New bookings will now sync to this tenant's calendar.",
                "calendar_id": tenant_row.gcal_calendar_id or "primary",
            }

        # Legacy fallback: no tenant slug → save to file (single-user dev mode)
        save_creds(creds)
        p = Path(os.getenv("GOOGLE_TOKEN_DIR", "data/google_tokens")) / "default.json"
        return {
            "ok": True,
            "msg": "Google authorized (legacy single-user mode).",
            "token_path": str(p),
            "exists": p.exists(),
        }

    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/debug/google-config")
def google_cfg():
    return {
        "client_id_prefix": (os.getenv("GOOGLE_CLIENT_ID", "")[:20] + "..."),
        "redirect_uri": os.getenv("GOOGLE_OAUTH_REDIRECT_URI"),
        "scopes": os.getenv("GOOGLE_SCOPES"),
        "token_dir": os.getenv("GOOGLE_TOKEN_DIR", "data/google_tokens"),
    }


@router.get("/debug/google-token")
def google_token():
    p = Path(os.getenv("GOOGLE_TOKEN_DIR", "data/google_tokens")) / "default.json"
    return {
        "path": str(p),
        "exists": p.exists(),
        "size": (p.stat().st_size if p.exists() else 0),
    }
