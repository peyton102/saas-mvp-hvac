# app/routers/admin_invites.py
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlmodel import Session

from app import config
from app.db import get_session
from app.routers.auth import get_current_user
from app.routers.invites import ensure_invite_table
from app.services.email import send_email

router = APIRouter(prefix="/admin/invites", tags=["admin-invites"])


# --------------- helpers ---------------

def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    try:
        return dict(row)
    except TypeError:
        return {k: getattr(row, k) for k in dir(row) if not k.startswith("_")}


def _ensure_columns(session: Session) -> None:
    """Add is_admin to tenant + invited_email/sent_at to invite_code if missing."""
    migrations = [
        ("sp_ai_is_admin",  "ALTER TABLE tenant ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"),
        ("sp_ai_inv_email", "ALTER TABLE invite_code ADD COLUMN invited_email TEXT"),
        ("sp_ai_inv_sent",  "ALTER TABLE invite_code ADD COLUMN sent_at TEXT"),
    ]
    for sp, ddl in migrations:
        try:
            session.exec(text(f"SAVEPOINT {sp}"))
            session.exec(text(ddl))
            session.exec(text(f"RELEASE SAVEPOINT {sp}"))
        except Exception:
            session.exec(text(f"ROLLBACK TO SAVEPOINT {sp}"))


def _require_admin(current_user: Dict[str, Any], session: Session) -> None:
    _ensure_columns(session)
    slug = current_user["tenant_slug"]
    row = session.exec(
        text("SELECT is_admin FROM tenant WHERE slug = :slug LIMIT 1").bindparams(slug=slug)
    ).first()
    if not row:
        raise HTTPException(status_code=403, detail="Tenant not found")
    if not _row_to_dict(row).get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")


def _invite_status(used_at: Optional[str], expires_at: Optional[str]) -> str:
    if used_at:
        return "signed_up"
    if expires_at:
        try:
            exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                return "expired"
        except Exception:
            pass
    return "pending"


def _send_invite_email(to_email: str, code: str) -> None:
    portal_url = getattr(config, "PORTAL_URL", "https://saas-mvp-hvac-1.onrender.com").rstrip("/")
    from_name = getattr(config, "FROM_NAME", "Torevez")
    signup_url = f"{portal_url}?invite={code}&email={to_email}"

    subject = f"You're invited to join {from_name}"
    text_body = (
        f"You've been invited to create a {from_name} account.\n\n"
        f"Click the link below to get started (link expires in 7 days):\n\n"
        f"{signup_url}\n\n"
        f"If you weren't expecting this invitation, you can safely ignore this email."
    )
    html_body = f"""
<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;max-width:520px;padding:24px">
  <h2 style="margin:0 0 12px;color:#111827">You're invited to {from_name}</h2>
  <p style="color:#374151;margin:0 0 20px">
    Someone invited you to create an account. Click the button below to get started.
    This link expires in <strong>7 days</strong>.
  </p>
  <p>
    <a href="{signup_url}"
       style="display:inline-block;padding:14px 32px;background:#f97316;color:#111827;
              font-weight:700;text-decoration:none;border-radius:8px;font-size:16px">
      Create My Account
    </a>
  </p>
  <p style="color:#6b7280;font-size:13px;margin-top:20px">
    Or copy this link:<br>
    <a href="{signup_url}" style="color:#f97316;word-break:break-all">{signup_url}</a>
  </p>
  <p style="color:#9ca3af;font-size:12px;margin-top:16px">
    If you weren't expecting this invitation, you can safely ignore this email.
  </p>
</div>
    """.strip()

    try:
        send_email(to_email, subject, text_body, html=html_body)
    except Exception as e:
        print(f"[ADMIN INVITE] email send error for {to_email}: {e}")


# --------------- schemas ---------------

class SendInviteRequest(BaseModel):
    email: EmailStr
    days_valid: int = 7


class InviteOut(BaseModel):
    code: str
    invited_email: Optional[str] = None
    created_at: str
    expires_at: Optional[str] = None
    used_at: Optional[str] = None
    sent_at: Optional[str] = None
    status: str


# --------------- routes ---------------

@router.post("/send", response_model=InviteOut)
def send_invite(
    payload: SendInviteRequest,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user, session)
    ensure_invite_table(session)

    days = max(1, min(int(payload.days_valid), 60))
    code = secrets.token_urlsafe(16)
    now_iso = datetime.now(timezone.utc).isoformat()
    expires_iso = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    session.exec(text("""
        INSERT INTO invite_code (code, created_at, expires_at, used_at, note, invited_email, sent_at)
        VALUES (:code, :created_at, :expires_at, NULL, NULL, :email, :sent_at)
    """).bindparams(
        code=code,
        created_at=now_iso,
        expires_at=expires_iso,
        email=str(payload.email),
        sent_at=now_iso,
    ))
    session.commit()

    _send_invite_email(str(payload.email), code)

    return InviteOut(
        code=code,
        invited_email=str(payload.email),
        created_at=now_iso,
        expires_at=expires_iso,
        used_at=None,
        sent_at=now_iso,
        status="pending",
    )


@router.get("", response_model=list[InviteOut])
def list_invites(
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user, session)
    ensure_invite_table(session)

    rows = session.exec(text("""
        SELECT code, invited_email, created_at, expires_at, used_at, sent_at
        FROM invite_code
        ORDER BY created_at DESC
        LIMIT 200
    """)).all()

    result = []
    for r in rows:
        d = _row_to_dict(r)
        result.append(InviteOut(
            code=d.get("code", ""),
            invited_email=d.get("invited_email"),
            created_at=d.get("created_at", ""),
            expires_at=d.get("expires_at"),
            used_at=d.get("used_at"),
            sent_at=d.get("sent_at"),
            status=_invite_status(d.get("used_at"), d.get("expires_at")),
        ))
    return result


@router.post("/{code}/resend")
def resend_invite(
    code: str,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user, session)
    ensure_invite_table(session)

    row = session.exec(text("""
        SELECT code, invited_email, used_at, expires_at
        FROM invite_code WHERE code = :code LIMIT 1
    """).bindparams(code=code)).first()

    if not row:
        raise HTTPException(status_code=404, detail="Invite not found")

    d = _row_to_dict(row)

    if d.get("used_at"):
        raise HTTPException(status_code=400, detail="Invite already used — cannot resend")

    email = d.get("invited_email")
    if not email:
        raise HTTPException(status_code=400, detail="No email stored for this invite")

    now_iso = datetime.now(timezone.utc).isoformat()
    session.exec(text("""
        UPDATE invite_code SET sent_at = :sent_at WHERE code = :code
    """).bindparams(sent_at=now_iso, code=code))
    session.commit()

    _send_invite_email(email, code)

    return {"ok": True, "code": code, "email": email}
