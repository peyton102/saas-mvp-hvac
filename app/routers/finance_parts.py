# app/routers/finance_parts.py
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, Session  # <- use sqlmodel.Session (matches get_session)
from decimal import Decimal

from app.db import get_session
from app.deps import get_tenant_id
from app.models_finance import FinanceRevenue, FinanceCost

router = APIRouter(prefix="/finance", tags=["finance"])


def _parse_iso(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid datetime. Use ISO like '2025-10-04T00:00:00'",
        )


@router.get("/parts_summary")
def parts_summary(
    start: str = Query(..., description="ISO start e.g. 2025-10-01T00:00:00"),
    end: str = Query(..., description="ISO end   e.g. 2025-10-31T23:59:59"),
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    dt_start = _parse_iso(start)
    dt_end = _parse_iso(end)

    # Revenue (part_code, job_type, amount)
    r_stmt = (
        select(
            FinanceRevenue.part_code,
            FinanceRevenue.job_type,
            FinanceRevenue.amount,
        )
        .where(
            FinanceRevenue.tenant_id == tenant_id,
            FinanceRevenue.created_at >= dt_start,
            FinanceRevenue.created_at <= dt_end,
        )
    )

    # Costs (part_code, job_type, amount, hours, hourly_rate, category)
    c_stmt = (
        select(
            FinanceCost.part_code,
            FinanceCost.job_type,
            FinanceCost.amount,
            FinanceCost.hours,
            FinanceCost.hourly_rate,
            FinanceCost.category,
        )
        .where(
            FinanceCost.tenant_id == tenant_id,
            FinanceCost.created_at >= dt_start,
            FinanceCost.created_at <= dt_end,
        )
    )

    r_rows = session.exec(r_stmt).all()
    c_rows = session.exec(c_stmt).all()

    # Aggregate in Python by (part_code, job_type)
    # Keep Decimal for accuracy, convert to strings at the end
    agg: Dict[Tuple[str, str], Dict[str, Decimal]] = defaultdict(
        lambda: {
            "revenue": Decimal("0"),
            "cost": Decimal("0"),
            "hours": Decimal("0"),
            "labor_cost": Decimal("0"),
        }
    )

    def key(part_code, job_type):
        return (part_code or "(none)", job_type or "(none)")

    # Revenue rollup
    for part_code, job_type, amount in r_rows:
        k = key(part_code, job_type)
        agg[k]["revenue"] += Decimal(str(amount or 0))

    # Cost + labor rollup
    # Cost + labor rollup (treat amount as parts; labor = hours * hourly_rate)
    for part_code, job_type, amount, hours, hourly_rate, category in c_rows:
        k = key(part_code, job_type)

        parts_amt = Decimal(str(amount or 0))
        h = Decimal(str(hours or 0))
        r = Decimal(str(hourly_rate or 0))
        labor_amt = (h * r) if (h > 0 and r > 0) else Decimal("0")

        # totals
        agg[k]["hours"] += h
        agg[k]["labor_cost"] += labor_amt
        agg[k]["cost"] += (parts_amt + labor_amt)

    # Build response rows
    out = []
    for (part_code, job_type), vals in agg.items():
        rev = vals["revenue"]
        cost = vals["cost"]
        profit = rev - cost
        margin = (profit / rev * Decimal("100")) if rev else Decimal("0")
        out.append(
            {
                "part_code": part_code,
                "job_type": job_type,
                "revenue_total": f"{rev:.2f}",
                "cost_total": f"{cost:.2f}",
                "profit": f"{profit:.2f}",
                "margin_pct": f"{margin:.2f}",
                # new optional columns (your UI toggles will read these):
                "hours_total": f"{vals['hours']:.2f}",
                "labor_cost_total": f"{vals['labor_cost']:.2f}",
            }
        )

    # Sort by profit desc
    out.sort(key=lambda r: float(r["profit"]), reverse=True)

    return {
        "rows": out,
        "start": dt_start.isoformat(),
        "end": dt_end.isoformat(),
    }
