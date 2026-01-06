# app/routers/invites.py
from __future__ import annotations
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from app.db import get_session

router = APIRouter(prefix="/auth/invite", tags=["auth-invite"])


# ----------------- helpers -----------------

def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    try:
        return dict(row)
    except TypeError:
        return {k: getattr(row, k) for k in dir(row) if not k.startswith("_")}


def _require_admin(x_admin_key: Optional[str]) -> None:
    admin_key = (os.getenv("INVITE_ADMIN_KEY") or "").strip()
    if not admin_key:
        # fail closed if you forgot to set it
        raise HTTPException(status_code=500, detail="INVITE_ADMIN_KEY not set")
    if (x_admin_key or "").strip() != admin_key:
        raise HTTPException(status_code=403, detail="Forbidden")


def ensure_invite_table(session: Session) -> None:
    session.exec(text("""
    CREATE TABLE IF NOT EXISTS invite_code (
        code TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        expires_at TEXT NULL,
        used_at TEXT NULL,
        note TEXT NULL
    )
    """))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------- schemas -----------------

class InviteCreateResponse(BaseModel):
    code: str
    created_at: str
    expires_at: Optional[str] = None
    note: Optional[str] = None


class InviteVerifyResponse(BaseModel):
    ok: bool
    code: str
    expires_at: Optional[str] = None
    used: bool


# ----------------- routes -----------------

@router.post("/create", response_model=InviteCreateResponse)
def create_invite(
    days_valid: int = 7,
    note: Optional[str] = None,
    session: Session = Depends(get_session),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):

    """
    Create an invitation code. Protected by header: X-Admin-Key: <INVITE_ADMIN_KEY>
    """
    _require_admin(x_admin_key)
    ensure_invite_table(session)

    days_valid = max(1, min(int(days_valid), 60))  # clamp 1..60
    code = secrets.token_urlsafe(16)
    created_at = _now_iso()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days_valid)).isoformat()

    session.exec(
        text("""
            INSERT INTO invite_code (code, created_at, expires_at, used_at, note)
            VALUES (:code, :created_at, :expires_at, NULL, :note)
        """).bindparams(
            code=code,
            created_at=created_at,
            expires_at=expires_at,
            note=(note or "").strip() or None,
        )
    )
    session.commit()

    return InviteCreateResponse(code=code, created_at=created_at, expires_at=expires_at, note=note)


@router.get("/verify", response_model=InviteVerifyResponse)
def verify_invite(
    code: str,
    session: Session = Depends(get_session),
):
    """
    Public check (no admin key): tells frontend if invite is valid/unused/not expired.
    """
    ensure_invite_table(session)

    row = session.exec(
        text("""
            SELECT code, expires_at, used_at
            FROM invite_code
            WHERE code = :code
            LIMIT 1
        """).bindparams(code=(code or "").strip())
    ).first()

    if not row:
        return InviteVerifyResponse(ok=False, code=code, expires_at=None, used=False)

    data = _row_to_dict(row)
    used = bool(data.get("used_at"))
    expires_at = data.get("expires_at")

    # expired?
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_dt:
                return InviteVerifyResponse(ok=False, code=data["code"], expires_at=expires_at, used=used)
        except Exception:
            # if parsing fails, fail closed
            return InviteVerifyResponse(ok=False, code=data["code"], expires_at=expires_at, used=used)

    if used:
        return InviteVerifyResponse(ok=False, code=data["code"], expires_at=expires_at, used=True)

    return InviteVerifyResponse(ok=True, code=data["code"], expires_at=expires_at, used=False)

