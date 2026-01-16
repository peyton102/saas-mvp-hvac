# app/routers/cron.py
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlmodel import Session
from app.db import get_session
from app.routers.reminders import send_reminders_all
from app import config

router = APIRouter(prefix="/cron", tags=["cron"])
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
    expected = (getattr(config, "ADMIN_KEY", "") or "").strip()
    got = (x_admin_key or "").strip()

    if not expected:
        raise HTTPException(status_code=500, detail="Server misconfigured: ADMIN_KEY not set")
    if got != expected:
        raise HTTPException(status_code=401, detail="Unauthorized: missing or invalid admin key")

    return send_reminders_all(look_back_minutes=look_back_minutes, session=session)
