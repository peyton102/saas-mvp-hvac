# app/routers/voice.py
import os
import urllib.parse
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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import config, storage
from app.db import get_session
from app.services.sms import send_sms, get_brand_for_tenant, _office_destination_for_tenant
from app.models import WebhookDedup, Lead as LeadModel, Tenant, TenantSettings
from app.utils.phone import normalize_us_phone
from ..deps import get_tenant_id as _get_tenant_id_strict


async def get_tenant_id_public(
    request: Request,
    tenant: Optional[str] = None,
    session: Session = Depends(get_session),
) -> str:
    """
    Tenant resolver for public Twilio webhooks.
    Priority:
      1) request.state.tenant_id (set by middleware)
      2) X-API-Key header via TENANT_KEYS
      3) Authorization: Bearer via TENANT_KEYS
      4) ?tenant= query param
      5) Twilio 'ForwardedFrom' matched against TenantSettings.business_phone (call forwarding)
      6) Twilio 'To' matched against TenantSettings.twilio_number
      7) Twilio 'To' matched against Tenant.phone (legacy)
      8) 'default'
    """
    state_tenant = getattr(request.state, "tenant_id", None)
    if state_tenant and state_tenant != "public":
        return str(state_tenant)

    keys = getattr(config, "TENANT_KEYS", None)
    if not isinstance(keys, dict) and hasattr(config, "settings"):
        keys = getattr(config.settings, "TENANT_KEYS", None)
    keys = keys or {}

    api_key = (request.headers.get("x-api-key") or "").strip()
    if api_key and api_key in keys:
        return str(keys[api_key])

    auth = (request.headers.get("authorization") or "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token in keys:
            return str(keys[token])

    tenant_q = request.query_params.get("tenant", "").strip()
    if tenant_q:
        return tenant_q

    try:
        form = await request.form()

        # Call-forwarding path: ForwardedFrom is the owner's real number the customer originally dialed
        forwarded_raw = (form.get("ForwardedFrom") or "").strip()
        if forwarded_raw:
            forwarded_norm = normalize_us_phone(forwarded_raw) or forwarded_raw
            settings_rows = session.exec(
                select(TenantSettings).where(TenantSettings.business_phone != None, TenantSettings.business_phone != "")
            ).all()
            for s in settings_rows:
                if normalize_us_phone(s.business_phone or "") == forwarded_norm:
                    print(f"[VOICE] tenant resolved via ForwardedFrom={forwarded_raw} → {s.tenant_id}", flush=True)
                    return s.tenant_id

        # Direct-call path: To is the Twilio number
        to_raw = (form.get("To") or "").strip()
        if to_raw:
            to_norm = normalize_us_phone(to_raw) or to_raw
            settings_rows = session.exec(
                select(TenantSettings).where(TenantSettings.twilio_number != None, TenantSettings.twilio_number != "")
            ).all()
            for s in settings_rows:
                if normalize_us_phone(s.twilio_number or "") == to_norm:
                    return s.tenant_id
            # Legacy: match against Tenant.phone
            tenants = session.exec(
                select(Tenant).where(Tenant.phone != None, Tenant.phone != "")
            ).all()
            for t in tenants:
                if normalize_us_phone(t.phone or "") == to_norm:
                    return t.slug
    except Exception as e:
        session.rollback()
        print(f"[VOICE] tenant lookup error: {e}", flush=True)

    return "default"

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
    now = now or datetime.now(timezone.utc)

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
    # Render sets x-forwarded-proto but not x-forwarded-host; fall back to host header
    proto = (hdr.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    host = (hdr.get("host") or request.url.netloc).split(",")[0].strip()
    url = f"{proto}://{host}{request.url.path}"
    # Twilio signs the full URL including query string — must include it or sig fails
    qs = request.url.query
    if qs:
        url += f"?{qs}"
    return url

async def _verify_twilio_signature(request: Request) -> bool:
    if not getattr(config, "TWILIO_VALIDATE_SIGNATURES", False):
        return True
    auth_token = (getattr(config, "TWILIO_AUTH_TOKEN", "") or "").strip()
    if not auth_token:
        print("[VOICE] WARNING: TWILIO_AUTH_TOKEN not set — skipping signature validation", flush=True)
        return True
    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        print("[VOICE] WARNING: request missing X-Twilio-Signature header", flush=True)
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
    validator = RequestValidator(auth_token)
    result = bool(validator.validate(url, params, signature))
    if not result:
        print(f"[VOICE] Twilio signature mismatch — url={url} sig={signature[:20]}...", flush=True)
    return result

def _dedupe_insert(session: Session, source: str, event_id: str) -> bool:
    try:
        session.rollback()  # clear any aborted transaction left by earlier errors
        session.add(WebhookDedup(source=source, event_id=event_id))
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False
    except Exception as e:
        session.rollback()
        print(f"[DEDUPE] insert error: {e}", flush=True)
        return False

def _log_lead_db(session: Session, phone: str, name: str, tenant_id: str, source: Optional[str] = None):
    if not phone:
        return
    try:
        session.add(LeadModel(
            name=(name or "").strip(),
            phone=phone.strip(),
            email=None,
            message="Inbound call",
            tenant_id=tenant_id,
            source=source,
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[VOICE] DB lead insert error: {e}")

def _blocked_number(phone: str) -> bool:
    bl = (getattr(config, "SMS_BLOCKLIST", "") or "").split(",")
    return phone in [x.strip() for x in bl if x.strip()]

def _handle_voice_side_effects(from_number: str, caller_name: str, body: str, tenant_id: str, business_name: str = ""):
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
        # Office alert for forwarded missed call
        try:
            office_to = _office_destination_for_tenant(tenant_id)
            if office_to:
                label = business_name or tenant_id
                alert = f"Missed call from {from_number}" + (f" ({caller_name})" if caller_name else "") + f" — {label}"
                send_sms(office_to, alert)
        except Exception as e:
            print(f"[VOICE] office alert error: {e}")
    except Exception as e:
        print(f"[VOICE ERROR] {e}")

# ------------------------- routes -------------------------

@router.post("/twilio/voice")
async def twilio_voice(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id_public),
):
    if not await _verify_twilio_signature(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Twilio signature")

    try:
        form = await request.form()
    except Exception as e:
        print(f"[VOICE] form parse error: {e}")
        form = {}

    print(
        f"[VOICE RAW] From={form.get('From')!r} To={form.get('To')!r} "
        f"ForwardedFrom={form.get('ForwardedFrom')!r} Called={form.get('Called')!r} "
        f"Direction={form.get('Direction')!r} full_form={dict(form)}",
        flush=True,
    )

    from_num_raw = (form.get("From") or "").strip()
    from_num = normalize_us_phone(from_num_raw) or from_num_raw
    caller = (form.get("CallerName") or "").strip()
    call_sid = (form.get("CallSid") or "").strip()
    forwarded_from_raw = (form.get("ForwardedFrom") or "").strip()

    if call_sid:
        event_id = call_sid
    else:
        pairs = "&".join(f"{k}={form.get(k)}" for k in sorted(form.keys()))
        event_id = hashlib.sha256(pairs.encode("utf-8")).hexdigest()

    first_time = _dedupe_insert(session, source=f"twilio_voice:{tenant_id}", event_id=event_id)

    b = get_brand_for_tenant(tenant_id)
    business_name = b.get("business_name") or tenant_id
    booking_link = b.get("booking_link") or ""
    print(f"[VOICE] brand lookup — tenant_id={tenant_id!r} business_name={business_name!r}", flush=True)

    after_hours = _is_after_hours(request)
    _log_lead_db(session, from_num, caller, tenant_id, source="missed_call" if after_hours else None)
    print(f"[VOICE] tenant={tenant_id} call_sid={call_sid or 'n/a'} first={first_time} "
          f"from={from_num} forwarded_from={forwarded_from_raw!r} after_hours={after_hours}")

    # --- Forward to VAPI if configured ---
    # Redirect the live call to Vapi's inbound call URL so Vapi takes over handling.
    # forwarded_from is appended as a query parameter so Vapi includes it in the
    # end-of-call report, where /vapi/intake reads it for tenant resolution.
    vapi_phone = os.getenv("VAPI_PHONE_NUMBER", "").strip()
    if vapi_phone:
        vapi_url = "https://api.vapi.ai/twilio/inbound_call"
        if forwarded_from_raw:
            vapi_url += "?" + urllib.parse.urlencode({"forwarded_from": forwarded_from_raw})
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f'<Redirect method="POST">{vapi_url}</Redirect>'
            "</Response>"
        )
        print(f"[VOICE] redirecting to VAPI inbound_call URL, forwarded_from={forwarded_from_raw!r}", flush=True)
        return PlainTextResponse(twiml, media_type="application/xml")

    # --- Default flow (no VAPI phone set, or direct call with no ForwardedFrom) ---
    first = caller.split(" ")[0] if caller else "there"
    msg = (
        f"Hey {first}, thanks for contacting {business_name}! "
        f"{booking_link} "
        f"Prefer a call? Reply here."
    )

    if not after_hours and first_time and from_num and not _blocked_number(from_num):
        background_tasks.add_task(_handle_voice_side_effects, from_num, caller, msg, tenant_id, business_name)

    vr = VoiceResponse()
    if after_hours:
        vr.say("Thanks for calling. We're currently unavailable. "
               "Please leave a brief message after the beep.",
               voice="alice")
        vr.record(max_length=120, play_beep=True, action="/twilio/voice/recorded", method="POST")
        vr.say("Got it. Goodbye.")
        vr.hangup()
    else:
        vr.say("Thanks for calling. We just texted you our booking link. We'll be in touch shortly.",
               voice="alice")
        vr.hangup()

    return PlainTextResponse(str(vr), media_type="application/xml")

@router.post("/twilio/voice/recorded", response_class=PlainTextResponse)
async def twilio_voice_recorded(
    request: Request,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id_public),
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
                last.source = "missed_call"
                session.add(last); session.commit()
            else:
                session.add(LeadModel(
                    name=(caller or "").strip(),
                    phone=from_num,
                    email=None,
                    message=f"Voicemail: {recording_url}" if recording_url else "Voicemail",
                    tenant_id=tenant_id,
                    source="missed_call",
                ))
                session.commit()
        except Exception as e:
            session.rollback()
            print(f"[VOICE] voicemail attach error: {e}")

    b = get_brand_for_tenant(tenant_id)
    business_name = b.get("business_name") or tenant_id
    print(f"[RECORDED] brand lookup — tenant_id={tenant_id!r} business_name={business_name!r}", flush=True)
    body = "Hi! We missed your call and want to make sure you get taken care of. We'll be in touch shortly."
    try:
        if from_num and not _blocked_number(from_num) and _after_hours():
            if not storage.sent_recently(from_num, minutes=getattr(config, "ANTI_SPAM_MINUTES", 120)):
                send_sms(from_num, body)
    except Exception as e:
        print(f"[VOICE] voicemail SMS error: {e}")

    # Alert the office that a voicemail was left
    try:
        office_to = _office_destination_for_tenant(tenant_id)
        if office_to:
            voicemail_alert = (
                f"Voicemail from {from_num}" +
                (f" ({caller})" if caller else "") +
                f" — {business_name}" +
                (f"\n{recording_url}" if recording_url else "")
            )
            send_sms(office_to, voicemail_alert)
    except Exception as e:
        print(f"[VOICE] voicemail office alert error: {e}")

    vr = VoiceResponse()
    vr.say("Thanks. We just texted you our booking link. Goodbye.", voice="alice")
    return PlainTextResponse(str(vr), media_type="application/xml")

@router.post("/twilio/voice/missed")
async def twilio_voice_missed(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id_public),
):
    """
    Twilio status callback for unanswered/missed inbound calls.
    Fires when CallStatus is 'no-answer' or 'busy'.

    REQUIRED TWILIO CONSOLE SETUP (per phone number):
      1. Go to Twilio Console → Phone Numbers → Manage → Active Numbers
      2. Click the number, scroll to "Voice & Fax"
      3. Under "Call Status Changes", set the webhook URL to:
         https://<your-domain>/twilio/voice/missed  (HTTP POST)
      Without this, Twilio will never call this endpoint and missed calls
      will not be logged or alerted.
    """
    if not await _verify_twilio_signature(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Twilio signature")

    try:
        form = await request.form()
    except Exception as e:
        print(f"[MISSED] form parse error: {e}")
        form = {}

    call_status = (form.get("CallStatus") or "").strip().lower()
    from_num_raw = (form.get("From") or "").strip()
    from_num = normalize_us_phone(from_num_raw) or from_num_raw
    caller = (form.get("CallerName") or "").strip()
    call_sid = (form.get("CallSid") or "").strip()

    print(f"[MISSED] tenant={tenant_id} status={call_status} from={from_num} sid={call_sid}")

    # Only act on actual missed/unanswered calls
    if call_status not in ("no-answer", "busy", "failed"):
        return PlainTextResponse("", status_code=204)

    if not from_num:
        return PlainTextResponse("", status_code=204)

    # Dedupe by CallSid so retries don't double-send
    if call_sid and not _dedupe_insert(session, source=f"missed_call:{tenant_id}", event_id=call_sid):
        print(f"[MISSED] duplicate CallSid={call_sid}, skipping")
        return PlainTextResponse("", status_code=204)

    # 1. Save lead with source="missed_call"
    try:
        session.add(LeadModel(
            name=(caller or "").strip(),
            phone=from_num,
            email=None,
            message="Missed call",
            tenant_id=tenant_id,
            source="missed_call",
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"[MISSED] DB lead insert error: {e}")

    b = get_brand_for_tenant(tenant_id)
    business_name = b.get("business_name") or tenant_id

    # 2. SMS to caller
    def _send_missed_call_effects():
        try:
            if not _blocked_number(from_num):
                caller_msg = "Hi! We missed your call and want to make sure you get taken care of. We'll be in touch shortly."
                send_sms(from_num, caller_msg)
        except Exception as e:
            print(f"[MISSED] caller SMS error: {e}")

        # 3. Alert the office
        try:
            from app.services.sms import _office_destination_for_tenant, send_sms as _send
            office_to = _office_destination_for_tenant(tenant_id)
            if office_to:
                alert_body = f"Missed call from {from_num}" + (f" ({caller})" if caller else "") + f" — {business_name}"
                _send(office_to, alert_body)
        except Exception as e:
            print(f"[MISSED] office alert error: {e}")

    background_tasks.add_task(_send_missed_call_effects)

    return PlainTextResponse("", status_code=204)


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
    tok = (getattr(config, "TWILIO_AUTH_TOKEN", "") or "").strip()
    return {
        "validate": bool(getattr(config, "TWILIO_VALIDATE_SIGNATURES", False)),
        "token_set": bool(tok),
        "token_len": len(tok),
        "token_prefix": tok[:4] + "..." if tok else "(empty)",
        "account_sid_set": bool((getattr(config, "TWILIO_ACCOUNT_SID", "") or "").strip()),
        "host": request.headers.get("host"),
        "forwarded_proto": request.headers.get("x-forwarded-proto"),
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
