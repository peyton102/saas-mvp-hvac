# app/routers/vapi.py
import json as _json
import os
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import Any, Optional

from app.db import get_session
from app.models import Lead as LeadModel, Tenant, TenantSettings
from app.services.sms import get_brand_for_tenant, _office_destination_for_tenant, send_sms
from app.utils.phone import normalize_us_phone

router = APIRouter(prefix="", tags=["vapi"])


class VapiIntakePayload(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    language: Optional[str] = None
    called_number: Optional[str] = None    # call.phoneNumber.number — validated against TWILIO_PHONE_NUMBER
    phone_number_id: Optional[str] = None  # call.phoneNumberId — matched against Tenant.vapi_phone_number_id
    forwarded_from: Optional[str] = None   # call.forwardingPhoneNumber — matched against business_phone for tenant lookup


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

    # Vapi's internal phone number ID — matched against Tenant.vapi_phone_number_id.
    phone_number_id = call.get("phoneNumberId") or (call.get("phoneNumber") or {}).get("id") or ""
    print(f"[VAPI EXTRACT] phoneNumberId={call.get('phoneNumberId')!r} "
          f"phoneNumber.id={(call.get('phoneNumber') or {}).get('id')!r}", flush=True)

    # Log full call object keys + known nested objects so we can see exactly what Vapi sends
    print(f"[VAPI EXTRACT] call keys: {list(call.keys())}", flush=True)
    provider_details = call.get("phoneCallProviderDetails") or {}
    metadata = call.get("metadata") or {}
    debugging = call.get("inboundPhoneCallDebuggingArtifacts") or {}
    print(f"[VAPI EXTRACT] phoneCallProviderDetails={provider_details}", flush=True)
    print(f"[VAPI EXTRACT] metadata={metadata}", flush=True)
    print(f"[VAPI EXTRACT] inboundPhoneCallDebuggingArtifacts={debugging}", flush=True)
    print(f"[VAPI EXTRACT] forwardingPhoneNumber={call.get('forwardingPhoneNumber')!r} "
          f"forwardedFrom={call.get('forwardedFrom')!r}", flush=True)

    # forwarded_from — the original number the caller dialed before Twilio forwarding.
    # Priority:
    #   1. phoneCallProviderDetails.customParameters.forwarded_from — Vapi's standard location
    #      for customParameters passed via <Number customParameters="..."> TwiML.
    #   2. metadata.forwarded_from — Vapi may surface query params passed to inbound_call URL here.
    #   3. inboundPhoneCallDebuggingArtifacts.forwarded_from — another possible location.
    #   4. call.forwardingPhoneNumber / call.forwardedFrom — native Twilio forwarding fields.
    custom_params = provider_details.get("customParameters") or {}
    forwarded_from = (
        custom_params.get("forwarded_from")
        or metadata.get("forwarded_from")
        or debugging.get("forwarded_from")
        or call.get("forwardingPhoneNumber")
        or call.get("forwardedFrom")
        or ""
    )
    print(f"[VAPI EXTRACT] resolved forwarded_from={forwarded_from!r}", flush=True)

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
        "phone_number_id": phone_number_id,
        "forwarded_from": forwarded_from,
    }


def _resolve_tenant(
    called_number: Optional[str],
    phone_number_id: Optional[str],
    forwarded_from: Optional[str],
    session: Session,
) -> Optional[str]:
    """Identify the tenant from a VAPI end-of-call report.

    Step 1 — validate the call:
      Confirm call.phoneNumber.number matches TWILIO_PHONE_NUMBER env var (non-fatal).

    Step 2 — resolve by Vapi phone number ID:
      Match call.phoneNumberId against Tenant.vapi_phone_number_id. This is the most
      reliable method — each tenant stores the ID of their Vapi phone number in settings.

    Step 3 — resolve by forwarded_from:
      Fall back to matching call.forwardingPhoneNumber against TenantSettings.business_phone.

    Returns None if no tenant is found. Caller must handle None — never save without a tenant.
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

    # Step 2: resolve by Vapi phone number ID
    if phone_number_id:
        tenants = session.exec(
            select(Tenant).where(
                Tenant.vapi_phone_number_id != None,
                Tenant.vapi_phone_number_id != "",
            )
        ).all()
        candidates_id = {t.slug: t.vapi_phone_number_id for t in tenants}
        print(f"[VAPI] phone_number_id lookup: phone_number_id={phone_number_id!r} "
              f"candidates={candidates_id}", flush=True)
        for t in tenants:
            if t.vapi_phone_number_id == phone_number_id:
                print(f"[VAPI] tenant resolved via phone_number_id={phone_number_id!r} → {t.slug!r}", flush=True)
                return t.slug
        print(f"[VAPI] phone_number_id={phone_number_id!r} did not match any Tenant.vapi_phone_number_id — "
              f"trying forwarded_from fallback.", flush=True)
    else:
        print("[VAPI] phone_number_id missing — skipping ID-based lookup, trying forwarded_from.", flush=True)

    # Step 3: resolve by forwarded_from vs business_phone
    if not forwarded_from:
        print("[VAPI] ERROR: forwarded_from also empty — cannot resolve tenant. "
              "Set vapi_phone_number_id in tenant settings for reliable routing.", flush=True)
        return None

    norm_fwd = normalize_us_phone(forwarded_from) or forwarded_from
    rows = session.exec(select(TenantSettings)).all()
    candidates_bp = {s.tenant_id: normalize_us_phone(s.business_phone or "") for s in rows if s.business_phone}
    print(f"[VAPI] forwarded_from lookup: forwarded_from={forwarded_from!r} normalized={norm_fwd!r} "
          f"candidates={candidates_bp}", flush=True)

    for s in rows:
        if normalize_us_phone(s.business_phone or "") == norm_fwd:
            print(f"[VAPI] tenant resolved via forwarded_from={forwarded_from!r} → {s.tenant_id!r}", flush=True)
            return s.tenant_id

    print(f"[VAPI] ERROR: phone_number_id={phone_number_id!r} and forwarded_from={forwarded_from!r} both "
          f"unmatched — lead will NOT be saved.", flush=True)
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

    tenant_id = _resolve_tenant(payload.called_number, payload.phone_number_id, payload.forwarded_from, session)
    print(f"[VAPI] intake — phone_number_id={payload.phone_number_id!r} called_number={payload.called_number!r} "
          f"forwarded_from={payload.forwarded_from!r} tenant_id={tenant_id!r} "
          f"caller={payload.phone!r} name={payload.name!r}", flush=True)

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
