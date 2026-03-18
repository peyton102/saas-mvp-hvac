# app/routers/bookings.py
from datetime import datetime, timedelta, time, timezone
from typing import Optional, List

from dateutil import parser as dtparse

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select
from zoneinfo import ZoneInfo  # 👈 add this

from app import config, storage
from app.db import get_session
from app.deps import get_tenant_id
from app.models import Booking as BookingModel, ReminderSent
from app.routers.tenant import get_tenant_tz

from app.services import google_calendar as gcal
from app.services.sms import (
    booking_confirmation_sms,
    booking_office_notify_sms,
    booking_reminder_sms,
)
from app.services.email import send_booking_confirmation
from app.utils.phone import normalize_us_phone

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
    email_sent: Optional[bool] = None


# ===== Helpers =====
def _parse_dt(val: str) -> datetime:
    """
    Parse ISO string from the portal.

    - If it has a timezone (Z or offset), keep it.
    - If it's naive (no timezone), treat it as config.TZ (e.g. America/New_York).
    """
    try:
        dt = dtparse.isoparse(val)
    except Exception:
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(status_code=422, detail=f"Invalid datetime: {val}")

    if dt.tzinfo is None:
        tz = ZoneInfo(getattr(config, "TZ", "America/New_York"))
        dt = dt.replace(tzinfo=tz)

    return dt


def _gcal_create_event(
    start: datetime,
    end: datetime,
    name: str,
    email: Optional[str],
    phone: Optional[str],
    notes: Optional[str],
) -> str:
    """
    Call google_calendar.create_event(svc, calendar_id=..., summary=..., description=..., start_dt=..., end_dt=..., tz_str=...)
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
        print("[GCAL] No calendar service configured – skipping calendar event.")
        return ""

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
        print(f"[GCAL CREATE_EVENT ERROR] {e!r}  (continuing without calendar event)")
        return ""

    if isinstance(ev, dict):
        return ev.get("id") or ev.get("event_id") or ev.get("event", {}).get("id") or ""
    if isinstance(ev, str):
        return ev
    return ""


# ===== Availability =====
@router.get("/availability", operation_id="bookings_availability_get")
def availability(
    days: int = Query(7, ge=1, le=14),
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return open slots based on BUSINESS_HOURS & SLOT_MINUTES, filtered by existing DB bookings."""
    try:
        bh = getattr(config, "BUSINESS_HOURS", "09:00-17:00")
        slot_min = int(getattr(config, "SLOT_MINUTES", 60))
        buf_min = int(getattr(config, "SLOT_BUFFER_MINUTES", 0))
    except Exception:
        bh, slot_min, buf_min = "09:00-17:00", 60, 0

    try:
        start_str, end_str = bh.split("-")
        start_t = time.fromisoformat(start_str)
        end_t = time.fromisoformat(end_str)
    except Exception:
        start_t = time(9, 0)
        end_t = time(17, 0)

    tenant_tz = get_tenant_tz(tenant_id, session)
    now_tz = datetime.now(tenant_tz)
    now_utc = datetime.now(timezone.utc)
    window_end = now_utc + timedelta(days=days)

    # Bookings are stored as UTC-naive — strip tz for comparison
    now_naive = now_utc.replace(tzinfo=None)
    window_end_naive = window_end.replace(tzinfo=None)
    existing = session.exec(
        select(BookingModel)
        .where(BookingModel.tenant_id == tenant_id)
        .where(BookingModel.end > now_naive)
        .where(BookingModel.start < window_end_naive)
    ).all()

    out: List[str] = []
    step = timedelta(minutes=slot_min + buf_min)

    for d in range(days):
        day = (now_tz + timedelta(days=d)).date()
        cursor = datetime.combine(day, start_t, tzinfo=tenant_tz)
        end_of_day = datetime.combine(day, end_t, tzinfo=tenant_tz)
        while cursor + timedelta(minutes=slot_min) <= end_of_day:
            slot_start = cursor
            slot_end = cursor + timedelta(minutes=slot_min)
            if slot_start < now_tz:
                cursor += step
                continue
            s = slot_start.astimezone(timezone.utc).replace(tzinfo=None)
            e = slot_end.astimezone(timezone.utc).replace(tzinfo=None)
            conflict = any(not (e <= b.start or s >= b.end) for b in existing)
            if not conflict:
                out.append(slot_start.isoformat())
            cursor += step

    return {"slots": out}


@router.get("/public/availability", operation_id="public_bookings_availability_get")
def public_availability(
    days: int = Query(7, ge=1, le=14),
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    return availability(days, session, tenant_id)


# ===== Upcoming Bookings (per-tenant) =====
@router.get("/upcoming")
def list_upcoming_bookings(
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Return ALL bookings for this tenant.
    Frontend controls hiding: past, completed, incomplete.
    """
    rows = session.exec(
        select(BookingModel)
        .where(BookingModel.tenant_id == tenant_id)
        .order_by(BookingModel.start.asc())
    ).all()

    tenant_tz = get_tenant_tz(tenant_id, session)

    def _to_tenant_tz(dt):
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tenant_tz).isoformat(timespec="seconds")

    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "tenant_id": r.tenant_id,
            "name": r.name,
            "email": r.email,
            "phone": r.phone,
            "notes": r.notes,
            "source": r.source,
            "start": _to_tenant_tz(r.start),
            "end": _to_tenant_tz(r.end),
            "created_at": _to_tenant_tz(getattr(r, "created_at", None)),
            "completed_at": _to_tenant_tz(getattr(r, "completed_at", None)),
        })

    return out


# ===== Direct Booking (per-tenant) =====
@router.post("/book", response_model=BookOut)
def book(
    request: Request,
    payload: BookIn,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    start_local = _parse_dt(payload.start)
    end_local = _parse_dt(payload.end)

    if end_local <= start_local:
        raise HTTPException(status_code=422, detail="end must be after start")

    # Store as UTC-naive to match availability query comparisons
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)

    # Check DB for overlapping bookings (stored as UTC-naive)
    conflict = session.exec(
        select(BookingModel)
        .where(BookingModel.tenant_id == tenant_id)
        .where(BookingModel.start < end_utc)
        .where(BookingModel.end > start_utc)
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="Time slot is not available")

    event_id = _gcal_create_event(
        start_local, end_local, payload.name, payload.email, payload.phone, payload.notes
    )

    e164 = normalize_us_phone(payload.phone) if payload.phone else ""
    sms_ok = False
    if e164:
        try:
            sms_ok = booking_confirmation_sms(
                tenant_id,
                {
                    "name": payload.name,
                    "phone": e164,
                    "service": "appointment",
                    "starts_at_iso": start_local.isoformat(),

                },
            )
        except Exception as e:
            print(f"[BOOK SMS ERROR] {e}")

    # CSV log (preserve existing behavior only when DB_FIRST is false)
    try:
        if (not getattr(config, "DB_FIRST", True)) and hasattr(storage, "save_booking"):
            tz_str=str(start_local.tzinfo or ""),
            storage.save_booking(
                event_id=event_id,
                invitee_name=payload.name,
                invitee_email=(payload.email or ""),
                invitee_phone=e164,
                start_time=start_local.isoformat(),
                end_time=end_local.isoformat(),
                tz_str=tz_str,
                notes=(payload.notes or ""),
                sms_sent=bool(sms_ok),
                source="api",
            )
    except Exception as e:
        print(f"[BOOK CSV LOG ERROR] {e}")

    # DB write (per-tenant)
    session.add(
        BookingModel(
            tenant_id=tenant_id,
            name=payload.name or "",
            phone=e164 or "",
            email=(payload.email or None),
            start=start_utc,
            end=end_utc,

            notes=(payload.notes or None),
            source="api",
        )
    )
    session.commit()

    # Office SMS notify
    try:
        office_payload = {
            "name": payload.name,
            "phone": e164 or (payload.phone or ""),
            "service": "appointment",
            "starts_at_iso": start_local.isoformat(),
        }
        booking_office_notify_sms(tenant_id, office_payload)
    except Exception as e:
        print(f"[BOOK OFFICE SMS ERROR] {e}")

    # ===== Booking confirmation EMAIL (office + customer) =====
    email_ok = False
    try:
        email_payload = {
            "name": payload.name,
            "email": (payload.email or "").strip(),
            "phone": e164 or (payload.phone or ""),
            "address": "",
            "service": "appointment",
            "starts_at_iso": start_local.isoformat(),
            "reschedule_url": getattr(config, "BOOKING_LINK", "") or "",
        }
        email_ok = send_booking_confirmation(tenant_id, email_payload)
    except Exception as e:
        print(f"[BOOK EMAIL ERROR] {e}")

    return BookOut(
        ok=True,
        event_id=event_id,
        sms_sent=bool(sms_ok),
        email_sent=bool(email_ok),
    )


# ===== Debug endpoint: tenant-aware =====
@router.get("/upcoming/debug")
def list_upcoming_bookings_debug(
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    bookings = session.exec(
        select(BookingModel)
        .where(BookingModel.tenant_id == tenant_id)
        .where(BookingModel.start >= now_naive)
        .order_by(BookingModel.start)
        .limit(50)
    ).all()

    return {
        "tenant_id": tenant_id,
        "count": len(bookings),
        "items": bookings,
    }


@router.post("/bookings/{booking_id}/complete")
def complete_booking(
    booking_id: int,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Mark a booking as completed and queue a review SMS to send ~2 hours later.
    """
    booking = session.exec(
        select(BookingModel)
        .where(BookingModel.id == booking_id)
        .where(BookingModel.tenant_id == tenant_id)
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.completed_at = datetime.now(timezone.utc)
    session.add(booking)

    if booking.phone:
        reminder = ReminderSent(
            phone=booking.phone,
            name=booking.name,
            booking_start=booking.start,
            booking_end=booking.end,
            message=None,
            template="review-queue",
            source="booking-complete",
            sms_sent=False,
            tenant_id=tenant_id,
        )
        session.add(reminder)

    session.commit()

    return {"ok": True, "booking_id": booking_id, "tenant_id": tenant_id}


@router.post("/bookings/reminders/run")
def run_review_reminders(
    session: Session = Depends(get_session),
):
    """
    Find queued review reminders (template='review-queue') older than 2 hours
    and send review SMS using booking_reminder_sms(kind='review').
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=2)

    rows = session.exec(
        select(ReminderSent)
        .where(ReminderSent.template == "review-queue")
        .where((ReminderSent.sms_sent == False) | (ReminderSent.sms_sent.is_(None)))
        .where(ReminderSent.created_at <= cutoff)
    ).all()

    sent = 0
    for r in rows:
        if not r.phone:
            continue

        tenant_id = r.tenant_id or "default"
        tenant_tz = get_tenant_tz(tenant_id, session)
        starts_at_raw = r.booking_start or now
        if starts_at_raw.tzinfo is None:
            starts_at_raw = starts_at_raw.replace(tzinfo=timezone.utc)
        starts_at_local = starts_at_raw.astimezone(tenant_tz)

        payload = {
            "name": r.name or "there",
            "phone": r.phone,
            "service": "appointment",
            "starts_at_iso": starts_at_local.isoformat(),
        }

        ok = booking_reminder_sms(tenant_id, payload, "review")
        if ok:
            r.sms_sent = True
            r.message = (r.message or "") + " [review sent]"
            sent += 1

    session.commit()
    return {"ok": True, "sent": sent}


@router.delete("/tenant/bookings/{booking_id}")
def delete_booking_for_tenant(
    booking_id: int,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    booking = session.get(BookingModel, booking_id)
    if not booking or booking.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Not Found")

    session.delete(booking)
    session.commit()
    return {"ok": True, "deleted": booking_id}
