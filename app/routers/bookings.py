from __future__ import annotations
import os
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from dateutil import parser as dateparser
from googleapiclient.errors import HttpError

from app.services.google_calendar import ensure_service, create_event
from app.services.sms import send_sms
from app import storage, config

router = APIRouter(tags=["booking"])

class BookIn(BaseModel):
    # ISO8601 start (e.g. "2025-09-17T14:00:00-04:00" or "2025-09-17T18:00:00Z")
    start: str
    # Either provide 'end' or we'll use duration_minutes (default = SLOT_MINUTES or 60)
    end: str | None = None
    duration_minutes: int | None = None

    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    notes: str | None = None

class BookOut(BaseModel):
    ok: bool
    event_id: str | None = None
    html_link: str | None = None
    sms_sent: bool = False

@router.post("/book", response_model=BookOut)
def book(payload: BookIn):
    tz_str = os.getenv("TZ", "America/New_York")
    cal_id = [c.strip() for c in os.getenv("GOOGLE_CALENDAR_IDS", "primary").split(",") if c.strip()][0]

    # parse start/end
    try:
        start_dt = dateparser.isoparse(payload.start)
    except Exception:
        raise HTTPException(400, "Invalid 'start' datetime (use ISO8601)")

    if payload.end:
        try:
            end_dt = dateparser.isoparse(payload.end)
        except Exception:
            raise HTTPException(400, "Invalid 'end' datetime (use ISO8601)")
    else:
        dur = payload.duration_minutes or int(os.getenv("SLOT_MINUTES", "60"))
        end_dt = start_dt + timedelta(minutes=dur)

    # google service
    try:
        svc, _ = ensure_service()
    except PermissionError:
        raise HTTPException(401, "Not authorized with Google. Visit /oauth/google/start")

    # create calendar event
    summary = f"Service appointment — {config.FROM_NAME}"
    desc = payload.notes or ""
    try:
        ev = create_event(
            svc,
            calendar_id=cal_id,
            summary=summary,
            description=desc,
            start_dt=start_dt,
            end_dt=end_dt,
            tz_str=tz_str,
            attendee_email=(str(payload.email) if payload.email else None),
            attendee_name=payload.name,
        )
    except HttpError as e:
        # common if GOOGLE_SCOPES lacks full calendar scope
        raise HTTPException(403, f"Google Calendar insert failed: {e}")

    # optional SMS confirmation
    sms_ok = False
    if payload.phone:
        z = ZoneInfo(tz_str)
        s_local = (start_dt if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc)).astimezone(z)
        pretty = s_local.strftime("%I:%M %p on %a %b %d").lstrip("0")
        link = ev.get("htmlLink") or ""
        body = f"You're booked with {config.FROM_NAME} at {pretty}. Details: {link}"
        sms_ok = send_sms(payload.phone, body)

    # log as a booking row (source=api)
    from datetime import timezone as _tz
    storage.save_booking(
        event_id=ev.get("id", ""),
        invitee_name=payload.name or "",
        invitee_email=str(payload.email or ""),
        invitee_phone=payload.phone or "",
        start_time=start_dt.astimezone(_tz.utc).isoformat().replace("+00:00", "Z"),
        end_time=end_dt.astimezone(_tz.utc).isoformat().replace("+00:00", "Z"),
        tz_str=tz_str,
        notes=payload.notes or "",
        sms_sent=sms_ok,
        source="api",
    )

    return BookOut(ok=True, event_id=ev.get("id"), html_link=ev.get("htmlLink"), sms_sent=sms_ok)
