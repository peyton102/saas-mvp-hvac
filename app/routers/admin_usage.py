# app/routers/admin_usage.py
"""
Admin-only endpoint: per-tenant usage aggregates.
Returns counts only — no customer PII (names/phones/emails).
Used to verify tenant value before billing ("don't pay until you've made money").
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlmodel import Session, select

from app.db import get_session
from app.models import Lead, Booking, Review, ReminderSent, Tenant
from app.routers.auth import get_current_user

router = APIRouter(prefix="/admin/usage", tags=["admin-usage"])


def _require_admin(current_user: Dict[str, Any], session: Session) -> None:
    from fastapi import HTTPException
    slug = current_user.get("tenant_slug") or current_user.get("tenant")
    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant or not tenant.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")


class TenantUsage(BaseModel):
    slug: str
    business_name: str
    email: str
    joined: Optional[str]

    # Missed call assistant — the headline metric
    missed_call_leads_30d: int
    missed_call_leads_total: int

    # Other feature usage (30-day window)
    bookings_30d: int
    bookings_total: int
    review_requests_30d: int
    reminders_30d: int

    # Job won tracking
    jobs_won_30d: int
    revenue_attributed_30d: float

    # Activity signal
    last_active: Optional[str]   # ISO string of most recent record across all tables


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@router.get("", response_model=List[TenantUsage])
def get_usage(
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user, session)

    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)

    tenants = session.exec(
        select(Tenant).where(Tenant.is_admin == False)  # noqa: E712
    ).all()

    results: List[TenantUsage] = []

    for t in tenants:
        slug = t.slug

        # ---- missed call leads (source = 'vapi' OR 'missed_call') ----
        mc_filter = Lead.tenant_id == slug, Lead.source.in_(["vapi", "missed_call"])
        mc_30d = session.exec(
            select(func.count(Lead.id)).where(*mc_filter, Lead.created_at >= cutoff_30d)
        ).one()
        mc_total = session.exec(
            select(func.count(Lead.id)).where(*mc_filter)
        ).one()

        # ---- bookings ----
        bk_30d = session.exec(
            select(func.count(Booking.id)).where(
                Booking.tenant_id == slug, Booking.created_at >= cutoff_30d
            )
        ).one()
        bk_total = session.exec(
            select(func.count(Booking.id)).where(Booking.tenant_id == slug)
        ).one()

        # ---- review requests ----
        rv_30d = session.exec(
            select(func.count(Review.id)).where(
                Review.tenant_id == slug, Review.created_at >= cutoff_30d
            )
        ).one()

        # ---- reminders ----
        rm_30d = session.exec(
            select(func.count(ReminderSent.id)).where(
                ReminderSent.tenant_id == slug, ReminderSent.created_at >= cutoff_30d
            )
        ).one()

        # ---- jobs won (30d) — leads marked won ----
        jobs_won_30d = session.exec(
            select(func.count(Lead.id)).where(
                Lead.tenant_id == slug,
                Lead.job_won == True,  # noqa: E712
                Lead.created_at >= cutoff_30d,
            )
        ).one() or 0

        lead_rev_30d = session.exec(
            select(func.coalesce(func.sum(Lead.job_value), 0)).where(
                Lead.tenant_id == slug,
                Lead.job_won == True,  # noqa: E712
                Lead.created_at >= cutoff_30d,
            )
        ).one() or 0.0

        # ---- booking revenue (30d) — completed bookings with job_value ----
        booking_rev_30d = session.exec(
            select(func.coalesce(func.sum(Booking.job_value), 0)).where(
                Booking.tenant_id == slug,
                Booking.job_value.isnot(None),
                Booking.created_at >= cutoff_30d,
                Booking.completed_at.isnot(None),
            )
        ).one() or 0.0

        revenue_30d = float(lead_rev_30d) + float(booking_rev_30d)

        # ---- last active: latest created_at across all four tables ----
        candidates: List[Optional[datetime]] = []

        row = session.exec(
            select(func.max(Lead.created_at)).where(Lead.tenant_id == slug)
        ).one()
        candidates.append(row)

        row = session.exec(
            select(func.max(Booking.created_at)).where(Booking.tenant_id == slug)
        ).one()
        candidates.append(row)

        row = session.exec(
            select(func.max(Review.created_at)).where(Review.tenant_id == slug)
        ).one()
        candidates.append(row)

        row = session.exec(
            select(func.max(ReminderSent.created_at)).where(ReminderSent.tenant_id == slug)
        ).one()
        candidates.append(row)

        valid = [c for c in candidates if c is not None]
        last_active = max(valid) if valid else None

        results.append(TenantUsage(
            slug=slug,
            business_name=t.business_name or t.name or slug,
            email=t.email or "",
            joined=_iso(t.created_at),
            missed_call_leads_30d=mc_30d or 0,
            missed_call_leads_total=mc_total or 0,
            bookings_30d=bk_30d or 0,
            bookings_total=bk_total or 0,
            review_requests_30d=rv_30d or 0,
            reminders_30d=rm_30d or 0,
            jobs_won_30d=jobs_won_30d,
            revenue_attributed_30d=float(revenue_30d),
            last_active=_iso(last_active),
        ))

    # Sort: most missed-call captures (30d) first, then total, then name
    results.sort(key=lambda r: (-r.missed_call_leads_30d, -r.missed_call_leads_total, r.business_name.lower()))
    return results
