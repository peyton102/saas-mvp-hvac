# app/routers/bookings.py
from datetime import datetime, timedelta, time
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, EmailStr
from sqlmodel import Session

from app import config, storage
from app.utils.phone import normalize_us_phone
from app.services import google_calendar as gcal
from app.services.sms import send_sms
from app.db import get_session
from app.models import Booking as BookingModel

router = APIRouter(prefix="", tags=["booking"])


# ===== Schemas =====
class BookIn(BaseModel):
    start: str  # ISO8601 (e.g. 2025-09-19T09:00:00-04:00)
    end: str    # ISO8601
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class BookOut(BaseModel):
    ok: bool
    event_id: Optional[str] = None
    sms_sent: Optional[bool] = None


# ===== Helpers =====
def _parse_dt(val: str) -> datetime:
    from dateutil import parser as dtparse
    try:
        return dtparse.isoparse(val)
    except Exception:
        # Fallback: allow Z → +00:00
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(status_code=422, detail=f"Invalid datetime: {val}")


def _gcal_is_free(start: datetime, end: datetime) -> bool:
    """
    Ask Google if range is free; fall back to permissive if helper not available.
    """
    try:
        fb = gcal.freebusy(start, end)
        if isinstance(fb, dict):
            busy = fb.get("busy") or []
            return len(busy) == 0
        if isinstance(fb, list):
            return len(fb) == 0
    except Exception:
        pass
    for attr in ("is_free", "is_range_free", "is_time_free"):
        fn = getattr(gcal, attr, None)
        if callable(fn):
            try:
                return bool(fn(start, end))
            except Exception:
                continue
    return True


def _gcal_create_event(start: datetime, end: datetime, name: str, email: Optional[str], phone: Optional[str], notes: Optional[str]) -> str:
    """
    Call google_calendar.create_event(svc, calendar_id=..., summary=..., description=..., start_dt=..., end_dt=..., tz_str=...)
    Your helper requires the first positional arg 'svc' (the Google Calendar service).
    """
    summary = f"Estimate: {name}"
    description = (
        f"Name: {name}\nPhone: {phone or ''}\nEmail: {email or ''}\nNotes: {notes or ''}"
    ).strip()

    # calendar + tz from env
    try:
        cal_ids = getattr(config, "GOOGLE_CALENDAR_IDS", "primary")
        calendar_id = (cal_ids.split(",")[0] or "primary").strip()
    except Exception:
        calendar_id = "primary"
    tz_str = getattr(config, "TZ", "America/New_York")

    # --- acquire Google service (try common builder names) ---
    svc = None
    for attr in ("get_service", "get_calendar_service", "build_service", "service"):
        obj = getattr(gcal, attr, None)
        try:
            if callable(obj):
                svc = obj()
            elif obj is not None:
                svc = obj
        except Exception as e:
            print(f"[GCAL SERVICE {attr} ERROR] {e!r}")
        if svc:
            break
    if svc is None:
        raise HTTPException(status_code=502, detail="calendar service unavailable (no get_service/build_service)")

    # --- create event using required kwargs (no attendees, per your helper) ---
    try:
        ev = gcal.create_event(
            svc,
            calendar_id=calendar_id,
            summary=summary,
            description=description,
            start_dt=start,
            end_dt=end,
            tz_str=tz_str,
        )
    except Exception as e:
        print(f"[GCAL CREATE_EVENT ERROR] {e!r}")
        raise HTTPException(status_code=502, detail=f"calendar.create_event failed: {e}")

    # normalize return
    if isinstance(ev, dict):
        return ev.get("id") or ev.get("event_id") or ev.get("event", {}).get("id") or ""
    if isinstance(ev, str):
        return ev
    return ""  # OK if helper returns None


# ===== Availability =====
@router.get("/availability")
def availability(days: int = Query(7, ge=1, le=14)):
    """Simple availability using BUSINESS_HOURS & SLOT_MINUTES, filtered by Google free/busy."""
    try:
        bh = getattr(config, "BUSINESS_HOURS", "09:00-17:00")
        slot_min = int(getattr(config, "SLOT_MINUTES", 60))
        buf_min = int(getattr(config, "SLOT_BUFFER_MINUTES", 0))
    except Exception:
        bh, slot_min, buf_min = "09:00-17:00", 60, 0

    try:
        start_s, end_s = bh.split("-")
        start_t = time.fromisoformat(start_s)
        end_t = time.fromisoformat(end_s)
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid BUSINESS_HOURS format")

    now = datetime.now().astimezone()
    out: List[str] = []
    step = timedelta(minutes=slot_min + buf_min)

    for d in range(days):
        day = (now + timedelta(days=d)).date()
        cursor = datetime.combine(day, start_t, tzinfo=now.tzinfo)
        end_of_day = datetime.combine(day, end_t, tzinfo=now.tzinfo)
        while cursor + timedelta(minutes=slot_min) <= end_of_day:
            slot_start = cursor
            slot_end = cursor + timedelta(minutes=slot_min)
            if _gcal_is_free(slot_start, slot_end):
                out.append(slot_start.isoformat())
            cursor += step

    return {"slots": out}


# ===== Direct Booking =====
@router.post("/book", response_model=BookOut)
def book(payload: BookIn, session: Session = Depends(get_session)):
    """
    Validate slot against Google Calendar; on success create event, log CSV, SMS confirm,
    and dual-write to DB. Returns 409 if conflict.
    """
    start = _parse_dt(payload.start)
    end = _parse_dt(payload.end)
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")

    # check availability
    if not _gcal_is_free(start, end):
        raise HTTPException(status_code=409, detail="Time slot is not available")

    # create event
    event_id = _gcal_create_event(start, end, payload.name, payload.email, payload.phone, payload.notes)

    # SMS confirmation (honors SMS_DRY_RUN)
    e164 = normalize_us_phone(payload.phone) if payload.phone else ""
    sms_ok = False
    if e164:
        msg = (
            f"You're booked with {config.FROM_NAME}. "
            f"Start: {start.isoformat()}. To reschedule: {config.BOOKING_LINK}"
        )
        try:
            sms_ok = send_sms(e164, msg)
        except Exception as e:
            print(f"[BOOK SMS ERROR] {e}")

    # CSV log (preserve existing behavior)
    try:
        if hasattr(storage, "save_booking"):
            tz_str = getattr(config, "TZ", "America/New_York")
            storage.save_booking(
                event_id=event_id,
                invitee_name=payload.name,
                invitee_email=(payload.email or ""),
                invitee_phone=e164,
                start_time=start.isoformat(),
                end_time=end.isoformat(),
                tz_str=tz_str,
                notes=(payload.notes or ""),
                sms_sent=bool(sms_ok),
                source="api",
            )
    except Exception as e:
        print(f"[BOOK CSV LOG ERROR] {e}")

    # DB write
    session.add(BookingModel(
        name=payload.name or "",
        phone=e164 or "",
        email=(payload.email or None),
        start=start,
        end=end,
        notes=(payload.notes or None),
        source="api",
    ))
    session.commit()

    return BookOut(ok=True, event_id=event_id or None, sms_sent=bool(sms_ok))
