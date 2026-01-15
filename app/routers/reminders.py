# app/routers/reminders.py
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from zoneinfo import ZoneInfo
from sqlmodel import Session, select
from fastapi import APIRouter, Depends, Query, Request, HTTPException

from app.deps import get_tenant_id
from app import config, storage
from app.services.sms import send_sms
from app.services.email import send_booking_reminder
from app.db import get_session
from app.models import Booking as BookingModel, ReminderSent as ReminderModel
from app.utils.phone import normalize_us_phone

router = APIRouter(prefix="", tags=["reminders"])


# --------------------------- tenant resolution ---------------------------

def _tenant_keys_map() -> dict:
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
    """
    t = getattr(request.state, "tenant_id", None)
    if t and t != "public":
        return t

    api_key = (request.headers.get("x-api-key") or "").strip()
    if api_key:
        t = _tenant_keys_map().get(api_key)
        if t:
            return t

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
def _utc_naive(dt: datetime) -> datetime:
    if not dt:
        return dt
    if dt.tzinfo is None:
        return dt.replace(microsecond=0)
    return dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def _already_sent(session: Session, tenant_id: str, phone: str, template: str, booking_start: datetime) -> bool:
    bs = _utc_naive(booking_start)
    q = select(ReminderModel).where(
        (ReminderModel.tenant_id == tenant_id) &
        (ReminderModel.phone == phone) &
        (ReminderModel.template == template) &
        (ReminderModel.booking_start == bs)
    ).limit(1)
    return session.exec(q).first() is not None



def _make_msg(name: str, start_dt_utc: datetime) -> str:
    who = (name or "").strip() or "there"
    tz_name = getattr(config, "TZ", "America/New_York")
    try:
        local = start_dt_utc.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = start_dt_utc
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

    tz_name = getattr(config, "TZ", "America/New_York")
    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = timezone.utc

    for r in rows:
        if not r.start:
            continue

        # Normalize booking start → UTC using config.TZ for naive datetimes
        if r.start.tzinfo:
            # already tz-aware; normalize to UTC
            start_dt_utc = r.start.astimezone(timezone.utc)
        else:
            # stored as naive local time → attach config.TZ, then convert to UTC
            start_dt_utc = r.start.replace(tzinfo=timezone.utc)

        name = r.name or ""
        phone_raw = (r.phone or "").strip()
        e164 = normalize_us_phone(phone_raw) if phone_raw else ""

        for tpl_name, delta in templates:
            trigger = start_dt_utc - delta
            if (window_start - timedelta(seconds=window_pad)) <= trigger <= (window_end + timedelta(seconds=window_pad)):
                if e164 and not _already_sent(session, tenant_id, e164, tpl_name, start_dt_utc.replace(microsecond=0)):
                    body = _make_msg(name, start_dt_utc)
                    due.append({
                        "tenant_id": tenant_id,
                        "phone": e164,
                        "name": name,
                        "email": (r.email or None),
                        "booking_start": start_dt_utc,
                        "booking_end": r.end,
                        "template": tpl_name,
                        "message": body,
                        "source": r.source or "cron",
                    })

    return due


# ------------------------------ DEBUG ----------------------------------


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
            "created_at": (
    (r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc))
    .astimezone(timezone.utc)
    .isoformat(timespec="seconds")
    .replace("+00:00", "Z")
    if r.created_at else None
),

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


# ---------------------------- SEND & LOG (per-tenant) --------------------------------


def _send_for_tenant(session: Session, tenant_id: str, look_back_minutes: int) -> Dict[str, int]:
    """
    Core send+log logic for a single tenant. Reused by both per-tenant and all-tenants endpoints.
    """
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

        # duplicate guard
        if _already_sent(session, tenant_id, phone, template, start_dt.replace(microsecond=0)):
            skipped_duplicates += 1
            continue

        ok = False
        try:
            ok = send_sms(phone, body)  # honors SMS_DRY_RUN
        except Exception as e:
            failures += 1
            print(f"[REMINDER SMS ERROR] {e}")

        # EMAIL reminder (24h / 2h) – parallel to SMS
        email_ok = False
        try:
            email_payload = {
                "name": name,
                "email": it.get("email") or None,
                "phone": phone,
                "address": "",
                "service": "appointment",
                "starts_at_iso": start_dt.isoformat(),
                "reschedule_url": getattr(config, "BOOKING_LINK", "") or "",
            }
            email_ok = send_booking_reminder(tenant_id, email_payload, template)
        except Exception as e:
            print(f"[REMINDER EMAIL ERROR] {e}")

        session.add(ReminderModel(
            tenant_id=tenant_id,
            phone=phone,
            name=name,
            booking_start=_utc_naive(start_dt),
            booking_end=_utc_naive(end_dt) if end_dt else None,
            template=template,
            message=body + ("" if not email_ok else " [email sent]"),
            source=it.get("source", "cron"),
            sms_sent=bool(ok),
        ))
        session.commit()

        if ok:
            sent += 1

    return {
        "sent": sent,
        "skipped_duplicates": skipped_duplicates,
        "failures": failures,
    }


@router.post("/tasks/send-reminders")
def send_reminders(
    request: Request,
    look_back_minutes: int = Query(60, ge=1, le=720),
    session: Session = Depends(get_session),
):
    """
    Per-tenant endpoint – used by PowerShell tests / frontend with proper auth.
    """
    tenant_id = _resolve_tenant(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing or unknown tenant key")

    metrics = _send_for_tenant(session, tenant_id, look_back_minutes)
    return {"ok": True, **metrics}


# ---------------------------- SEND & LOG (ALL tenants) -------------------------------


@router.post("/tasks/send-reminders-all")
def send_reminders_all(
    look_back_minutes: int = Query(60, ge=1, le=720),
    session: Session = Depends(get_session),
):
    """
    Internal use by cron: scan ALL tenant_ids that have bookings,
    and send reminders per tenant.

    No hard-coded slug, no TENANT_KEYS dependency.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=2)
    until = now + timedelta(days=7)

    tenant_ids: List[str] = session.exec(
        select(BookingModel.tenant_id)
        .where(BookingModel.start >= since)
        .where(BookingModel.start <= until)
        .distinct()
    ).all()

    totals = {"sent": 0, "skipped_duplicates": 0, "failures": 0}
    per_tenant = {}

    for t in tenant_ids:
        if not t:
            continue
        m = _send_for_tenant(session, t, look_back_minutes)
        per_tenant[t] = m
        totals["sent"] += m["sent"]
        totals["skipped_duplicates"] += m["skipped_duplicates"]
        totals["failures"] += m["failures"]

    return {
        "ok": True,
        "tenants": tenant_ids,
        "totals": totals,
        "per_tenant": per_tenant,
    }
