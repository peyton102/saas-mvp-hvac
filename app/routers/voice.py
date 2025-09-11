# app/routers/voice.py
from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import Response
from app import config, storage
from app.services.sms import send_sms

router = APIRouter(prefix="", tags=["voice"])

def _handle_voice_side_effects(from_number: str, caller_name: str, body: str):
    """Run outside response path so Twilio never times out."""
    try:
        minutes = getattr(config, "ANTI_SPAM_MINUTES", 120)
        ok = False

        if from_number:
            if storage.sent_recently(from_number, minutes=minutes):
                print(f"[THROTTLE] Skipping SMS to {from_number} ({minutes}m)")
            else:
                ok = send_sms(from_number, body)

        storage.save_lead(
            {"name": caller_name or "", "phone": from_number, "email": "", "message": "Inbound call"},
            sms_body=body,
            sms_sent=ok,
            source="voice",
        )
    except Exception as e:
        print(f"[VOICE ERROR] {e}")


@router.post("/twilio/voice")
async def twilio_voice(request: Request, background_tasks: BackgroundTasks):
    """
    Twilio Voice webhook: return TwiML immediately; do SMS/save in background.
    """
    try:
        form = await request.form()
    except Exception as e:
        print(f"[VOICE] form parse error: {e}")
        form = {}

    from_number = (form.get("From") or "").strip()
    caller_name = (form.get("CallerName") or "").strip()
    first = caller_name.split(" ")[0] if caller_name else "there"

    body = (
        f"Hey {first}, thanks for contacting {config.FROM_NAME}! "
        f"Grab the next available slot here: {config.BOOKING_LINK}. "
        f"Prefer a call? Reply here."
    )

    background_tasks.add_task(_handle_voice_side_effects, from_number, caller_name, body)

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Thanks for calling {config.FROM_NAME}. We just texted you our booking link. We'll be in touch shortly.</Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


# Optional GET fallback if webhook is accidentally set to GET
@router.get("/twilio/voice")
def twilio_voice_get():
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Thanks for calling {config.FROM_NAME}. We just texted you our booking link. We'll be in touch shortly.</Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")
