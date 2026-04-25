# app/routers/vapi.py
import json as _json
import os
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import Any, Optional

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
    forwarded_from: Optional[str] = None  # call.forwardingPhoneNumber — matched against business_phone for tenant lookup


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

    # The original number the caller dialed before Twilio forwarding kicked in.
    # Matched against TenantSettings.business_phone to identify the tenant.
    forwarded_from = call.get("forwardingPhoneNumber") or ""

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


def _resolve_tenant(called_number: Optional[str], forwarded_from: Optional[str], session: Session) -> str:
    """Identify the tenant from a VAPI end-of-call report.

    Step 1 — validate the call:
      Confirm call.phoneNumber.number matches TWILIO_PHONE_NUMBER env var.
      Logs a warning if it doesn't, but continues (non-fatal).

    Step 2 — identify the tenant:
      Match forwarded_from (call.forwardingPhoneNumber) against TenantSettings.business_phone.
      If no match or forwarded_from is absent, falls back to 'default'.
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

    # Step 2: resolve tenant
    if not forwarded_from:
        print("[VAPI] forwarded_from missing — cannot identify tenant, falling back to 'default'.", flush=True)
        return "default"

    norm_fwd = normalize_us_phone(forwarded_from) or forwarded_from
    rows = session.exec(
        select(TenantSettings).where(
            TenantSettings.business_phone != None,
            TenantSettings.business_phone != "",
        )
    ).all()
    for s in rows:
        if normalize_us_phone(s.business_phone or "") == norm_fwd:
            print(f"[VAPI] tenant resolved: forwarded_from={forwarded_from!r} → tenant_id={s.tenant_id!r}", flush=True)
            return s.tenant_id

    print(f"[VAPI] WARNING: forwarded_from={forwarded_from!r} (normalized={norm_fwd!r}) did not match any "
          f"TenantSettings.business_phone — falling back to 'default'.", flush=True)
    return "default"


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

    # Office SMS
    try:
        office_to = _office_destination_for_tenant(tenant_id)
        if office_to:
            b = get_brand_for_tenant(tenant_id)
            business_name = b.get("business_name") or tenant_id
            name_display = (payload.name or "Unknown").strip()
            phone_display = (payload.phone or "unknown").strip()
            reason_display = (payload.reason or "no reason given").strip()
            alert = (
                f"New lead from {name_display} at {phone_display} — "
                f"{reason_display}. They called {business_name}."
            )
            send_sms(office_to, alert)
    except Exception as e:
        print(f"[VAPI] office SMS error: {e}", flush=True)

    return {"status": "ok", "tenant_id": tenant_id}
