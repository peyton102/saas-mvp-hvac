# app/routers/backup.py
from __future__ import annotations

import io
import os
import csv
import zipfile
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.deps import get_tenant_id
from app.models import Lead as LeadModel
from app.models_finance import Revenue, Cost

router = APIRouter(prefix="/backup", tags=["backup"])


# ====== AUTH FOR ADMIN BACKUPS ======
def _require_admin_bearer(
    authorization: str | None = Header(None, alias="Authorization"),
) -> None:
    """
    Accepts: Authorization: Bearer <token>

    Token must match ANY of:
      - ADMIN_BEARER
      - DEBUG_BEARER
      - DEBUG_BEARER_TOKEN
    from environment.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    token = parts[1]

    expected = (
        os.getenv("ADMIN_BEARER")
        or os.getenv("DEBUG_BEARER")
        or os.getenv("DEBUG_BEARER_TOKEN")
        or ""
    ).strip()

    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


# ====== CSV HELPERS ======
def _csv_stream(name: str, s: io.StringIO) -> StreamingResponse:
    s.seek(0)
    return StreamingResponse(
        iter([s.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ====== LEADS BACKUP (PER TENANT) ======
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


# ====== FINANCE BACKUP (PER TENANT) ======
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


# ====== FULL SQLITE BACKUP (ADMIN ONLY) ======
@router.post("/sqlite")
def backup_sqlite(_: None = Depends(_require_admin_bearer)):
    """
    Admin-only: return a ZIP containing the SQLite DB.
    """
    # Figure out DB path – default matches your local setup
    db_url = os.getenv("DATABASE_URL", "sqlite:///data/app.db")
    # crude parse for sqlite:///... style
    if db_url.startswith("sqlite:///"):
        db_path = Path(db_url.replace("sqlite:///", "", 1))
    else:
        # fallback: assume same as local
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
        headers={
            "Content-Disposition": 'attachment; filename="sqlite-backup.zip"'
        },
    )
@router.get("/debug-admin-env")
def debug_admin_env():
    """
    Dev-only helper to check if ADMIN/DEBUG bearer env vars
    are actually set on this backend.
    Does NOT return the secrets, only booleans.
    """
    return {
        "ADMIN_BEARER_set": bool(os.getenv("ADMIN_BEARER")),
        "DEBUG_BEARER_set": bool(os.getenv("DEBUG_BEARER")),
        "DEBUG_BEARER_TOKEN_set": bool(os.getenv("DEBUG_BEARER_TOKEN")),
    }