# app/routers/vapi.py
import json as _json
import os
import re
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from typing import Any, Optional

from app.call_cache import lookup as cache_lookup, evict as cache_evict
from app.db import get_session
from app.models import Lead as LeadModel, Tenant, WebhookDedup
from app.services.sms import vapi_lead_office_sms

router = APIRouter(prefix="", tags=["vapi"])


class VapiIntakePayload(BaseModel):
    call_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    issue: Optional[str] = None
    language: Optional[str] = None
    summary: Optional[str] = None
    zip: Optional[str] = None
    service_urgency: Optional[str] = None
    phone_number_id: Optional[str] = None
    forwarded_from: Optional[str] = None


def _message_type(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    msg = body.get("message") or {}
    return str(msg.get("type") or "").strip()


def _clean_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _normalize_phone(value: Optional[str]) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) == 10:
        return digits
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    return text


def _format_display_phone(value: Optional[str]) -> str:
    normalized = _normalize_phone(value)
    if not normalized:
        return ""
    digits = re.sub(r"\D", "", normalized)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if normalized.startswith("+"):
        return normalized
    return normalized


def _extract_name_from_text(*values: Optional[str]) -> str:
    patterns = [
        r"\b(?:their|the caller'?s|caller)\s+name\s+(?:is|was)\s+([A-Z][a-z]+)\b",
        r"\b([A-Z][a-z]+)\s+called\b",
    ]
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip(" ,.")
                return candidate[:1].upper() + candidate[1:]
    return ""


def _extract_phone_from_text(*values: Optional[str]) -> str:
    patterns = [
        r"\b(?:callback|call\s*back|best)\s+(?:number|phone)\D*([+]?\d[\d\-\(\)\s]{8,}\d)",
        r"\bphone\s+number\D*([+]?\d[\d\-\(\)\s]{8,}\d)",
    ]
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                phone = _normalize_phone(match.group(1))
                if phone:
                    return phone
    return ""


def _compact_reason(value: Optional[str]) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    if len(text) <= 60 and not re.search(r"\b(called|assistant|contact|schedule|confirm)\b", text, re.IGNORECASE):
        return text.rstrip(".")

    patterns = [
        r"\b(?:because|for)\s+(their\s+)?(.+?)(?:\s+and\s+(?:needed|needs|requested)|[.!?]|$)",
        r"\b(?:issue|reason)\D+(.+?)(?:[.!?]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            phrase = match.group(match.lastindex).strip(" ,.")
            phrase = re.sub(r"^(their|the)\s+", "", phrase, flags=re.IGNORECASE)
            return phrase[:1].upper() + phrase[1:]

    match = re.match(r"(.+?)(?:[.!?]|$)", text)
    if match:
        return match.group(1).strip(" ,.")
    return text


def _compact_notes(value: Optional[str], fallback_text: Optional[str] = None) -> str:
    combined = _clean_text(value)
    fallback = _clean_text(fallback_text)
    source = combined or fallback
    if not source:
        return ""

    parts: list[str] = []

    zip_match = re.search(r"\bZIP(?:\s+code)?\D*(\d{5})\b", source, re.IGNORECASE)
    if zip_match:
        parts.append(f"ZIP {zip_match.group(1)}")

    if re.search(r"\burgent|asap|immediate|right away|fastest possible\b", source, re.IGNORECASE):
        parts.append("urgent repair")
    elif re.search(r"\btoday or tomorrow\b", source, re.IGNORECASE):
        parts.append("today or tomorrow")

    preferred_patterns = [
        r"\b(?:prefer(?:red)?|best|available)\s+(?:time|day|day/time|date)\D*(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(morning|afternoon|evening))?",
        r"\b(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(morning|afternoon|evening))?\b",
    ]
    for pattern in preferred_patterns:
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            day = match.group(1)
            day_part = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
            preferred = day.lower()
            if day_part:
                preferred = f"{preferred} {day_part.lower()}"
            parts.append(f"prefers {preferred}")
            break

    time_match = re.search(
        r"\b(?:prefer(?:red)?|best|available)\s+(?:time|day|day/time|date)\D*"
        r"((?:\d{1,2})(?::\d{2})?\s*(?:am|pm)|(?:morning|afternoon|evening))\b",
        source,
        re.IGNORECASE,
    ) or re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", source, re.IGNORECASE)
    if time_match:
        parts.append(f"prefers {time_match.group(1).lower()}")

    if not parts and combined and len(combined) <= 80:
        parts.append(combined.rstrip("."))

    return ", ".join(dict.fromkeys(parts))


def _split_reason_and_notes(reason: Optional[str], notes: Optional[str]) -> tuple[str, str]:
    return _compact_reason(reason), _compact_notes(notes, fallback_text=reason)


def _extract_zip(value: Optional[str]) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    match = re.search(r"\b(\d{5})\b", text)
    return match.group(1) if match else ""


def _extract_timing(*values: Optional[str]) -> str:
    patterns = [
        r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(morning|afternoon|evening))?(?:\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)))?\b",
        r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
    ]
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        if re.search(r"\b(asap|urgent|immediately|right away|as soon as possible)\b", text, re.IGNORECASE):
            return "ASAP"
        match = re.search(patterns[0], text, re.IGNORECASE)
        if match:
            day = (match.group(1) or "").lower()
            part = (match.group(2) or "").lower()
            at_time = (match.group(3) or "").lower()
            result = day
            if part:
                result = f"{result} {part}"
            if at_time:
                result = f"{result} at {at_time}"
            return result.strip()
        match = re.search(patterns[1], text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return ""


_VAPI_DAY_TO_WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _get_available_slots_str(tenant_id: str, days: int = 7) -> str:
    """Query available slots for a tenant and return a human-readable string for Vapi."""
    from datetime import datetime, timedelta, time, timezone
    from app.models import Booking as BookingModel, Tenant as _Tenant
    from app.routers.tenant import get_tenant_booking_config, get_tenant_tz
    from sqlmodel import select as _sel

    gen = get_session()
    session = next(gen)
    try:
        tenant = session.exec(_sel(_Tenant).where(_Tenant.slug == tenant_id)).first()
        if not tenant or not getattr(tenant, "vapi_can_book", False):
            return "I can only collect your contact information at this time. Someone from our team will call you back to schedule."

        cfg = get_tenant_booking_config(tenant_id, session)
        slot_min = cfg["slot_minutes"]
        try:
            start_t = time.fromisoformat(cfg["booking_start"])
            end_t = time.fromisoformat(cfg["booking_end"])
        except Exception:
            start_t, end_t = time(8, 0), time(17, 0)

        allowed_weekdays = {_VAPI_DAY_TO_WEEKDAY[d] for d in cfg["booking_days"] if d in _VAPI_DAY_TO_WEEKDAY}
        tenant_tz = get_tenant_tz(tenant_id, session)
        now_tz = datetime.now(tenant_tz)
        now_utc = datetime.now(timezone.utc)
        window_end = now_utc + timedelta(days=days)
        now_naive = now_utc.replace(tzinfo=None)
        window_end_naive = window_end.replace(tzinfo=None)

        existing = session.exec(
            _sel(BookingModel)
            .where(BookingModel.tenant_id == tenant_id)
            .where(BookingModel.end > now_naive)
            .where(BookingModel.start < window_end_naive)
        ).all()

        step = timedelta(minutes=slot_min)
        by_day: dict = {}
        for d in range(days):
            day = (now_tz + timedelta(days=d)).date()
            if day.weekday() not in allowed_weekdays:
                continue
            cursor = datetime.combine(day, start_t, tzinfo=tenant_tz)
            end_of_day = datetime.combine(day, end_t, tzinfo=tenant_tz)
            while cursor + step <= end_of_day:
                slot_start = cursor
                slot_end = cursor + step
                if slot_start <= now_tz:
                    cursor += step
                    continue
                s = slot_start.astimezone(timezone.utc).replace(tzinfo=None)
                e = slot_end.astimezone(timezone.utc).replace(tzinfo=None)
                conflict = any(not (e <= b.start or s >= b.end) for b in existing)
                if not conflict:
                    day_key = day.strftime("%A, %B %d").replace(" 0", " ")
                    by_day.setdefault(day_key, []).append((slot_start.isoformat(), slot_start.strftime("%I:%M %p").lstrip("0")))
                cursor += step
    finally:
        session.close()

    if not by_day:
        return "We don't have any open slots in the next week. I'll take your contact info and someone will call you to schedule."

    lines = []
    for day_label, slots in list(by_day.items())[:3]:
        time_strs = ", ".join(t for _, t in slots[:6])
        lines.append(f"{day_label}: {time_strs}")
    return "Here are our available times: " + "; ".join(lines) + ". Which works best for you?"


def _book_slot_for_vapi(tenant_id: str, call_id: str, args: dict, background_tasks) -> str:
    """Book an appointment from a Vapi tool call. Returns a confirmation string."""
    from datetime import timezone, timedelta
    from app.models import Booking as BookingModel, Tenant as _Tenant
    from app.services.sms import booking_confirmation_sms, booking_office_notify_sms
    from app.utils.phone import normalize_us_phone
    from dateutil import parser as dtparse
    from sqlmodel import select as _sel

    name = _clean_text(args.get("name") or args.get("caller_name") or "")
    phone_raw = args.get("phone") or args.get("callback_phone") or args.get("phone_number") or ""
    start_str = _clean_text(args.get("start") or args.get("start_time") or "")
    end_str = _clean_text(args.get("end") or args.get("end_time") or "")
    notes = _clean_text(args.get("notes") or args.get("issue") or "")

    if not start_str:
        return "I need a specific time to book. Could you confirm the date and time you'd like?"

    gen = get_session()
    session = next(gen)
    try:
        tenant = session.exec(_sel(_Tenant).where(_Tenant.slug == tenant_id)).first()
        if not tenant or not getattr(tenant, "vapi_can_book", False):
            return "I can only collect your contact information at this time. Someone from our team will call you back to schedule."

        try:
            start_dt = dtparse.isoparse(start_str)
        except Exception:
            return "I couldn't understand that time. Could you please confirm the date and time?"

        if end_str:
            try:
                end_dt = dtparse.isoparse(end_str)
            except Exception:
                end_dt = None
        else:
            end_dt = None

        if end_dt is None:
            from app.routers.tenant import get_tenant_booking_config
            cfg = get_tenant_booking_config(tenant_id, session)
            end_dt = start_dt + timedelta(minutes=cfg["slot_minutes"])

        start_utc = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_dt.astimezone(timezone.utc).replace(tzinfo=None)

        conflict = session.exec(
            _sel(BookingModel)
            .where(BookingModel.tenant_id == tenant_id)
            .where(BookingModel.start < end_utc)
            .where(BookingModel.end > start_utc)
        ).first()
        if conflict:
            return "I'm sorry, that time was just taken. Please ask for available times again and I'll find you another slot."

        e164 = normalize_us_phone(phone_raw) if phone_raw else ""
        booking = BookingModel(
            tenant_id=tenant_id,
            name=name or "Phone customer",
            phone=e164 or _normalize_phone(phone_raw),
            email=None,
            start=start_utc,
            end=end_utc,
            notes=notes or None,
            source="vapi",
        )
        session.add(booking)
        session.commit()
        print(f"[VAPI BOOKING] booked tenant={tenant_id!r} name={name!r} start={start_str!r}", flush=True)

        from app.routers.tenant import get_tenant_tz
        tenant_tz = get_tenant_tz(tenant_id, session)
        start_local = start_dt.astimezone(tenant_tz)
        friendly_time = start_local.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ").lstrip("0")
        display_phone = e164 or _normalize_phone(phone_raw)
    except Exception as exc:
        session.rollback()
        print(f"[VAPI BOOKING ERROR] {exc}", flush=True)
        return "I had trouble booking that appointment. A team member will call you back to confirm."
    finally:
        session.close()

    if display_phone:
        def _send_booking_sms():
            try:
                booking_confirmation_sms(tenant_id, {
                    "name": name or "there",
                    "phone": display_phone,
                    "service": "appointment",
                    "starts_at_iso": start_dt.isoformat(),
                })
            except Exception as e:
                print(f"[VAPI BOOKING SMS] confirmation error: {e}", flush=True)
            try:
                booking_office_notify_sms(tenant_id, {
                    "name": name or "Phone customer",
                    "phone": display_phone,
                    "service": "appointment",
                    "starts_at_iso": start_dt.isoformat(),
                })
            except Exception as e:
                print(f"[VAPI BOOKING SMS] office notify error: {e}", flush=True)
        background_tasks.add_task(_send_booking_sms)

    return f"You're all set! I've booked your appointment for {friendly_time}. You'll receive a confirmation text shortly. Is there anything else I can help you with?"


def _reason_for_sms(reason: Optional[str], summary: Optional[str]) -> str:
    reason_text = _clean_text(reason)
    if reason_text and reason_text.lower() != "pending":
        return _compact_reason(reason_text)

    summary_text = _clean_text(summary)
    if not summary_text:
        return ""

    match = re.match(r"(.+?)(?:[.!?]|$)", summary_text)
    if match:
        return match.group(1).strip(" ,.")
    return summary_text


def _extract_from_vapi_body(body: dict) -> dict:
    """
    VAPI sends end-of-call webhooks as a nested structure, not the flat fields
    this endpoint originally expected. This function normalises both formats.
    """
    if "message" not in body:
        return body

    msg = body.get("message") or {}
    call = msg.get("call") or {}
    analysis = msg.get("analysis") or {}
    structured = analysis.get("structuredData") or {}
    summary = msg.get("summary") or analysis.get("summary") or ""

    customer = call.get("customer") or {}
    phone = (
        structured.get("phone")
        or structured.get("callback_phone")
        or structured.get("callbackPhone")
        or structured.get("callback_number")
        or structured.get("callbackNumber")
        or structured.get("phone_number")
        or structured.get("phoneNumber")
        or customer.get("number")
        or ""
    )

    phone_number_id = call.get("phoneNumberId") or ""

    call_id = call.get("id") or ""
    print(f"[VAPI EXTRACT] call keys: {list(call.keys())}", flush=True)
    print(
        f"[VAPI EXTRACT] call.id={call_id!r} phoneNumberId={phone_number_id!r} "
        f"forwardingPhoneNumber={call.get('forwardingPhoneNumber')!r} "
        f"forwardedFrom={call.get('forwardedFrom')!r}",
        flush=True,
    )

    forwarded_from = (
        call.get("forwardingPhoneNumber")
        or call.get("forwardedFrom")
        or ""
    )

    name = (
        structured.get("name")
        or structured.get("caller_name")
        or _extract_name_from_text(summary)
        or ""
    )
    issue = (
        structured.get("issue")
        or structured.get("reason")
        or summary
        or ""
    )
    zip_code = (
        structured.get("zip")
        or structured.get("zip_code")
        or structured.get("zipcode")
        or structured.get("postal_code")
        or ""
    )
    service_urgency = _clean_text(
        structured.get("service_urgency")
        or structured.get("serviceUrgency")
        or structured.get("urgency")
        or ""
    )
    if not service_urgency:
        service_urgency = _extract_timing(summary) or ""
    phone = _extract_phone_from_text(issue, summary) or _normalize_phone(phone)
    issue = _compact_reason(issue)
    zip_code = _extract_zip(zip_code or summary)

    return {
        "call_id": call_id,
        "name": name,
        "phone": phone,
        "issue": issue,
        "summary": summary,
        "zip": zip_code,
        "service_urgency": service_urgency,
        "phone_number_id": phone_number_id,
        "forwarded_from": forwarded_from,
    }


def _resolve_tenant(phone_number_id: Optional[str], session: Session) -> Optional[str]:
    """Identify the tenant by matching call.phoneNumberId against Tenant.twilio_number."""
    if not phone_number_id:
        fallback = (os.getenv("VAPI_DEFAULT_TENANT") or "").strip()
        if fallback:
            print(f"[VAPI] phone_number_id empty - using VAPI_DEFAULT_TENANT={fallback!r}", flush=True)
            return fallback
        print("[VAPI] ERROR: phone_number_id empty - cannot resolve tenant.", flush=True)
        return None

    rows = session.exec(
        select(Tenant).where(
            Tenant.twilio_number != None,
            Tenant.twilio_number != "",
        )
    ).all()
    candidates = {t.slug: t.twilio_number for t in rows}
    print(f"[VAPI] tenant lookup: phone_number_id={phone_number_id!r} candidates={candidates}", flush=True)

    for t in rows:
        if (t.twilio_number or "").strip() == phone_number_id.strip():
            print(f"[VAPI] tenant resolved: phone_number_id={phone_number_id!r} -> {t.slug!r}", flush=True)
            return t.slug

    print(
        f"[VAPI] ERROR: phone_number_id={phone_number_id!r} unmatched against "
        f"Tenant.twilio_number - lead will NOT be saved.",
        flush=True,
    )
    return None


def _dedupe_insert(session: Session, source: str, event_id: str) -> bool:
    try:
        session.rollback()
        session.add(WebhookDedup(source=source, event_id=event_id))
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False
    except Exception as e:
        session.rollback()
        print(f"[VAPI] dedupe insert error: {e}", flush=True)
        return False


def _process_tool_call_background(tenant_id: str, call_id: str, name: str, phone: str, issue: str, zip_code: str, service_urgency: str):
    """DB + SMS work done after VAPI already got its response."""
    try:
        gen = get_session()
        session = next(gen)
        try:
            if call_id and not _dedupe_insert(session, source=f"vapi_tool:{tenant_id}", event_id=call_id):
                print(f"[VAPI TOOL-CALL] duplicate ignored call_id={call_id!r}", flush=True)
                return

            lead = LeadModel(
                name=name,
                phone=phone or "",
                email=None,
                message=issue or "Inbound call via Vapi",
                tenant_id=tenant_id,
                source="vapi",
                service_urgency=service_urgency or None,
            )
            session.add(lead)
            session.commit()
            print(f"[VAPI TOOL-CALL] lead saved for tenant={tenant_id!r}", flush=True)
        except Exception as e:
            session.rollback()
            print(f"[VAPI TOOL-CALL] lead insert error: {e}", flush=True)
        finally:
            session.close()
    except Exception as e:
        print(f"[VAPI TOOL-CALL] background session error: {e}", flush=True)

    try:
        vapi_lead_office_sms(tenant_id, {
            "name": name,
            "phone": phone,
            "issue": issue,
            "zip": zip_code,
            "service_urgency": service_urgency,
        })
    except Exception as e:
        print(f"[VAPI TOOL-CALL] office SMS error: {e}", flush=True)


async def _handle_tool_call(body: dict, background_tasks: BackgroundTasks):
    """
    Handle VAPI tool-call events mid-conversation.
    Returns immediately to VAPI, saves lead + sends SMS in background.
    """
    msg = body.get("message") or {}
    tool_calls = msg.get("toolCalls") or msg.get("toolCallList") or []
    call = msg.get("call") or {}
    phone_number_id = call.get("phoneNumberId") or ""
    call_id = call.get("id") or ""

    print(f"[VAPI TOOL-CALL] call_id={call_id!r} phone_number_id={phone_number_id!r} tools={[tc.get('function', {}).get('name') for tc in tool_calls]}", flush=True)

    # Resolve tenant synchronously (fast, just a env var or small DB lookup)
    gen = get_session()
    session = next(gen)
    try:
        tenant_id = _resolve_tenant(phone_number_id, session)
    finally:
        session.close()

    results = []
    for tc in tool_calls:
        tc_id = tc.get("id") or ""
        fn = tc.get("function") or {}
        fn_name = fn.get("name") or ""
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = _json.loads(args)
            except Exception:
                args = {}

        if fn_name == "hvac_intake":
            if not tenant_id:
                results.append({"toolCallId": tc_id, "result": "Got it, we'll have them call you back shortly."})
                continue

            name = _clean_text(args.get("name") or args.get("caller_name") or "")
            phone = _normalize_phone(
                args.get("phone") or args.get("callback_phone") or args.get("phone_number") or ""
            )
            issue = _compact_reason(args.get("issue") or args.get("reason") or "")
            zip_code = _extract_zip(args.get("zip") or args.get("zip_code") or "")
            service_urgency = _clean_text(
                args.get("service_urgency")
                or args.get("timing")
                or args.get("service_timing")
                or args.get("preferred_day")
                or ""
            )
            if not service_urgency:
                service_urgency = _extract_timing(
                    args.get("timing") or args.get("service_timing") or args.get("preferred_day") or issue
                )

            print(f"[VAPI TOOL-CALL] queuing background save: name={name!r} phone={phone!r} issue={issue!r} urgency={service_urgency!r} zip={zip_code!r}", flush=True)

            background_tasks.add_task(
                _process_tool_call_background,
                tenant_id, call_id, name, phone, issue, zip_code, service_urgency,
            )

            results.append({"toolCallId": tc_id, "result": "Got it, we'll have them call you back shortly."})

        elif fn_name == "get_availability":
            slots_str = _get_available_slots_str(tenant_id or "")
            results.append({"toolCallId": tc_id, "result": slots_str})

        elif fn_name == "book_appointment":
            result_str = _book_slot_for_vapi(tenant_id or "", call_id, args, background_tasks)
            results.append({"toolCallId": tc_id, "result": result_str})

        else:
            results.append({"toolCallId": tc_id, "result": "ok"})

    return {"results": results}


@router.post("/vapi/intake")
async def vapi_intake(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    try:
        raw_body = await request.body()
        raw_text = raw_body.decode("utf-8", errors="replace")
        print(f"[VAPI] raw body received: {raw_text[:2000]}", flush=True)
        body: Any = _json.loads(raw_text) if raw_text.strip() else {}
    except Exception as e:
        print(f"[VAPI] body parse error: {e}", flush=True)
        body = {}

    msg_type = _message_type(body)
    if msg_type == "tool-calls":
        print(f"[VAPI TOOL-CALL RAW] {raw_text[:3000]}", flush=True)
        try:
            return await _handle_tool_call(body, background_tasks)
        except Exception as e:
            print(f"[VAPI TOOL-CALL ERROR] {e}", flush=True)
            msg = body.get("message") or {}
            tool_calls = msg.get("toolCalls") or msg.get("toolCallList") or []
            results = [{"toolCallId": tc.get("id") or "", "result": "Received."} for tc in tool_calls]
            return {"results": results}
    if msg_type and msg_type != "end-of-call-report":
        print(f"[VAPI] ignoring non-final event type={msg_type!r}", flush=True)
        return {"status": "ok", "ignored_event_type": msg_type}

    flat = _extract_from_vapi_body(body) if isinstance(body, dict) else {}
    payload = VapiIntakePayload(**{k: v for k, v in flat.items() if k in VapiIntakePayload.model_fields})

    tenant_id = _resolve_tenant(payload.phone_number_id, session)
    print(
        f"[VAPI] intake - phone_number_id={payload.phone_number_id!r} forwarded_from={payload.forwarded_from!r} "
        f"tenant_id={tenant_id!r} caller={payload.phone!r} name={payload.name!r}",
        flush=True,
    )

    if tenant_id is None:
        print(
            f"[VAPI] DROPPING lead - tenant unresolved. "
            f"caller={payload.phone!r} name={payload.name!r} issue={payload.issue!r} "
            f"forwarded_from={payload.forwarded_from!r}",
            flush=True,
        )
        return {"status": "error", "detail": "tenant not resolved"}

    if payload.call_id and not _dedupe_insert(session, source=f"vapi_intake:{tenant_id}", event_id=payload.call_id):
        print(f"[VAPI] duplicate intake ignored for tenant={tenant_id!r} call_id={payload.call_id!r}", flush=True)
        return {"status": "ok", "tenant_id": tenant_id, "deduped": True}

    message_parts = [payload.issue or ""]
    message = " | ".join(p for p in message_parts if p).strip() or "Inbound call via Vapi"

    lead = LeadModel(
        name=(payload.name or "").strip(),
        phone=(payload.phone or "").strip(),
        email=None,
        message=message,
        tenant_id=tenant_id,
        source="vapi",
        service_urgency=(payload.service_urgency or "").strip() or None,
    )
    try:
        session.add(lead)
        session.commit()
        session.refresh(lead)
    except Exception as e:
        session.rollback()
        print(f"[VAPI] lead insert error: {e}", flush=True)

    try:
        vapi_lead_office_sms(tenant_id, {
            "name": payload.name,
            "phone": payload.phone,
            "issue": payload.issue,
            "zip": payload.zip,
            "service_urgency": payload.service_urgency,
        })
        print(f"[VAPI] office SMS sent for tenant={tenant_id!r}", flush=True)
    except Exception as e:
        print(f"[VAPI] office SMS error: {e}", flush=True)

    return {"status": "ok", "tenant_id": tenant_id}
