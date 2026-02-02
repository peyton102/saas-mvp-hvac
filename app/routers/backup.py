# app/routers/backup.py
from __future__ import annotations

import io
import os
import csv
import zipfile
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.deps import get_tenant_id
from app.models import Lead as LeadModel, AuditEvent

from app.models_finance import Revenue, Cost

router = APIRouter(prefix="/backup", tags=["backup"])


# ============================================================
# ADMIN AUTH
# ============================================================
def _require_admin_bearer(
    authorization: str | None = Header(None, alias="Authorization"),
) -> None:
    """
    Accepts Authorization: Bearer <token>
    Must match ADMIN_BEARER OR DEBUG_BEARER OR DEBUG_BEARER_TOKEN
    """

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    token = parts[1].strip()

    # Pull all accepted admin tokens from env
    admin = (os.getenv("ADMIN_BEARER") or "").strip()
    debug = (os.getenv("DEBUG_BEARER") or "").strip()
    debug_legacy = (os.getenv("DEBUG_BEARER_TOKEN") or "").strip()

    allowed = {admin, debug, debug_legacy} - {""}

    if token not in allowed:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


# ============================================================
# CSV HELPERS
# ============================================================
def _csv_stream(name: str, s: io.StringIO) -> StreamingResponse:
    s.seek(0)
    return StreamingResponse(
        iter([s.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ============================================================
# LEADS CSV (TENANT-SPECIFIC)
# ============================================================
@router.get("/leads.csv")
def backup_leads_csv(
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    rows = session.exec(
        select(LeadModel)
        .where(LeadModel.tenant_id == tenant_id)
        .order_by(LeadModel.id.asc())
    ).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["id", "created_at", "name", "phone", "email", "message", "status", "tenant_id"]
    )

    for r in rows:
        w.writerow(
            [
                r.id,
                (r.created_at.isoformat() if r.created_at else ""),
                r.name or "",
                r.phone or "",
                r.email or "",
                (r.message or "").replace("\r", " ").replace("\n", " "),
                (getattr(r, "status", None) or "new"),
                r.tenant_id or "",
            ]
        )

    return _csv_stream("leads.csv", buf)


# ============================================================
# FINANCE CSV (TENANT-SPECIFIC)
# ============================================================
@router.get("/finance.csv")
def backup_finance_csv(
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    rev = session.exec(
        select(Revenue)
        .where(Revenue.tenant_id == tenant_id)
        .order_by(Revenue.id.asc())
    ).all()
    cost = session.exec(
        select(Cost)
        .where(Cost.tenant_id == tenant_id)
        .order_by(Cost.id.asc())
    ).all()

    def _s(x):
        if x in (None, ""):
            return ""
        if isinstance(x, Decimal):
            return str(x)
        return str(Decimal(str(x)))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "type",
            "id",
            "created_at",
            "amount",
            "source",
            "category",
            "vendor",
            "part_code",
            "job_type",
            "hours",
            "hourly_rate",
            "notes",
        ]
    )

    for r in rev:
        w.writerow(
            [
                "revenue",
                r.id,
                (r.created_at.isoformat() if r.created_at else ""),
                _s(r.amount),
                (getattr(r, "source", None) or ""),
                "",
                "",
                r.part_code or "",
                r.job_type or "",
                "",
                "",
                (r.notes or "").replace("\r", " ").replace("\n", " "),
            ]
        )

    for c in cost:
        w.writerow(
            [
                "cost",
                c.id,
                (c.created_at.isoformat() if c.created_at else ""),
                _s(c.amount),
                "",
                (c.category or ""),
                (getattr(c, "vendor", None) or ""),
                c.part_code or "",
                c.job_type or "",
                _s(getattr(c, "hours", None) or ""),
                _s(getattr(c, "hourly_rate", None) or ""),
                (c.notes or "").replace("\r", " ").replace("\n", " "),
            ]
        )

    return _csv_stream("finance.csv", buf)


# ============================================================
# FULL SQLITE BACKUP (ADMIN ONLY)
# ============================================================
@router.post("/sqlite")
def backup_sqlite(_: None = Depends(_require_admin_bearer)):
    """
    Returns sqlite-backup.zip containing your SQLite DB file.
    Admin-only.
    """
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/app.db")

    if db_url.startswith("sqlite:///"):
        db_path = Path(db_url.replace("sqlite:///", "", 1))
    else:
        db_path = Path("data/app.db")

    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"DB file not found: {db_path}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, arcname=db_path.name)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="sqlite-backup.zip"'},
    )


# ============================================================
# SAFE DEBUG ENDPOINTS (NO SECRETS)
# ============================================================

@router.get("/debug-admin-env")
def debug_admin_env(_: None = Depends(_require_admin_bearer)):
    return {
        "ADMIN_BEARER_set": bool(os.getenv("ADMIN_BEARER")),
        "DEBUG_BEARER_set": bool(os.getenv("DEBUG_BEARER")),
        "DEBUG_BEARER_TOKEN_set": bool(os.getenv("DEBUG_BEARER_TOKEN")),
    }


@router.get("/debug-env")
def debug_env():
    """
    No secrets shown — only true/false presence flags.
    Allows us to test Render env without needing admin auth.
    """
    return {
        "ADMIN_PRESENT": bool(os.getenv("ADMIN_BEARER")),
        "DEBUG_PRESENT": bool(os.getenv("DEBUG_BEARER")),
        "DEBUG_TOKEN_PRESENT": bool(os.getenv("DEBUG_BEARER_TOKEN")),
    }
# ============================================================
# SEATBELT / AUDIT EVENTS (ADMIN ONLY)
# ============================================================

@router.get("/audit/events")
def backup_audit_events(
    limit: int = Query(50, ge=1, le=500),
    tenant_id: str | None = Query(None),
    category: str | None = Query(None),
    action: str | None = Query(None),
    _: None = Depends(_require_admin_bearer),
    session: Session = Depends(get_session),
):
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)

    if tenant_id:
        stmt = stmt.where(AuditEvent.tenant_id == tenant_id)
    if category:
        stmt = stmt.where(AuditEvent.category == category)
    if action:
        stmt = stmt.where(AuditEvent.action == action)

    rows = session.exec(stmt).all()

    return [
        {
            "id": r.id,
            "created_at": (r.created_at.isoformat() if r.created_at else None),
            "tenant_id": r.tenant_id,
            "user_email": r.user_email,
            "category": r.category,
            "action": r.action,
            "ok": r.ok,
            "error": r.error,
            "payload_json": r.payload_json,
        }
        for r in rows
    ]
