# app/routers/cron.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text
from sqlmodel import Session, select
from app.db import get_session
from app.models import Tenant
from app.routers.reminders import send_reminders_all
from app.services.lead_nudges import send_lead_nudges_all
from app.services.email import send_monthly_summary_email
from app import config

router = APIRouter(prefix="/cron", tags=["cron"])


def _require_admin_key(x_admin_key: str | None) -> None:
    expected = (getattr(config, "ADMIN_KEY", "") or "").strip()
    got = (x_admin_key or "").strip()
    if not expected:
        raise HTTPException(status_code=500, detail="Server misconfigured: ADMIN_KEY not set")
    if got != expected:
        raise HTTPException(status_code=401, detail="Unauthorized: missing or invalid admin key")
@router.get("/debug/admin-key")
def debug_admin_key():
    v = (getattr(config, "ADMIN_KEY", "") or "").strip()
    return {"has_admin_key": bool(v), "len": len(v)}
@router.post("/lead-nudges/run")
def cron_lead_nudges_run(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    hours_old: float = Query(2.0, ge=0.5, le=48.0, description="Nudge leads stale for this many hours"),
    session: Session = Depends(get_session),
):
    """
    Send follow-up nudge SMS to customers whose lead is still 'new' after
    `hours_old` hours. Safe to run on a schedule — each lead is only ever
    nudged once (nudge_sent_at stamp prevents repeats).
    """
    _require_admin_key(x_admin_key)
    return send_lead_nudges_all(hours_old=hours_old, session=session)


@router.post("/reminders/run")
def cron_reminders_run(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    look_back_minutes: int = Query(60, ge=1, le=720),
    session: Session = Depends(get_session),
):
    _require_admin_key(x_admin_key)
    reminders_result = send_reminders_all(look_back_minutes=look_back_minutes, session=session)

    # Also flush any queued review SMSes (review-queue template, sms_sent=False)
    from app.routers.bookings import run_review_reminders
    review_result = run_review_reminders(session=session)

    return {"reminders": reminders_result, "review_queue": review_result}


@router.post("/gcal-sync")
def cron_gcal_sync(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    session: Session = Depends(get_session),
):
    """
    Import new Google Calendar events as Torevez bookings for all connected tenants.
    Safe to call every 5 minutes. Uses incremental sync tokens — only fetches changes.
    Protected by X-Admin-Key header.
    """
    from app.services.google_calendar import sync_new_bookings

    _require_admin_key(x_admin_key)

    tenants = session.exec(
        select(Tenant)
        .where(Tenant.gcal_refresh_token.isnot(None))
        .where(Tenant.is_active == True)
    ).all()

    results = []
    for tenant in tenants:
        r = sync_new_bookings(tenant, session)
        results.append({
            "tenant": tenant.slug,
            "imported": r["imported"],
            "skipped": r["skipped"],
            "errors": r["errors"],
        })
        if r["errors"]:
            print(f"[GCAL SYNC] Errors for '{tenant.slug}': {r['errors']}")

    return {"ok": True, "tenants_synced": len(results), "results": results}


@router.post("/gcal-reset")
def cron_gcal_reset(
    tenant_slug: str = Query(..., description="Tenant slug to reset"),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    session: Session = Depends(get_session),
):
    """
    Reset Google Calendar sync state for one tenant:
    - Clears gcal_sync_token and gcal_last_synced_at
    - Deletes all bookings with source='google_calendar' for this tenant
    Use before testing to start completely fresh. After this, re-run
    /oauth/google/start?tenant=<slug> to establish a new sync baseline.
    """
    from app.models import Booking as BookingModel

    _require_admin_key(x_admin_key)

    tenant = session.exec(select(Tenant).where(Tenant.slug == tenant_slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_slug}' not found")

    tenant.gcal_sync_token = None
    tenant.gcal_last_synced_at = None
    session.add(tenant)

    gcal_bookings = session.exec(
        select(BookingModel)
        .where(BookingModel.tenant_id == tenant_slug)
        .where(BookingModel.source == "google_calendar")
    ).all()
    deleted = len(gcal_bookings)
    for b in gcal_bookings:
        session.delete(b)

    session.commit()

    return {
        "ok": True,
        "tenant": tenant_slug,
        "sync_token_cleared": True,
        "bookings_deleted": deleted,
        "next_step": f"Re-run /oauth/google/start?tenant={tenant_slug} to set a new baseline.",
    }


@router.post("/monthly-summary")
def cron_monthly_summary(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    session: Session = Depends(get_session),
):
    """
    Send monthly summary emails to all active tenants.
    Run on the 1st of each month via Render cron job.
    """
    _require_admin_key(x_admin_key)

    now = datetime.now(timezone.utc)
    # Use previous month's stats if run on the 1st
    if now.month == 1:
        year, month = now.year - 1, 12
    else:
        year, month = now.year, now.month - 1

    month_start = datetime(year, month, 1, tzinfo=timezone.utc).isoformat()
    if month == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc).isoformat()
    else:
        month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc).isoformat()

    from calendar import month_name
    month_label = f"{month_name[month]} {year}"
    portal_url = getattr(config, "PORTAL_URL", "https://saas-mvp-hvac-1.onrender.com")

    tenants = session.exec(select(Tenant).where(Tenant.is_active == True)).all()

    sent = 0
    errors = 0
    for t in tenants:
        if not t.email:
            continue
        try:
            leads = session.exec(text("""
                SELECT COUNT(*) FROM lead
                WHERE tenant_id = :tid AND created_at >= :s AND created_at < :e
            """).bindparams(tid=t.slug, s=month_start, e=month_end)).scalar() or 0

            bookings = session.exec(text("""
                SELECT COUNT(*) FROM booking
                WHERE tenant_id = :tid AND created_at >= :s AND created_at < :e
            """).bindparams(tid=t.slug, s=month_start, e=month_end)).scalar() or 0

            won_row = session.exec(text("""
                SELECT COUNT(*), COALESCE(SUM(job_value), 0) FROM booking
                WHERE tenant_id = :tid AND completed_at IS NOT NULL AND job_value > 0
                AND completed_at >= :s AND completed_at < :e
            """).bindparams(tid=t.slug, s=month_start, e=month_end)).first()

            missed = session.exec(text("""
                SELECT COUNT(*) FROM lead
                WHERE tenant_id = :tid AND source = 'missed_call'
                AND created_at >= :s AND created_at < :e
            """).bindparams(tid=t.slug, s=month_start, e=month_end)).scalar() or 0

            stats = {
                "month": month_label,
                "leads_captured": int(leads),
                "bookings_made": int(bookings),
                "jobs_won": int(won_row[0]) if won_row else 0,
                "revenue_this_month": float(won_row[1]) if won_row else 0.0,
                "missed_calls_answered": int(missed),
            }
            ok = send_monthly_summary_email(t.email, t.business_name or t.slug, stats, portal_url)
            if ok:
                sent += 1
            else:
                errors += 1
        except Exception as exc:
            print(f"[MONTHLY SUMMARY] error for {t.slug}: {exc}")
            errors += 1

    return {"ok": True, "month": month_label, "sent": sent, "errors": errors}
