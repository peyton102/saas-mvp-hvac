# app/routers/finance.py
from fastapi import APIRouter, Depends, Query, HTTPException
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from sqlmodel import Session, select

from app.db import get_session
from app.deps import get_tenant_id
from app.models_finance import Revenue, Cost

router = APIRouter(prefix="/finance", tags=["finance"])

FIN_VER = "pnl-eod-2"  # <-- version tag to verify reload

@router.get("/_ver")
def _ver():
    return {"finance_router_version": FIN_VER}

# ---------- helpers ----------
def _dec(val) -> Decimal:
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

def _range(range_key: str):
    now = datetime.now(tz=timezone.utc)
    if range_key == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_key == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # month default
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now

def _to_dt_utc(s: str, *, is_end: bool = False) -> datetime:
    s = (s or "").strip().replace("Z", "+00:00")
    if not s:
        raise ValueError("empty datetime")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        if len(s) == 10 and s.count("-") == 2:  # YYYY-MM-DD
            dt = datetime.fromisoformat(s + "T00:00:00")
            if is_end:
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt

# ---------- endpoints ----------
@router.post("/revenue")
def add_revenue(payload: dict,
                tenant_id: str = Depends(get_tenant_id),
                session: Session = Depends(get_session)):
    r = Revenue(
        tenant_id=tenant_id,
        amount=_dec(payload.get("amount")),
        source=(payload.get("source") or "unknown"),
        booking_id=payload.get("booking_id"),
        lead_id=payload.get("lead_id"),
        notes=payload.get("notes"),
    )
    session.add(r); session.commit(); session.refresh(r)
    return {"ok": True, "id": r.id}

@router.post("/cost")
def add_cost(payload: dict,
             tenant_id: str = Depends(get_tenant_id),
             session: Session = Depends(get_session)):
    c = Cost(
        tenant_id=tenant_id,
        amount=_dec(payload.get("amount")),
        category=(payload.get("category") or "general"),
        vendor=payload.get("vendor"),
        notes=payload.get("notes"),
    )
    session.add(c); session.commit(); session.refresh(c)
    return {"ok": True, "id": c.id}

@router.get("/summary")
def summary(range: str = Query("month", pattern="^(today|week|month)$"),
            tenant_id: str = Depends(get_tenant_id),
            session: Session = Depends(get_session)):
    start, end = _range(range)
    rev = session.exec(
        select(Revenue).where(
            Revenue.tenant_id == tenant_id,
            Revenue.created_at >= start,
            Revenue.created_at <= end
        )
    ).all()
    cost = session.exec(
        select(Cost).where(
            Cost.tenant_id == tenant_id,
            Cost.created_at >= start,
            Cost.created_at <= end
        )
    ).all()

    rev_total = sum((x.amount for x in rev), Decimal("0"))
    cost_total = sum((x.amount for x in cost), Decimal("0"))
    gross = rev_total - cost_total
    margin = (gross / rev_total * Decimal("100")) if rev_total else Decimal("0")

    by_source = {}
    for x in rev:
        k = x.source or "unknown"
        by_source[k] = by_source.get(k, Decimal("0")) + x.amount

    return {
        "range": range,
        "revenue_total": str(rev_total),
        "cost_total": str(cost_total),
        "gross_profit": str(gross),
        "margin_pct": str(margin.quantize(Decimal("0.01"))),
        "by_source": {k: str(v) for k, v in by_source.items()},
    }

@router.get("/pnl")
def pnl(start: str, end: str,
        tenant_id: str = Depends(get_tenant_id),
        session: Session = Depends(get_session)):
    try:
        s = _to_dt_utc(start, is_end=False)
        e = _to_dt_utc(end,   is_end=True)   # <-- end-of-day for date-only
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Invalid datetime. Use ISO like '2025-09-26T00:00:00' ({ex})")

    if e < s:
        raise HTTPException(status_code=400, detail="end must be >= start")

    rev = session.exec(
        select(Revenue).where(
            Revenue.tenant_id == tenant_id,
            Revenue.created_at >= s,
            Revenue.created_at <= e
        )
    ).all()
    cost = session.exec(
        select(Cost).where(
            Cost.tenant_id == tenant_id,
            Cost.created_at >= s,
            Cost.created_at <= e
        )
    ).all()

    rev_total = sum((x.amount for x in rev), Decimal("0"))
    cost_total = sum((x.amount for x in cost), Decimal("0"))
    gross = rev_total - cost_total
    margin = (gross / rev_total * Decimal("100")) if rev_total else Decimal("0")

    return {
        "start": s.isoformat(),
        "end": e.isoformat(),
        "revenue_total": str(rev_total),
        "cost_total": str(cost_total),
        "gross_profit": str(gross),
        "margin_pct": str(margin.quantize(Decimal("0.01"))),
    }
@router.get("/pnl_day")
def pnl_day(date: str,
            tenant_id: str = Depends(get_tenant_id),
            session: Session = Depends(get_session)):
    # Accepts YYYY-MM-DD and expands to the full day
    if len(date) != 10 or date.count("-") != 2:
        raise HTTPException(status_code=400, detail="Use date=YYYY-MM-DD")

    start = f"{date}T00:00:00"
    end   = f"{date}T23:59:59"
    # Reuse existing /pnl logic by calling the function directly
    return pnl(start=start, end=end, tenant_id=tenant_id, session=session)  # type: ignore

@router.get("/attribution")
def attribution(by: str = Query("source", pattern="^(source)$"),
                range: str = Query("month", pattern="^(today|week|month)$"),
                tenant_id: str = Depends(get_tenant_id),
                session: Session = Depends(get_session)):
    start, end = _range(range)
    rev = session.exec(
        select(Revenue).where(
            Revenue.tenant_id == tenant_id,
            Revenue.created_at >= start,
            Revenue.created_at <= end
        )
    ).all()
    buckets = {}
    for r in rev:
        key = (r.source or "unknown")
        buckets[key] = buckets.get(key, Decimal("0")) + r.amount
    return {"by": by, "range": range, "buckets": {k: str(v) for k, v in buckets.items()}}
