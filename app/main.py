from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from app import config
from app.services.sms import send_sms
from app import storage
import phonenumbers
from fastapi import Request
from fastapi.responses import Response

app = FastAPI(title="HVAC SaaS Bot (MVP)", version="0.1.0")

@app.get("/")
def root():
    return {"ok": True, "msg": "root alive"}

@app.get("/health")
def health():
    return {"ok": True, "env": config.ENV}

class LeadIn(BaseModel):
    name: str | None = None
    phone: str
    email: EmailStr | None = None
    message: str | None = None

class LeadOut(BaseModel):
    sms_sent: bool

def normalize_us_phone(raw: str) -> str:
    try:
        pn = phonenumbers.parse(raw, "US")
        if not phonenumbers.is_possible_number(pn) or not phonenumbers.is_valid_number(pn):
            raise ValueError("invalid")
        return phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid phone number. Use format like +18145551234.")

@app.post("/lead", response_model=LeadOut)
def create_lead(lead: LeadIn):
    first = (lead.name or "").split(" ")[0] if lead.name else "there"
    body = (
        f"Hey {first}, thanks for contacting {config.FROM_NAME}! "
        f"Grab the next available slot here: {config.BOOKING_LINK}. "
        f"Prefer a call? Reply here."
    )

    # THROTTLE: don't re-text the same phone within the window
    if storage.sent_recently(lead.phone, minutes=config.ANTI_SPAM_MINUTES):
        ok = False
        storage.save_lead(lead.model_dump(), sms_body=body, sms_sent=ok, source="api")
        return LeadOut(sms_sent=ok)

    ok = send_sms(lead.phone, body)
    storage.save_lead(lead.model_dump(), sms_body=body, sms_sent=ok, source="api")
    return LeadOut(sms_sent=ok)

@app.get("/debug/leads")
def debug_leads(limit: int = 20):
    return {"count": len(storage.read_leads(limit)), "items": storage.read_leads(limit)}
@app.post("/twilio/voice")
async def twilio_voice(request: Request):
    """
    Twilio Voice webhook: when someone calls your Twilio number,
    we (dry) text them the booking link, save a lead, and speak a message.
    """
    form = await request.form()
    from_number = (form.get("From") or "").strip()
    caller_name = (form.get("CallerName") or "").strip()

    first = caller_name.split(" ")[0] if caller_name else "there"
    body = (
        f"Hey {first}, thanks for contacting {config.FROM_NAME}! "
        f"Grab the next available slot here: {config.BOOKING_LINK}. "
        f"Prefer a call? Reply here."
    )

    # throttle: don't re-text the same caller within the window
    minutes = getattr(config, "ANTI_SPAM_MINUTES", 120)
    if storage.sent_recently(from_number, minutes=minutes):
        ok = False
    else:
        ok = send_sms(from_number, body)

    # save the lead (source=voice)
    storage.save_lead(
        {"name": caller_name or "", "phone": from_number, "email": "", "message": "Inbound call"},
        sms_body=body,
        sms_sent=ok,
        source="voice",
    )

    # tell Twilio what to do with the call
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Thanks for calling {config.FROM_NAME}. We just texted you our booking link. We'll be in touch shortly.</Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")
