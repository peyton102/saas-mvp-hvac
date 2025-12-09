# app/routers/voice.py
from fastapi import APIRouter, Request, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response, PlainTextResponse
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse
import hashlib
from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Column, DateTime, text
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import config, storage
from app.db import get_session
from app.services.sms import send_sms
from app.models import WebhookDedup, Lead as LeadModel
from ..deps import get_tenant_id
from app.tenantold import brand
from app.utils.phone import normalize_us_phone

router = APIRouter(prefix="", tags=["voice"])

def utcnow():
    return datetime.now(tz=timezone.utc)

class ReviewRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
        default_factory=utcnow
    )
    tenant_id: str
    job_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    message: Optional[str] = None
    sms_sent: bool = False
# ----------------------- business hours / tz -----------------------

def _get_business_tz():
    try:
        return ZoneInfo(getattr(config, "TZ", "America/New_York"))
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")

BUSINESS_TZ = _get_business_tz()
BUSINESS_OPEN_HOUR  = int(getattr(config, "BUSINESS_OPEN_HOUR", 9))
BUSINESS_CLOSE_HOUR = int(getattr(config, "BUSINESS_CLOSE_HOUR", 17))
BUSINESS_OPEN_DOWS  = set(map(int, (getattr(config, "BUSINESS_OPEN_DOWS", "0,1,2,3,4").split(","))))

def _after_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now(BUSINESS_TZ)
    if now.weekday() not in BUSINESS_OPEN_DOWS:
        return True
    return not (BUSINESS_OPEN_HOUR <= now.hour < BUSINESS_CLOSE_HOUR)

# allow X-Force-After-Hours only outside prod
def _force_header_allowed() -> bool:
    return getattr(config, "ENV", "dev") != "prod"

from fastapi import Request

def _is_after_hours(request: Request) -> bool:
    # existing header override (works with tools that can set headers)
    force_hdr = (request.headers.get("x-force-after-hours") or "").strip() == "1"

    # NEW: query override so Twilio Console URL can force voicemail
    force_q = (request.query_params.get("force_after_hours") or "").strip().lower() in ("1", "true", "yes", "y")

    # Your existing business-hours check + allow-list for header if you have it
    try:
        header_ok = _force_header_allowed()  # keep if you already have this helper
    except NameError:
        header_ok = True  # safe default if you don't use that helper

    return _after_hours() or (force_hdr and header_ok) or force_q


# ----------------------- helpers -----------------------

def _tenant_from_headers(request: Request) -> str:
    auth = (request.headers.get("authorization") or "")
    api_key = (request.headers.get("x-api-key") or "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else api_key.strip()
    return getattr(config, "TENANT_KEYS", {}).get(token, "public")

def _external_url_for_signature(request: Request) -> str:
    hdr = request.headers
    proto = (hdr.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    host  = (hdr.get("x-forwarded-host")  or hdr.get("host") or request.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}{request.url.path}"

async def _verify_twilio_signature(request: Request) -> bool:
    if not getattr(config, "TWILIO_VALIDATE_SIGNATURES", False):
        return True
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        return False
    url = _external_url_for_signature(request)
    params = {}
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        try:
            form = await request.form()
            params = dict(form)
        except Exception:
            params = {}
    validator = RequestValidator(config.TWILIO_AUTH_TOKEN)
    return bool(validator.validate(url, params, signature))

def _dedupe_insert(session: Session, source: str, event_id: str) -> bool:
    try:
        session.add(WebhookDedup(source=source, event_id=event_id))
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False

def _log_lead_db(session: Session, phone: str, name: str, tenant_id: str):
    if not phone:
        return
    try:
        session.add(LeadModel(
            name=(name or "").strip(),
            phone=phone.strip(),
            email=None,
            message="Inbound call",
            tenant_id=tenant_id,
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[VOICE] DB lead insert error: {e}")

def _blocked_number(phone: str) -> bool:
    bl = (getattr(config, "SMS_BLOCKLIST", "") or "").split(",")
    return phone in [x.strip() for x in bl if x.strip()]

def _handle_voice_side_effects(from_number: str, caller_name: str, body: str, tenant_id: str):
    try:
        minutes = getattr(config, "ANTI_SPAM_MINUTES", 120)
        ok = False
        if from_number and not _blocked_number(from_number):
            if storage.sent_recently(from_number, minutes=minutes):
                print(f"[THROTTLE] Skipping SMS to {from_number} ({minutes}m)")
            else:
                try:
                    ok = send_sms(from_number, body)
                except Exception as e:
                    print(f"[VOICE] SMS send error: {e}")
        try:
            storage.save_lead(
                {"name": caller_name or "", "phone": from_number, "email": "", "message": "Inbound call", "tenant_id": tenant_id},
                sms_body=body,
                sms_sent=ok,
                source="voice",
            )
        except Exception:
            pass
    except Exception as e:
        print(f"[VOICE ERROR] {e}")

# ------------------------- routes -------------------------

@router.post("/twilio/voice")
async def twilio_voice(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    if not await _verify_twilio_signature(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Twilio signature")

    try:
        form = await request.form()
    except Exception as e:
        print(f"[VOICE] form parse error: {e}")
        form = {}

    from_num_raw = (form.get("From") or "").strip()
    from_num = normalize_us_phone(from_num_raw) or from_num_raw
    caller = (form.get("CallerName") or "").strip()
    call_sid = (form.get("CallSid") or "").strip()

    if call_sid:
        event_id = call_sid
    else:
        pairs = "&".join(f"{k}={form.get(k)}" for k in sorted(form.keys()))
        event_id = hashlib.sha256(pairs.encode("utf-8")).hexdigest()

    first_time = _dedupe_insert(session, source=f"twilio_voice:{tenant_id}", event_id=event_id)

    b = brand(tenant_id)
    first = caller.split(" ")[0] if caller else "there"
    msg = (
        f"Hey {first}, thanks for contacting {b['FROM_NAME']}! "
        f"Grab the next available slot here: {b['BOOKING_LINK']}. "
        f"Prefer a call? Reply here."
    )

    _log_lead_db(session, from_num, caller, tenant_id)

    after_hours = _is_after_hours(request)
    print(f"[VOICE] tenant={tenant_id} call_sid={call_sid or 'n/a'} first={first_time} from={from_num} after_hours={after_hours}")

    if not after_hours and first_time and from_num and not _blocked_number(from_num):
        background_tasks.add_task(_handle_voice_side_effects, from_num, caller, msg, tenant_id)

    vr = VoiceResponse()
    if after_hours:
        vr.say(f"Thanks for calling {b['FROM_NAME']}. We're currently unavailable. "
               "Please leave a brief message after the beep, and we'll text you our booking link.",
               voice="alice")
        vr.record(max_length=120, play_beep=True, action="/twilio/voice/recorded", method="POST")
        vr.say("Got it. Goodbye.")
        vr.hangup()
    else:
        vr.say(f"Thanks for calling {b['FROM_NAME']}. We just texted you our booking link. We'll be in touch shortly.",
               voice="alice")
        vr.hangup()

    return PlainTextResponse(str(vr), media_type="application/xml")

@router.post("/twilio/voice/recorded", response_class=PlainTextResponse)
async def twilio_voice_recorded(
    request: Request,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    if not await _verify_twilio_signature(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Twilio signature")

    try:
        form = await request.form()
    except Exception:
        form = {}

    from_num = normalize_us_phone((form.get("From") or "").strip()) or ""
    recording_url = (form.get("RecordingUrl") or "").strip()
    caller = (form.get("CallerName") or "").strip()

    if from_num:
        try:
            last = session.exec(
                select(LeadModel)
                .where(LeadModel.phone == from_num, LeadModel.tenant_id == tenant_id)
                .order_by(LeadModel.created_at.desc())
            ).first()
            if last:
                last.message = (last.message or "") + (f"\nVoicemail: {recording_url}" if recording_url else "")
                session.add(last); session.commit()
        except Exception as e:
            session.rollback()
            print(f"[VOICE] voicemail attach error: {e}")

    b = brand(tenant_id)
    body = f"Thanks for the voicemail! Book here: {b['BOOKING_LINK']}"
    try:
        if from_num and not _blocked_number(from_num) and _after_hours():
            if not storage.sent_recently(from_num, minutes=getattr(config, "ANTI_SPAM_MINUTES", 120)):
                send_sms(from_num, body)
    except Exception as e:
        print(f"[VOICE] voicemail SMS error: {e}")

    vr = VoiceResponse()
    vr.say("Thanks. We just texted you our booking link. Goodbye.", voice="alice")
    return PlainTextResponse(str(vr), media_type="application/xml")

@router.get("/twilio/voice")
def twilio_voice_get():
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Thanks for calling {config.FROM_NAME}. We just texted you our booking link. We'll be in touch shortly.</Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")

# --- DEBUG helpers (protected by /debug/* middleware) ---

@router.get("/debug/twilio-token")
def debug_twilio_token(request: Request):
    tok = (getattr(config, "TWILIO_AUTH_TOKEN", "") or "")
    return {
        "validate": bool(getattr(config, "TWILIO_VALIDATE_SIGNATURES", False)),
        "token_len": len(tok),
        "host": request.headers.get("host"),
    }

@router.get("/debug/twilio-sig")
def debug_twilio_sig(request: Request, From: str, CallerName: str):
    base = f"{request.url.scheme}://{request.headers.get('host')}"
    url = f"{base}/twilio/voice"
    params = {"From": From, "CallerName": CallerName}
    sig = RequestValidator(config.TWILIO_AUTH_TOKEN).compute_signature(url, params)
    return {"url": url, "sig": sig}

@router.get("/debug/twilio-sig-recorded")
def debug_twilio_sig_recorded(request: Request, From: str, CallerName: str, RecordingUrl: str):
    base = f"{request.url.scheme}://{request.headers.get('host')}"
    url = f"{base}/twilio/voice/recorded"
    params = {"From": From, "CallerName": CallerName, "RecordingUrl": RecordingUrl}
    sig = RequestValidator(config.TWILIO_AUTH_TOKEN).compute_signature(url, params)
    return {"url": url, "sig": sig}
