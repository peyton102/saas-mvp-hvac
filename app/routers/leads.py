# app/routers/leads.py
from fastapi import APIRouter
from app import config, storage
from app.services.sms import send_sms
from app.schemas import LeadIn, LeadOut
from app.utils.phone import normalize_us_phone

router = APIRouter(prefix="", tags=["leads"])

@router.post("/lead", response_model=LeadOut)
def create_lead(lead: LeadIn):
    e164 = normalize_us_phone(lead.phone)

    first = (lead.name or "").split(" ")[0] if lead.name else "there"
    body = (
        f"Hey {first}, thanks for contacting {config.FROM_NAME}! "
        f"Grab the next available slot here: {config.BOOKING_LINK}. "
        f"Prefer a call? Reply here."
    )

    # throttle duplicate texts
    if storage.sent_recently(e164, minutes=config.ANTI_SPAM_MINUTES):
        print(f"[THROTTLE] Skipping SMS to {e164} (last sent within {config.ANTI_SPAM_MINUTES} min)")
        ok = False
        storage.save_lead({**lead.model_dump(), "phone": e164}, sms_body=body, sms_sent=ok, source="api")
        return LeadOut(sms_sent=ok)

    ok = send_sms(e164, body)
    storage.save_lead({**lead.model_dump(), "phone": e164}, sms_body=body, sms_sent=ok, source="api")
    return LeadOut(sms_sent=ok)

@router.get("/debug/leads")
def debug_leads(limit: int = 20):
    items = storage.read_leads(limit)
    return {"count": len(items), "items": items}
