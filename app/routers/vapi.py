# app/routers/vapi.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
from typing import Optional

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
    forwarded_from: Optional[str] = None


def _resolve_tenant(forwarded_from: Optional[str], session: Session) -> str:
    """Match forwarded_from against TenantSettings.business_phone. Falls back to 'default'.

    forwarded_from must be sent by the VAPI assistant in the POST payload. If it is
    missing, all leads will be attributed to 'default' instead of the correct tenant.
    Check VAPI assistant config if you see tenant_id='default' in logs.
    """
    if not forwarded_from:
        print("[VAPI] WARNING: forwarded_from missing — cannot resolve tenant, falling back to 'default'. "
              "Check that the VAPI assistant is sending forwarded_from in its POST payload.", flush=True)
        return "default"
    norm = normalize_us_phone(forwarded_from) or forwarded_from
    rows = session.exec(
        select(TenantSettings).where(
            TenantSettings.business_phone != None,
            TenantSettings.business_phone != "",
        )
    ).all()
    for s in rows:
        if normalize_us_phone(s.business_phone or "") == norm:
            print(f"[VAPI] tenant resolved: forwarded_from={forwarded_from!r} → tenant_id={s.tenant_id!r}", flush=True)
            return s.tenant_id
    print(f"[VAPI] WARNING: forwarded_from={forwarded_from!r} (normalized={norm!r}) did not match any "
          f"TenantSettings.business_phone — falling back to 'default'. "
          f"Make sure the tenant's business_phone is set in TenantSettings.", flush=True)
    return "default"


@router.post("/vapi/intake")
def vapi_intake(
    payload: VapiIntakePayload,
    session: Session = Depends(get_session),
):
    tenant_id = _resolve_tenant(payload.forwarded_from, session)
    print(f"[VAPI] intake — forwarded_from={payload.forwarded_from!r} tenant_id={tenant_id!r} "
          f"caller={payload.phone!r} name={payload.name!r}", flush=True)

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
