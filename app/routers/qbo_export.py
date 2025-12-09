# app/routers/qbo_export.py
from datetime import datetime, date
from typing import List, Tuple, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app import models, models_finance
from app.deps import get_tenant_id
from app.routers.qbo_client import export_finance  # correct location

router = APIRouter(prefix="/finance/qbo/export", tags=["finance", "qbo"])

# Common possible tenant ID fields – we probe these dynamically
_TENANT_KEYS = ("key", "tenant_key", "tenant_id", "slug", "name", "id")


def _parse_date(d: str) -> date:
    d = d.strip()
    try:
        return datetime.fromisoformat(d).date()
    except Exception:
        return datetime.strptime(d, "%Y-%m-%d").date()


def _tenant_row(session: Session, tenant_id: str) -> Optional[models.Tenant]:
    Ten = models.Tenant
    for cand in _TENANT_KEYS:
        if hasattr(Ten, cand):
            return session.exec(
                select(Ten).where(getattr(Ten, cand) == tenant_id)
            ).first()
    return None


def _safe_tenant_value(t, fallback: str) -> str:
    if not t:
        return fallback
    for f in _TENANT_KEYS:
        if hasattr(t, f):
            try:
                v = getattr(t, f)
                if v is not None:
                    return str(v)
            except Exception:
                pass
    return fallback


def _query_finance_rows(
    session: Session,
    start: date,
    end: date,
    tenant_id: Optional[str] = None,
) -> Tuple[List[models_finance.Revenue], List[models_finance.Cost]]:
    """
    Fetch Revenue + Cost rows in [start, end].
    - 3 positional args allowed: (session, start, end)
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


@router.post("/plan")
def export_plan(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    tenant_id: str = Depends(get_tenant_id),
    session: Session = Depends(get_session),
):
    s = _parse_date(start)
    e = _parse_date(end)

    # Validate tenant exists (optional sanity check)
    _tenant_row(session, tenant_id)

    # ✅ 3 positional + 1 keyword → matches def above
    revenues, costs = _query_finance_rows(session, s, e, tenant_id=tenant_id)

    def _sum(ns):
        return float(sum((float(getattr(x, "amount", 0) or 0) for x in ns), 0.0))

    preview_revs = [
        {
            "id": r.id,
            "amount": float(r.amount or 0),
            "source": r.source or "",
            "part_code": r.part_code or "",
            "job_type": r.job_type or "",
            "notes": r.notes or "",
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in revenues[:50]
    ]
    preview_costs = [
        {
            "id": c.id,
            "amount": float(c.amount or 0),
            "category": c.category or "",
            "vendor": c.vendor or "",
            "part_code": c.part_code or "",
            "job_type": c.job_type or "",
            "notes": c.notes or "",
            "hours": float(c.hours or 0) if getattr(c, "hours", None) is not None else None,
            "hourly_rate": float(c.hourly_rate or 0) if getattr(c, "hourly_rate", None) is not None else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in costs[:50]
    ]

    return {
        "ok": True,
        "plan": {
            "tenant": tenant_id,
            "range": {"start": s.isoformat(), "end": e.isoformat()},
            "counts": {"revenues": len(revenues), "costs": len(costs)},
            "totals": {
                "revenue": _sum(revenues),
                "cost": _sum(costs),
                "gross_profit": _sum(revenues) - _sum(costs),
            },
            "preview": {"revenues": preview_revs, "costs": preview_costs},
        },
    }


@router.post("/commit")
def export_commit(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    tenant_id: str = Depends(get_tenant_id),
    session: Session = Depends(get_session),
):
    """
    Commit export: actually push journal entries / sales receipts / bills to QBO.
    Assumes QBO auth is already connected for this tenant.
    """
    s = _parse_date(start)
    e = _parse_date(end)

    # Load the tenant row
    t = _tenant_row(session, tenant_id)

    # ✅ same 3 positional + keyword call
    revenues, costs = _query_finance_rows(session, s, e, tenant_id=tenant_id)

    try:
        pushed = export_finance(
            session=session,
            tenant=t,
            revenues=revenues,
            costs=costs,
            start=s,
            end=e,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"QBO export failed: {exc}")

    return {
        "ok": True,
        "committed": {
            "revenues_exported": len(revenues),
            "costs_exported": len(costs),
            "tenant": _safe_tenant_value(t, tenant_id),
            "window": {"start": s.isoformat(), "end": e.isoformat()},
        },
    }
