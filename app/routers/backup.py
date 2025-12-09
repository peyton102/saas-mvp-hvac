# app/routers/backup.py
from __future__ import annotations

import io, csv
from decimal import Decimal
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.deps import get_tenant_id
from app.models import Lead as LeadModel
from app.models_finance import Revenue, Cost  # aliases are fine

router = APIRouter(prefix="/backup", tags=["backup"])


def _csv_stream(name: str, s: io.StringIO) -> StreamingResponse:
    s.seek(0)
    return StreamingResponse(
        iter([s.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/leads.csv")
def backup_leads_csv(
        session: Session = Depends(get_session),
        tenant_id: str = Depends(get_tenant_id),
):
    rows = session.exec(
        select(LeadModel).where(LeadModel.tenant_id == tenant_id).order_by(LeadModel.id.asc())
    ).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "created_at", "name", "phone", "email", "message", "status", "tenant_id"])
    for r in rows:
        w.writerow([
            r.id,
            (r.created_at.isoformat() if r.created_at else ""),
            r.name or "",
            r.phone or "",
            r.email or "",
            (r.message or "").replace("\r", " ").replace("\n", " "),
            (getattr(r, "status", None) or "new"),
            r.tenant_id or "",
        ])
    return _csv_stream("leads.csv", buf)


@router.get("/finance.csv")
def backup_finance_csv(
        session: Session = Depends(get_session),
        tenant_id: str = Depends(get_tenant_id),
):
    rev = session.exec(
        select(Revenue).where(Revenue.tenant_id == tenant_id).order_by(Revenue.id.asc())
    ).all()
    cost = session.exec(
        select(Cost).where(Cost.tenant_id == tenant_id).order_by(Cost.id.asc())
    ).all()

    def _s(x):  # stringify Decimals cleanly
        return str(x if isinstance(x, Decimal) else (Decimal(str(x)) if x not in (None, "") else ""))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "type", "id", "created_at", "amount", "source", "category", "vendor",
        "part_code", "job_type", "hours", "hourly_rate", "notes"
    ])

    for r in rev:
        w.writerow([
            "revenue",
            r.id,
            (r.created_at.isoformat() if r.created_at else ""),
            _s(r.amount),
            (getattr(r, "source", None) or ""),
            "",  # category (n/a for revenue)
            "",  # vendor (n/a)
            r.part_code or "",
            r.job_type or "",
            "",  # hours (n/a)
            "",  # hourly_rate (n/a)
            (r.notes or "").replace("\r", " ").replace("\n", " "),
        ])

    for c in cost:
        w.writerow([
            "cost",
            c.id,
            (c.created_at.isoformat() if c.created_at else ""),
            _s(c.amount),
            "",  # source (n/a for cost)
            (c.category or ""),
            (getattr(c, "vendor", None) or ""),
            c.part_code or "",
            c.job_type or "",
            _s(getattr(c, "hours", None) or ""),
            _s(getattr(c, "hourly_rate", None) or ""),
            (c.notes or "").replace("\r", " ").replace("\n", " "),
        ])

    return _csv_stream("finance.csv", buf)
