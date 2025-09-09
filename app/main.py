from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr
from app import config, storage
from app.services.sms import send_sms
import phonenumbers

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
    """Normalize US/CA numbers to E.164. Raise 422 if invalid."""
    try:
        pn = phonenumbers.parse(raw, "US")
        if not phonenumbers.is_possible_number(pn) or not phonenumbers.is_valid_number(pn):
            raise ValueError("invalid")
        return phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        # If the user already sent E.164 like +18145551234 but parse failed for any reason, keep error clear:
        raise HTTPException(status_code=422, detail="Invalid phone number. Use format like +18145551234.")


@app.post("/lead", response_model=LeadOut)
def create_lead(lead: LeadIn):
    # Normalize phone to E.164 for clean storage and sending
    e164 = normalize_us_phone(lead.phone)

    first = (lead.name or "").split(" ")[0] if lead.name else "there"
    body = (
        f"Hey {first}, thanks for contacting {config.FROM_NAME}! "
        f"Grab the next available slot here: {config.BOOKING_LINK}. "
        f"Prefer a call? Reply here."
    )

    # THROTTLE: don't re-text the same phone within the window
    if storage.sent_recently(e164, minutes=config.ANTI_SPAM_MINUTES):
        print(f"[THROTTLE] Skipping SMS to {e164} (last sent within {config.ANTI_SPAM_MINUTES} min)")
        ok = False
        storage.save_lead({**lead.model_dump(), "phone": e164}, sms_body=body, sms_sent=ok, source="api")
        return LeadOut(sms_sent=ok)

    ok = send_sms(e164, body)
    storage.save_lead({**lead.model_dump(), "phone": e164}, sms_body=body, sms_sent=ok, source="api")
    return LeadOut(sms_sent=ok)


@app.get("/debug/leads")
def debug_leads(limit: int = 20):
    items = storage.read_leads(limit)
    return {"count": len(items), "items": items}


@app.post("/twilio/voice")
async def twilio_voice(request: Request):
    """
    Twilio Voice webhook: on inbound call, text the booking link (dry-run in dev),
    save a lead, and ALWAYS return valid TwiML so Twilio doesn't say "application error".
    """
    # Parse form safely
    try:
        form = await request.form()
    except Exception as e:
        print(f"[VOICE] form parse error: {e}")
        form = {}

    from_number = (form.get("From") or "").strip()
    caller_name = (form.get("CallerName") or "").strip()

    # Try to show a friendly first name if Twilio supplies one
    first = caller_name.split(" ")[0] if caller_name else "there"
    body = (
        f"Hey {first}, thanks for contacting {config.FROM_NAME}! "
        f"Grab the next available slot here: {config.BOOKING_LINK}. "
        f"Prefer a call? Reply here."
    )

    ok = False
    try:
        minutes = getattr(config, "ANTI_SPAM_MINUTES", 120)

        # Twilio typically sends E.164 already (e.g., +18145551234). If it's missing, we just skip normalize.
        if from_number:
            if storage.sent_recently(from_number, minutes=minutes):
                print(f"[THROTTLE] Skipping SMS to {from_number} ({minutes}m)")
            else:
                ok = send_sms(from_number, body)

        # Save lead regardless so we capture the missed call
        storage.save_lead(
            {"name": caller_name or "", "phone": from_number, "email": "", "message": "Inbound call"},
            sms_body=body,
            sms_sent=ok,
            source="voice",
        )
    except Exception as e:
        # Never crash; log and return TwiML
        print(f"[VOICE ERROR] {e}")

    # Always return valid TwiML
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Thanks for calling {config.FROM_NAME}. We just texted you our booking link. We'll be in touch shortly.</Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")
