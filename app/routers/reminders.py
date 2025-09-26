# app/routers/reminders.py
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from sqlmodel import Session, select

from app import config, storage
from app.services.sms import send_sms
from app.utils.phone import normalize_us_phone
from app.db import get_session
from app.models import Booking as BookingModel, ReminderSent as ReminderModel

router = APIRouter(prefix="", tags=["reminders"])


# --------------------------- tenant resolution ---------------------------

def _tenant_keys_map() -> dict:
    # Supports either config.TENANT_KEYS or config.settings.TENANT_KEYS
    if hasattr(config, "TENANT_KEYS") and isinstance(config.TENANT_KEYS, dict):
        return config.TENANT_KEYS
    if hasattr(config, "settings") and hasattr(config.settings, "TENANT_KEYS"):
        return getattr(config.settings, "TENANT_KEYS") or {}
    return {}

def _resolve_tenant(request: Request) -> Optional[str]:
    """
    Resolve tenant in priority:
      1) request.state.tenant_id (set by middleware)
      2) X-API-Key header mapped via TENANT_KEYS
      3) Bearer token mapped via TENANT_KEYS
    Returns None if not found (caller can 401).
    """
    # 1) middleware
    t = getattr(request.state, "tenant_id", None)
    if t and t != "public":
        return t

    # 2) X-API-Key
    api_key = (request.headers.get("x-api-key") or "").strip()
    if api_key:
        t = _tenant_keys_map().get(api_key)
        if t:
            return t

    # 3) Bearer (only if it’s actually a tenant key)
    auth = (request.headers.get("authorization") or "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        t = _tenant_keys_map().get(token)
        if t:
            return t

    return None


# ------------------------------ helpers --------------------------------

def _parse_reminder_list() -> List[Tuple[str, timedelta]]:
    """
    Parse REMINDERS like "24h,2h" into [("24h", 24h), ("2h", 2h)].
    Supports minutes ("m") and hours ("h").
    """
    src = getattr(config, "REMINDERS", None)
    if src is None and hasattr(config, "settings"):
        src = getattr(config.settings, "REMINDERS", "24h,2h")
    raw = (src or "24h,2h").split(",")
    out: List[Tuple[str, timedelta]] = []
    for tok in [t.strip() for t in raw if t.strip()]:
        if tok.endswith("h"):
            try:
                out.append((tok, timedelta(hours=int(tok[:-1]))))
            except Exception:
                continue
        elif tok.endswith("m"):
            try:
                out.append((tok, timedelta(minutes=int(tok[:-1]))))
            except Exception:
                continue
    return out or [("24h", timedelta(hours=24)), ("2h", timedelta(hours=2))]

def _already_sent(session: Session, tenant_id: str, phone: str, template: str, booking_start: datetime) -> bool:
    q = select(ReminderModel).where(
        (ReminderModel.tenant_id == tenant_id) &
        (ReminderModel.phone == phone) &
        (ReminderModel.template == template) &
        (ReminderModel.booking_start == booking_start.replace(microsecond=0))
    ).limit(1)
    return session.exec(q).first() is not None

def _make_msg(name: str, start_dt_utc: datetime) -> str:
    who = (name or "").strip() or "there"
    tz_name = getattr(config, "TZ", "America/New_York")
    try:
        local = start_dt_utc.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = start_dt_utc  # fallback
    when = local.strftime("%a %b %d at %I:%M %p").lstrip("0")
    return (
        f"Reminder from {config.FROM_NAME}: your appointment is {when} ({tz_name}). "
        f"Need to reschedule? {config.BOOKING_LINK}"
    )

def _iter_due(session: Session, tenant_id: str, window_minutes: int) -> List[Dict[str, Any]]:
    """
    Find bookings for THIS tenant whose reminder trigger time fell within
    the past `window_minutes` (± padding).
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=max(1, window_minutes))
    window_end = now

    pad_src = getattr(config, "REMINDER_WINDOW_SECONDS", None)
    if pad_src is None and hasattr(config, "settings"):
        pad_src = getattr(config.settings, "REMINDER_WINDOW_SECONDS", 900)
    window_pad = int(pad_src or 900)  # default 15m

    # Query this tenant's bookings in a practical window
    since = now - timedelta(days=2)
    until = now + timedelta(days=7)
    rows = session.exec(
        select(BookingModel)
        .where(BookingModel.tenant_id == tenant_id)
        .where(BookingModel.start >= since)
        .where(BookingModel.start <= until)
        .order_by(BookingModel.start.asc())
    ).all()

    templates = _parse_reminder_list()
    due: List[Dict[str, Any]] = []

    for r in rows:
        if not r.start:
            continue

        # Ensure tz-aware UTC for math
        start_dt = r.start if r.start.tzinfo else r.start.replace(tzinfo=timezone.utc)
        name = r.name or ""
        phone_raw = (r.phone or "").strip()
        e164 = normalize_us_phone(phone_raw) if phone_raw else ""

        for tpl_name, delta in templates:
            trigger = start_dt - delta
            if (window_start - timedelta(seconds=window_pad)) <= trigger <= (window_end + timedelta(seconds=window_pad)):
                if e164 and not _already_sent(session, tenant_id, e164, tpl_name, start_dt.replace(microsecond=0)):
                    body = _make_msg(name, start_dt)
                    due.append({
                        "tenant_id": tenant_id,
                        "phone": e164,
                        "name": name,
                        "booking_start": start_dt,
                        "booking_end": r.end,
                        "template": tpl_name,
                        "message": body,
                        "source": r.source or "cron",
                    })

    return due


# ------------------------------ DEBUG ----------------------------------
# NOTE: Do NOT add any extra bearer checks here; main.py middleware already
# enforces /debug/* with DEBUG_BEARER_TOKEN (or allows X-API-Key per your config).

@router.get("/debug/reminders-preview")
def reminders_preview(
    request: Request,
    look_back_minutes: int = Query(60, ge=1, le=720),
    session: Session = Depends(get_session),
):
    tenant_id = _resolve_tenant(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing or unknown tenant key")

    items = _iter_due(session, tenant_id, look_back_minutes)
    return {"count": len(items), "items": items}

@router.get("/debug/reminders-sent")
def debug_reminders_sent(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
):
    tenant_id = _resolve_tenant(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing or unknown tenant key")

    rows = session.exec(
        select(ReminderModel)
        .where(ReminderModel.tenant_id == tenant_id)
        .order_by(ReminderModel.id.desc())
        .limit(limit)
    ).all()
    items = [
        {
            "id": r.id,
            "created_at": (r.created_at.isoformat() if r.created_at else None),
            "phone": r.phone,
            "name": r.name or "",
            "booking_start": (r.booking_start.isoformat() if r.booking_start else None),
            "booking_end": (r.booking_end.isoformat() if r.booking_end else None),
            "message": r.message or "",
            "template": r.template or "",
            "source": r.source or "",
            "sms_sent": bool(r.sms_sent),
            "tenant_id": r.tenant_id,
        }
        for r in rows
    ]
    return {"count": len(items), "items": items}


# ---------------------------- SEND & LOG --------------------------------

@router.post("/tasks/send-reminders")
def send_reminders(
    request: Request,
    look_back_minutes: int = Query(60, ge=1, le=720),
    session: Session = Depends(get_session),
):
    # /tasks/* is not under /debug; require a resolvable tenant
    tenant_id = _resolve_tenant(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing or unknown tenant key")

    items = _iter_due(session, tenant_id, look_back_minutes)

    sent = 0
    skipped_duplicates = 0
    failures = 0

    for it in items:
        phone = it["phone"]
        name = it["name"]
        start_dt: datetime = it["booking_start"]
        end_dt: Optional[datetime] = it.get("booking_end")
        template = it["template"]
        body = it["message"]

        # duplicate guard (race safety)
        if _already_sent(session, tenant_id, phone, template, start_dt.replace(microsecond=0)):
            skipped_duplicates += 1
            continue

        ok = False
        try:
            ok = send_sms(phone, body)  # honors SMS_DRY_RUN in Twilio service
        except Exception as e:
            failures += 1
            print(f"[REMINDER SMS ERROR] {e}")

        # DB write
        session.add(ReminderModel(
            tenant_id=tenant_id,
            phone=phone,
            name=name,
            booking_start=start_dt.replace(microsecond=0),
            booking_end=(end_dt.replace(microsecond=0) if end_dt else None),
            template=template,
            message=body,
            source=it.get("source", "cron"),
            sms_sent=bool(ok),
        ))
        session.commit()

        # Optional CSV write when DB_FIRST = False
        try:
            db_first = getattr(config, "DB_FIRST", None)
            if db_first is None and hasattr(config, "settings"):
                db_first = getattr(config.settings, "DB_FIRST", True)
            if (not db_first) and hasattr(storage, "save_reminder_sent"):
                storage.save_reminder_sent({
                    "tenant_id": tenant_id,
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

        if ok:
            sent += 1

    return {"ok": True, "sent": sent, "skipped_duplicates": skipped_duplicates, "failures": failures}
