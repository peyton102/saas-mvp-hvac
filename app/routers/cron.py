# app/routers/cron.py
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlmodel import Session, select
from app.db import get_session
from app.models import Tenant
from app.routers.reminders import send_reminders_all
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
@router.post("/reminders/run")
def cron_reminders_run(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    look_back_minutes: int = Query(60, ge=1, le=720),
    session: Session = Depends(get_session),
):
    _require_admin_key(x_admin_key)
    return send_reminders_all(look_back_minutes=look_back_minutes, session=session)


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
