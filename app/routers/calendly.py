# app/routers/calendly.py
from fastapi import APIRouter
from app import config, storage
from app.services.sms import send_sms

router = APIRouter(prefix="", tags=["calendly"])

def _extract_phone(p: dict) -> str | None:
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
def calendly_webhook(payload: dict):
    """Handle Calendly invitee.created / invitee.canceled webhook payloads."""
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

    # save booking if supported, else fall back to a lead row
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
    return {"ok": True}

@router.get("/debug/bookings")
def debug_bookings(limit: int = 20):
    if hasattr(storage, "read_bookings"):
        items = storage.read_bookings(limit)
        return {"count": len(items), "items": items}
    return {"count": 0, "items": []}
