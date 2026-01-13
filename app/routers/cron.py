# app/routers/cron.py
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlmodel import Session

from app.db import get_session
from app.routers.reminders import send_reminders_all

router = APIRouter(prefix="/cron", tags=["cron"])

@router.post("/reminders/run")
def cron_reminders_run(
    x_admin_key: str | None = Header(None),
    look_back_minutes: int = Query(60, ge=1, le=720),
    session: Session = Depends(get_session),
):
    if x_admin_key != (getattr(__import__("app.config", fromlist=["ADMIN_KEY"]), "ADMIN_KEY", None) or "supersecret123"):
        raise HTTPException(status_code=401, detail="bad admin key")

    return send_reminders_all(look_back_minutes=look_back_minutes, session=session)
