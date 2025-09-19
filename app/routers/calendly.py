# app/routers/calendly.py
from datetime import timedelta
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from dateutil import parser as dtparse

from app import config, storage
from app.services.sms import send_sms
from app.db import get_session
from app.models import Booking as BookingModel

router = APIRouter(prefix="", tags=["calendly"])


def _extract_phone(p: dict) -> Optional[str]:
    invitee = (p.get("invitee") or {})
    # common fields
    for key in ("phone", "phone_number", "mobile", "sms"):
        val = invitee.get(key)
        if val:
            return str(val).strip()
    # Q&A fallback
    for qa in (p.get("questions_and_answers") or []):
        q = (qa.get("question") or "").lower()
        a = (qa.get("answer") or "").strip()
        if "phone" in q and a:
            return a
    return None


@router.post("/webhooks/calendly")
def calendly_webhook(payload: Dict[str, Any], session: Session = Depends(get_session)):
    """Handle Calendly invitee.created / invitee.canceled webhook payloads.
       CSV write preserved; also writes a Booking row to the DB."""
    p = payload.get("payload") or payload

    event_id = str(p.get("event") or p.get("event_uuid") or "")
    invitee = p.get("invitee") or {}
    name = invitee.get("name") or p.get("name") or ""
    email = invitee.get("email") or p.get("email") or ""
    phone = (_extract_phone(p) or "").strip()

    start = p.get("start_time") or ""
    end = p.get("end_time") or ""
    tz = p.get("timezone") or p.get("event_timezone") or "America/New_York"
    notes = (p.get("cancellation") or {}).get("reason") or p.get("notes") or ""

    # SMS confirm (DRY RUN if enabled)
    ok = False
    if phone and not storage.sent_recently(phone, minutes=getattr(config, "ANTI_SPAM_MINUTES", 120)):
        msg = (
            f"You're booked with {config.FROM_NAME}. "
            f"Start: {start} ({tz}). To reschedule: {config.BOOKING_LINK}"
        )
        try:
            ok = send_sms(phone, msg)
        except Exception as e:
            print(f"[BOOKING SMS ERROR] {e}")

    # --- CSV write (existing behavior) ---
    if hasattr(storage, "save_booking"):
        storage.save_booking(
            event_id=event_id,
            invitee_name=name,
            invitee_email=email,
            invitee_phone=phone,
            start_time=start,
            end_time=end,
            tz_str=tz,
            notes=notes,
            sms_sent=ok,
            source="calendly",
        )
    else:
        storage.save_lead(
            {"name": name, "phone": phone, "email": email, "message": f"Booking {event_id} {start}"},
            sms_body="calendly",
            sms_sent=ok,
            source="calendly",
        )

    # --- DB write (new) ---
    # Parse datetimes; require start for DB row. If missing, skip DB write (CSV already logged).
    if not start:
        return {"ok": True}
    try:
        start_dt = dtparse.isoparse(start)
    except Exception:
        # Invalid start_time -> skip DB write but keep CSV behavior
        return {"ok": True}

    if end:
        try:
            end_dt = dtparse.isoparse(end)
        except Exception:
            end_dt = start_dt + timedelta(minutes=60)
    else:
        end_dt = start_dt + timedelta(minutes=60)

    session.add(BookingModel(
        name=name or "",
        phone=phone or "",
        email=email or "",
        start=start_dt,
        end=end_dt,
        notes=notes or "",
        source="calendly",
    ))
    session.commit()

    return {"ok": True}


@router.get("/debug/bookings")
def debug_bookings(
    limit: int = 20,
    source: str = "csv",
    session: Session = Depends(get_session),
):
    source = (source or "csv").lower()
    if source == "db":
        rows = session.exec(
            select(BookingModel).order_by(BookingModel.id.desc()).limit(limit)
        ).all()
        items = [
            {
                "id": r.id,
                "created_at": (r.created_at.isoformat() if r.created_at else None),
                "name": r.name,
                "phone": r.phone,
                "email": r.email,
                "start": r.start.isoformat() if r.start else None,
                "end": r.end.isoformat() if r.end else None,
                "notes": r.notes,
                "source": r.source,
            }
            for r in rows
        ]
        return {"count": len(items), "items": items}

    # default: CSV
    items = storage.read_bookings(limit)
    return {"count": len(items), "items": items}

