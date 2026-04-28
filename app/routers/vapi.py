# app/routers/vapi.py
import json as _json
import re
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from typing import Any, Optional

from app.call_cache import lookup as cache_lookup, evict as cache_evict
from app.db import get_session
from app.models import Lead as LeadModel, Tenant, WebhookDedup
from app.services.sms import get_brand_for_tenant, _office_destination_for_tenant, send_sms

router = APIRouter(prefix="", tags=["vapi"])


class VapiIntakePayload(BaseModel):
    call_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    language: Optional[str] = None
    summary: Optional[str] = None
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
    summary = msg.get("summary") or ""

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
        or _extract_name_from_text(summary, structured.get("notes"), structured.get("details"))
        or ""
    )
    reason = structured.get("reason") or structured.get("issue") or summary or ""
    notes = structured.get("notes") or structured.get("details") or ""
    phone = _extract_phone_from_text(notes, summary) or _normalize_phone(phone)
    reason = _compact_reason(reason)

    return {
        "call_id": call_id,
        "name": name,
        "phone": phone,
        "reason": reason,
        "notes": notes,
        "summary": summary,
        "phone_number_id": phone_number_id,
        "forwarded_from": forwarded_from,
    }


def _resolve_tenant(phone_number_id: Optional[str], session: Session) -> Optional[str]:
    """Identify the tenant by matching call.phoneNumberId against Tenant.twilio_number."""
    if not phone_number_id:
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


@router.post("/vapi/intake")
async def vapi_intake(
    request: Request,
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
            f"caller={payload.phone!r} name={payload.name!r} reason={payload.reason!r} "
            f"notes={payload.notes!r} forwarded_from={payload.forwarded_from!r}",
            flush=True,
        )
        return {"status": "error", "detail": "tenant not resolved"}

    if payload.call_id and not _dedupe_insert(session, source=f"vapi_intake:{tenant_id}", event_id=payload.call_id):
        print(f"[VAPI] duplicate intake ignored for tenant={tenant_id!r} call_id={payload.call_id!r}", flush=True)
        return {"status": "ok", "tenant_id": tenant_id, "deduped": True}

    message_parts = [payload.reason or "", payload.notes or ""]
    message = " | ".join(p for p in message_parts if p).strip() or "Inbound call via Vapi"

    lead = LeadModel(
        name=(payload.name or "").strip(),
        phone=(payload.phone or "").strip(),
        email=None,
        message=message,
        tenant_id=tenant_id,
        source="vapi",
    )
    try:
        session.add(lead)
        session.commit()
        session.refresh(lead)
    except Exception as e:
        session.rollback()
        print(f"[VAPI] lead insert error: {e}", flush=True)

    try:
        office_to = _office_destination_for_tenant(tenant_id)
        if office_to:
            b = get_brand_for_tenant(tenant_id)
            business_name = b.get("business_name") or tenant_id
            name_display = (payload.name or "Unknown").strip()
            phone_display = _format_display_phone(payload.phone) or "unknown"
            reason_display = _reason_for_sms(payload.reason, payload.summary)
            _, notes_display = _split_reason_and_notes(payload.reason, payload.notes)
            alert_parts = [
                f"New Lead - {business_name}",
                f"Name: {name_display}",
                f"Phone: {phone_display}",
                f"Reason: {reason_display or 'Pending'}",
            ]
            if notes_display:
                alert_parts.append(f"Notes: {notes_display}")
            send_sms(office_to, "\n".join(alert_parts))
            print(f"[VAPI] office SMS sent to {office_to} for tenant={tenant_id!r}", flush=True)
        else:
            print(f"[VAPI] no office_sms_to configured for tenant={tenant_id!r} - skipping SMS", flush=True)
    except Exception as e:
        print(f"[VAPI] office SMS error: {e}", flush=True)

    return {"status": "ok", "tenant_id": tenant_id}
