# app/routers/vapi.py
import json as _json
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
    phone_number_id: Optional[str] = None
    forwarded_from: Optional[str] = None


def _message_type(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    msg = body.get("message") or {}
    return str(msg.get("type") or "").strip()


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

    customer = call.get("customer") or {}
    phone = customer.get("number") or ""

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

    name = structured.get("name") or structured.get("caller_name") or ""
    reason = structured.get("reason") or structured.get("issue") or msg.get("summary") or ""
    notes = structured.get("notes") or structured.get("details") or ""

    return {
        "call_id": call_id,
        "name": name,
        "phone": phone,
        "reason": reason,
        "notes": notes,
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
            phone_display = (payload.phone or "unknown").strip()
            reason_display = (payload.reason or "").strip()
            notes_display = (payload.notes or "").strip()
            alert_parts = [
                f"New AI call lead for {business_name}",
                f"Name: {name_display}",
                f"Phone: {phone_display}",
            ]
            if reason_display:
                alert_parts.append(f"Reason: {reason_display}")
            if notes_display:
                alert_parts.append(f"Notes: {notes_display}")
            send_sms(office_to, "\n".join(alert_parts))
            print(f"[VAPI] office SMS sent to {office_to} for tenant={tenant_id!r}", flush=True)
        else:
            print(f"[VAPI] no office_sms_to configured for tenant={tenant_id!r} - skipping SMS", flush=True)
    except Exception as e:
        print(f"[VAPI] office SMS error: {e}", flush=True)

    return {"status": "ok", "tenant_id": tenant_id}
