# app/routers/finance_export.py
from datetime import datetime, date
from typing import List, Tuple
import io, csv

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app import models_finance
from app.deps import get_tenant_id

router = APIRouter(prefix="/finance/export", tags=["finance"])


def _parse_date(d: str) -> date:
    d = d.strip()
    try:
        return datetime.fromisoformat(d).date()
    except Exception:
        return datetime.strptime(d, "%Y-%m-%d").date()


def _query_finance_rows(
    session: Session,
    start: date,
    end: date,
    tenant_id: str | None = None,
) -> Tuple[List[models_finance.Revenue], List[models_finance.Cost]]:
    """
    Fetch Revenue + Cost rows in [start, end].

    - 3 positional args: (session, start, end)
    - tenant_id is OPTIONAL and must be passed as a KEYWORD, not positional.
    """
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())

    rev_query = (
        select(models_finance.Revenue)
        .where(models_finance.Revenue.created_at >= start_dt)
        .where(models_finance.Revenue.created_at <= end_dt)
        .order_by(models_finance.Revenue.created_at.desc())
    )
    cost_query = (
        select(models_finance.Cost)
        .where(models_finance.Cost.created_at >= start_dt)
        .where(models_finance.Cost.created_at <= end_dt)
        .order_by(models_finance.Cost.created_at.desc())
    )

    # Multi-tenant filter if tenant_id is provided
    if tenant_id:
        rev_query = rev_query.where(models_finance.Revenue.tenant_id == tenant_id)
        cost_query = cost_query.where(models_finance.Cost.tenant_id == tenant_id)

    revs = list(session.exec(rev_query).all())
    costs = list(session.exec(cost_query).all())
    return revs, costs


@router.get("/csv")
def export_csv(
    request: Request,
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    include_revenue: bool = Query(True),
    include_cost: bool = Query(True),
    # You *can* keep the tenant query param for later admin use,
    # but for now we ignore it and trust get_tenant_id for security.
    tenant: str | None = Query(None, description="Tenant key (unused for now)"),
    tenant_id: str = Depends(get_tenant_id),
    session: Session = Depends(get_session),
):
    # Always export ONLY the caller's tenant
    effective_tenant = tenant_id

    s = _parse_date(start)
    e = _parse_date(end)

    # ✅ 3 positional + 1 keyword → matches helper signature
    revenues, costs = _query_finance_rows(session, s, e, tenant_id=effective_tenant)

    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow(
        [
            "Type",  # invoice | bill
            "LocalId",
            "Date",
            "Amount",
            "SourceOrCategory",
            "PartCode",
            "JobType",
            "Notes",
        ]
    )

    if include_revenue:
        for r in revenues:
            w.writerow(
                [
                    "invoice",
                    r.id,
                    (r.created_at.date() if r.created_at else s).isoformat(),
                    float(r.amount or 0),
                    (r.source or ""),
                    (r.part_code or ""),
                    (r.job_type or ""),
                    (r.notes or ""),
                ]
            )

    if include_cost:
        for c in costs:
            w.writerow(
                [
                    "bill",
                    c.id,
                    (c.created_at.date() if c.created_at else s).isoformat(),
                    float(c.amount or 0),
                    (c.category or ""),
                    (c.part_code or ""),
                    (c.job_type or ""),
                    (c.notes or ""),
                ]
            )

    buf.seek(0)
    filename = f"finance_export_{s.isoformat()}_{e.isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
