# app/routers/calendly.py
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlmodel import Session, select
from dateutil import parser as dtparse
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import timedelta
import hashlib
from app.tenantold import brand
from app import config, storage
from app.db import get_session
from app.models import Booking as BookingModel, WebhookDedup
from app.services.sms import send_sms
from ..deps import get_tenant_id

router = APIRouter(prefix="", tags=["calendly"])

# ---- (Optional) model if you want typed payloads later ----
class _Invitee(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

class CalendlyPayload(BaseModel):
    invitee: Optional[_Invitee] = None
    invitee_phone: Optional[str] = None
    start_time: str
    timezone: Optional[str] = None
    notes: Optional[str] = None
    event_id: Optional[str] = None

# ---- helpers ----
def _dedupe_insert(session: Session, source: str, event_id: str) -> bool:
    """Return True if first time seen; False if duplicate."""
    try:
        session.add(WebhookDedup(source=source, event_id=event_id))
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False

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

# ---- routes ----
@router.post("/webhooks/calendly")
def calendly_webhook(
    payload: Dict[str, Any],
    request: Request,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    # Secret verification (only if configured)
    secret_expected = getattr(config, "CALENDLY_WEBHOOK_SECRET", "") or ""
    if secret_expected:
        secret_got = (request.headers.get("x-webhook-secret") or "").strip()
        if secret_got != secret_expected:
            raise HTTPException(status_code=401, detail="Invalid Calendly secret")

    # Calendly sometimes nests under "payload"
    p = payload.get("payload") or payload

    # ---- Idempotency key ----
    invitee = p.get("invitee") or {}
    event_uuid = (p.get("event_uuid") or p.get("event_id") or p.get("event") or "").strip()
    if event_uuid:
        event_id = event_uuid
    else:
        phone = (p.get("invitee_phone") or invitee.get("phone") or "").strip()
        email = (invitee.get("email") or p.get("email") or "").strip().lower()
        start = (p.get("start_time") or "").strip()
        tz = (p.get("timezone") or p.get("event_timezone") or "").strip()
        base = f"{email}|{phone}|{start}|{tz}"
        event_id = hashlib.sha256(base.encode("utf-8")).hexdigest()

    first_time = _dedupe_insert(session, source=f"calendly:{tenant_id}", event_id=event_id)
    if not first_time:
        return {"ok": True, "deduped": True}

    # ---- Extract fields ----
    name = invitee.get("name") or p.get("name") or ""
    email = invitee.get("email") or p.get("email") or ""
    phone = (_extract_phone(p) or "").strip()
    start = p.get("start_time") or ""
    end = p.get("end_time") or ""
    tz = p.get("timezone") or p.get("event_timezone") or "America/New_York"
    notes = (p.get("cancellation") or {}).get("reason") or p.get("notes") or ""

    # ---- Optional branded confirm SMS (DRY RUN honored) ----
    ok = False
    if phone and not storage.sent_recently(phone, minutes=getattr(config, "ANTI_SPAM_MINUTES", 120)):
        b = brand(tenant_id)
        msg = (
            f"You're booked with {b['FROM_NAME']}. "
            f"Start: {start} ({tz}). To reschedule: {b['BOOKING_LINK']}"
        )
        try:
            ok = send_sms(phone, msg)
        except Exception as e:
            print(f"[BOOKING SMS ERROR] {e}")

    # ---- CSV write (only when DB_FIRST is false) ----
    if not getattr(config, "DB_FIRST", True):
        try:
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
                tenant_id=tenant_id,
            )
        except TypeError:
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

    # ---- DB write (primary) ----
    try:
        start_dt = dtparse.isoparse(start) if start else None
    except Exception:
        start_dt = None

    if start_dt:
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
            tenant_id=tenant_id,
        ))
        session.commit()

    return {"ok": True, "deduped": False}

@router.get("/debug/bookings")
def debug_bookings(
    limit: int = 20,
    source: str = Query("db", pattern="^(csv|db)$"),
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),     # ✅ tenant injected
):
    if source == "db":
        rows = session.exec(
            select(BookingModel)
            .where(BookingModel.tenant_id == tenant_id)  # ✅ filter
            .order_by(BookingModel.id.desc())
            .limit(limit)
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
                "tenant_id": r.tenant_id,
            }
            for r in rows
        ]
        return {"count": len(items), "items": items}

    # CSV fallback
    items = storage.read_bookings(limit)
    if items and isinstance(items[0], dict) and "tenant_id" in items[0]:
        items = [it for it in items if it.get("tenant_id") == tenant_id]
    return {"count": len(items), "items": items}
