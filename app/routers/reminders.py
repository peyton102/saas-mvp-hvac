# app/routers/reminders.py
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from dateutil import parser as dtparse

from app import config, storage
from app.services.sms import send_sms
from app.db import get_session
from app.models import Booking as BookingModel, ReminderSent as ReminderModel

router = APIRouter(prefix="", tags=["reminders"])


def _parse_offsets(spec: str) -> List[tuple[str, timedelta]]:
    """
    Parse '24h,2h,30m' -> [("24h", 24h), ("2h", 2h), ("30m", 30m)]
    """
    out: List[tuple[str, timedelta]] = []
    if not spec:
        return out
    for raw in [s.strip() for s in spec.split(",") if s.strip()]:
        num = "".join(ch for ch in raw if ch.isdigit())
        unit = "".join(ch for ch in raw if ch.isalpha()).lower() or "m"
        if not num:
            continue
        n = int(num)
        if unit in ("m", "min", "mins", "minute", "minutes"):
            out.append((raw, timedelta(minutes=n)))
        elif unit in ("h", "hr", "hrs", "hour", "hours"):
            out.append((raw, timedelta(hours=n)))
        elif unit in ("d", "day", "days"):
            out.append((raw, timedelta(days=n)))
        else:
            # default to minutes if unknown unit
            out.append((raw, timedelta(minutes=n)))
    return out


def _already_sent_db(session: Session, phone: str, start_dt: datetime, template: str) -> bool:
    q = select(ReminderModel).where(
        ReminderModel.phone == phone,
        ReminderModel.booking_start == start_dt,
        ReminderModel.template == template,
    )
    return session.exec(q).first() is not None


def _due_items(session: Session, look_back_minutes: int) -> List[Dict[str, Any]]:
    """
    Compute reminders due now (within look-back + small window), from DB bookings.
    """
    now = datetime.utcnow()
    window_sec = int(getattr(config, "REMINDER_WINDOW_SECONDS", 900))  # default 15 min
    lower_bound = now - timedelta(minutes=look_back_minutes) - timedelta(seconds=window_sec)
    upper_bound = now + timedelta(seconds=window_sec)

    # fetch recent bookings (loose window)
    rows = session.exec(
        select(BookingModel).where(BookingModel.start >= now - timedelta(days=14)).order_by(BookingModel.start)
    ).all()

    offsets = _parse_offsets(getattr(config, "REMINDERS", "24h,2h"))
    items: List[Dict[str, Any]] = []

    for b in rows:
        if not b.start:
            continue
        for label, delta in offsets:
            remind_at = b.start - delta
            if lower_bound <= remind_at <= upper_bound:
                # Build SMS
                when_txt = b.start.isoformat()
                body = (
                    f"Reminder from {config.FROM_NAME}: your appointment is at {when_txt}. "
                    f"Need to reschedule? {config.BOOKING_LINK}"
                )
                items.append({
                    "phone": (b.phone or "").strip(),
                    "name": (b.name or "").strip(),
                    "start": b.start,
                    "end": b.end,
                    "template": label,
                    "body": body,
                    "source": "cron",
                })
    # Filter items with phones
    return [it for it in items if it["phone"]]


@router.get("/debug/run-reminders")
def debug_run_reminders(
    look_back_minutes: int = Query(10, ge=0),
    session: Session = Depends(get_session),
):
    """Preview which reminders would send (no SMS). Uses DB bookings."""
    items = _due_items(session, look_back_minutes)
    # Show only minimal preview fields
    preview = [
        {
            "phone": it["phone"],
            "name": it["name"],
            "start": it["start"].isoformat(),
            "template": it["template"],
            "body": it["body"],
        }
        for it in items
    ]
    return {"count": len(preview), "items": preview}


@router.post("/tasks/send-reminders")
def send_reminders(
    look_back_minutes: int = Query(10, ge=0),
    session: Session = Depends(get_session),
):
    """
    Send due reminders. De-dupes using DB (and CSV if available), honors SMS_DRY_RUN.
    Also logs to CSV (if storage supports) and DB (ReminderSent).
    """
    items = _due_items(session, look_back_minutes)

    sent = 0
    skipped_dup = 0
    failures = 0

    for it in items:
        phone = it["phone"]
        start_dt: datetime = it["start"]
        template = it["template"]
        body = it["body"]
        name = it["name"]

        # DB dedupe
        if _already_sent_db(session, phone, start_dt, template):
            skipped_dup += 1
            continue

        # Optional CSV dedupe if your storage tracks it
        try:
            if hasattr(storage, "reminder_already_sent"):
                if storage.reminder_already_sent(phone=phone, start_iso=start_dt.isoformat(), template=template):
                    skipped_dup += 1
                    continue
        except Exception:
            pass

        ok = False
        try:
            ok = send_sms(phone, body)  # DRY-RUN respected inside send_sms
        except Exception as e:
            print(f"[REMINDER SMS ERROR] {e}")
            failures += 1

        # CSV log (preserve existing behavior)
        try:
            if hasattr(storage, "save_reminder_sent"):
                storage.save_reminder_sent({
                    "phone": phone,
                    "name": name,
                    "booking_start": start_dt.isoformat(),
                    "message": body,
                    "template": template,
                    "source": it.get("source", "cron"),
                    "sms_sent": "true" if ok else "false",
                })
        except Exception as e:
            print(f"[REMINDER CSV LOG ERROR] {e}")

        # DB log (new)
        session.add(ReminderModel(
            phone=phone,
            name=name or None,
            booking_start=start_dt,
            booking_end=it["end"],
            message=body,
            template=template,
            source=it.get("source", "cron"),
            sms_sent=bool(ok),
        ))
        session.commit()

        if ok:
            sent += 1

    return {"ok": True, "sent": sent, "skipped_duplicates": skipped_dup, "failures": failures}


@router.get("/debug/reminders-sent")
def debug_reminders_sent(limit: int = 50, session: Session = Depends(get_session)):
    """Read recent sent reminders from DB (newest first)."""
    rows = session.exec(
        select(ReminderModel).order_by(ReminderModel.id.desc()).limit(limit)
    ).all()
    items = [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "phone": r.phone,
            "name": r.name,
            "booking_start": r.booking_start.isoformat() if r.booking_start else None,
            "booking_end": r.booking_end.isoformat() if r.booking_end else None,
            "template": r.template,
            "message": r.message,
            "source": r.source,
            "sms_sent": r.sms_sent,
        }
        for r in rows
    ]
    return {"count": len(items), "items": items}
