import base64
import calendar
import hashlib
import json
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Tenant
from app.services.google_calendar import build_flow, save_creds

router = APIRouter()


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def _generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256 method."""
    code_verifier = secrets.token_urlsafe(64)  # 86 URL-safe chars, within 43-128 spec
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def _encode_state(tenant: str, code_verifier: str) -> str:
    """Pack tenant slug + code_verifier into a base64url JSON state string."""
    payload = json.dumps({"t": tenant, "cv": code_verifier})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_state(state: str) -> tuple[str, str]:
    """Unpack (tenant_slug, code_verifier) from state. Returns ('', '') on failure."""
    try:
        # Add padding in case it was stripped
        padded = state + "=" * (-len(state) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("t", ""), payload.get("cv", "")
    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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
    code_verifier, code_challenge = _generate_pkce()
    state = _encode_state(tenant, code_verifier)

    flow = build_flow()
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    return RedirectResponse(url)


@router.get("/oauth/google/callback")
def oauth_google_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Google redirects here after the customer approves access.
    Decodes tenant slug and code_verifier from state, exchanges the code for tokens,
    and saves them to the tenant's DB row.
    """
    try:
        code = request.query_params.get("code")
        if not code:
            raise HTTPException(status_code=400, detail="Missing authorization code from Google")

        raw_state = request.query_params.get("state", "")
        tenant_slug, code_verifier = _decode_state(raw_state)

        flow = build_flow()
        flow.fetch_token(code=code, code_verifier=code_verifier or None)
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
                # creds.expiry is naive UTC — use timegm to convert without assuming server tz
                tenant_row.gcal_token_expires_at = calendar.timegm(creds.expiry.timetuple())
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
