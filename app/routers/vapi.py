# app/routers/vapi.py
import json as _json
import os
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import Any, Optional

from app.call_cache import lookup as cache_lookup, evict as cache_evict
from app.db import get_session
from app.models import Lead as LeadModel, TenantSettings
from app.services.sms import get_brand_for_tenant, _office_destination_for_tenant, send_sms
from app.utils.phone import normalize_us_phone

router = APIRouter(prefix="", tags=["vapi"])


class VapiIntakePayload(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    language: Optional[str] = None
    called_number: Optional[str] = None   # call.phoneNumber.number — validated against TWILIO_PHONE_NUMBER
    forwarded_from: Optional[str] = None  # resolved from cache (call.id) or Twilio fields


def _extract_from_vapi_body(body: dict) -> dict:
    """
    VAPI sends end-of-call webhooks as a nested structure, not the flat fields
    this endpoint originally expected. This function normalises both formats:

    Flat (custom POST from VAPI tool/function):
      { "name": "...", "phone": "...", "reason": "...", "forwarded_from": "..." }

    VAPI end-of-call report (sent automatically when call ends):
      {
        "message": {
          "type": "end-of-call-report",
          "call": {
            "customer": { "number": "+1..." },
            "phoneNumber": { "number": "+1..." }   ← the Twilio number
          },
          "analysis": { "structuredData": { ... } },
          "summary": "..."
        }
      }

    Returns a flat dict with keys: name, phone, reason, notes, forwarded_from.
    """
    # Already flat — used when VAPI is configured with a custom function/tool call
    if "message" not in body:
        return body

    msg = body.get("message") or {}
    call = msg.get("call") or {}
    analysis = msg.get("analysis") or {}
    structured = analysis.get("structuredData") or {}

    # Caller's number
    customer = call.get("customer") or {}
    phone = (
        customer.get("number")
        or (call.get("phoneNumber") or {}).get("number")
        or ""
    )

    # The Twilio/VAPI number that received the call — validated against TWILIO_PHONE_NUMBER env var.
    called_number = (call.get("phoneNumber") or {}).get("number") or ""

    # call.id matches the originating Twilio CallSid — use it to look up ForwardedFrom
    # from the in-memory cache written by /twilio/voice when the call came in.
    call_id = call.get("id") or ""
    print(f"[VAPI EXTRACT] call keys: {list(call.keys())}", flush=True)
    print(f"[VAPI EXTRACT] call.id={call_id!r} called_number={called_number!r} "
          f"forwardingPhoneNumber={call.get('forwardingPhoneNumber')!r} "
          f"forwardedFrom={call.get('forwardedFrom')!r}", flush=True)

    # forwarded_from — priority:
    #   1. In-memory cache keyed by CallSid (most reliable — set by /twilio/voice)
    #   2. call.forwardingPhoneNumber / call.forwardedFrom — native Twilio fields as fallback
    cached = cache_lookup(call_id)
    forwarded_from = (
        cached
        or call.get("forwardingPhoneNumber")
        or call.get("forwardedFrom")
        or ""
    )
    if cached:
        cache_evict(call_id)
    print(f"[VAPI EXTRACT] forwarded_from={forwarded_from!r} "
          f"(source={'cache' if cached else 'twilio_field'})", flush=True)

    # Prefer structuredData fields extracted by the assistant, fall back to summary
    name    = structured.get("name")    or structured.get("caller_name")   or ""
    reason  = structured.get("reason")  or structured.get("issue")         or msg.get("summary") or ""
    notes   = structured.get("notes")   or structured.get("details")       or ""

    return {
        "name": name,
        "phone": phone,
        "reason": reason,
        "notes": notes,
        "called_number": called_number,
        "forwarded_from": forwarded_from,
    }


def _resolve_tenant(called_number: Optional[str], forwarded_from: Optional[str], session: Session) -> Optional[str]:
    """Identify the tenant from a VAPI end-of-call report.

    Step 1 — validate the call:
      Confirm call.phoneNumber.number matches TWILIO_PHONE_NUMBER env var (non-fatal).

    Step 2 — resolve by forwarded_from:
      Match forwarded_from (sourced from in-memory cache or Twilio native fields) against
      TenantSettings.business_phone. Returns None if no match — never falls back to 'default'.
    """
    twilio_number = normalize_us_phone(os.getenv("TWILIO_PHONE_NUMBER", "").strip()) or ""

    # Step 1: validate
    if twilio_number:
        norm_called = normalize_us_phone(called_number or "") or (called_number or "")
        if norm_called != twilio_number:
            print(f"[VAPI] WARNING: called_number={called_number!r} does not match "
                  f"TWILIO_PHONE_NUMBER={twilio_number!r} — unexpected origin.", flush=True)
        else:
            print(f"[VAPI] call validated: called_number={called_number!r} matches TWILIO_PHONE_NUMBER", flush=True)
    else:
        print("[VAPI] WARNING: TWILIO_PHONE_NUMBER env var not set — skipping call validation.", flush=True)

    # Step 2: resolve by forwarded_from vs business_phone
    if not forwarded_from:
        print("[VAPI] ERROR: forwarded_from empty — cannot resolve tenant. "
              "Check that /twilio/voice is storing ForwardedFrom in the cache for this CallSid.", flush=True)
        return None

    norm_fwd = normalize_us_phone(forwarded_from) or forwarded_from
    rows = session.exec(select(TenantSettings)).all()
    candidates = {s.tenant_id: normalize_us_phone(s.business_phone or "") for s in rows if s.business_phone}
    print(f"[VAPI] tenant lookup: forwarded_from={forwarded_from!r} normalized={norm_fwd!r} "
          f"candidates={candidates}", flush=True)

    for s in rows:
        if normalize_us_phone(s.business_phone or "") == norm_fwd:
            print(f"[VAPI] tenant resolved: forwarded_from={forwarded_from!r} → {s.tenant_id!r}", flush=True)
            return s.tenant_id

    print(f"[VAPI] ERROR: forwarded_from={forwarded_from!r} (normalized={norm_fwd!r}) unmatched — "
          f"lead will NOT be saved.", flush=True)
    return None


@router.post("/vapi/intake")
async def vapi_intake(
    request: Request,
    session: Session = Depends(get_session),
):
    # Log raw body — this is the first thing to check when data isn't arriving
    try:
        raw_body = await request.body()
        raw_text = raw_body.decode("utf-8", errors="replace")
        print(f"[VAPI] raw body received: {raw_text[:2000]}", flush=True)
        body: Any = _json.loads(raw_text) if raw_text.strip() else {}
    except Exception as e:
        print(f"[VAPI] body parse error: {e}", flush=True)
        body = {}

    # Normalise flat vs VAPI end-of-call-report format
    flat = _extract_from_vapi_body(body) if isinstance(body, dict) else {}
    payload = VapiIntakePayload(**{k: v for k, v in flat.items() if k in VapiIntakePayload.model_fields})

    tenant_id = _resolve_tenant(payload.called_number, payload.forwarded_from, session)
    print(f"[VAPI] intake — called_number={payload.called_number!r} forwarded_from={payload.forwarded_from!r} "
          f"tenant_id={tenant_id!r} caller={payload.phone!r} name={payload.name!r}", flush=True)

    if tenant_id is None:
        print(f"[VAPI] DROPPING lead — tenant unresolved. "
              f"caller={payload.phone!r} name={payload.name!r} reason={payload.reason!r} "
              f"notes={payload.notes!r} forwarded_from={payload.forwarded_from!r}", flush=True)
        return {"status": "error", "detail": "tenant not resolved"}

    # Build message from reason + notes
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

    # Office SMS — send everything the AI collected to the tenant's office number
    try:
        office_to = _office_destination_for_tenant(tenant_id)
        if office_to:
            b = get_brand_for_tenant(tenant_id)
            business_name = b.get("business_name") or tenant_id
            name_display = (payload.name or "Unknown").strip()
            phone_display = (payload.phone or "unknown").strip()
            reason_display = (payload.reason or "").strip()
            notes_display = (payload.notes or "").strip()
            alert_parts = [f"New AI call lead for {business_name}",
                           f"Name: {name_display}",
                           f"Phone: {phone_display}"]
            if reason_display:
                alert_parts.append(f"Reason: {reason_display}")
            if notes_display:
                alert_parts.append(f"Notes: {notes_display}")
            send_sms(office_to, "\n".join(alert_parts))
            print(f"[VAPI] office SMS sent to {office_to} for tenant={tenant_id!r}", flush=True)
        else:
            print(f"[VAPI] no office_sms_to configured for tenant={tenant_id!r} — skipping SMS", flush=True)
    except Exception as e:
        print(f"[VAPI] office SMS error: {e}", flush=True)

    return {"status": "ok", "tenant_id": tenant_id}
