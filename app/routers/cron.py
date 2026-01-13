# app/routers/cron.py
from fastapi import APIRouter, Header, HTTPException
from app import config
from app.services.reminders import run_booking_reminders  # <-- whatever your real function is

router = APIRouter(prefix="/cron", tags=["cron"])

@router.post("/reminders/run")
async def cron_run_reminders(x_admin_key: str | None = Header(None)):
    if x_admin_key != getattr(config.settings, "ADMIN_KEY", None):
        raise HTTPException(status_code=401, detail="Unauthorized")
    sent = await run_booking_reminders()  # returns count or dict
    return {"ok": True, "sent": sent}
