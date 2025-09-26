# app/routers/sms_debug.py
from fastapi import APIRouter, Body
from app import config
from app.services.sms import send_sms

router = APIRouter(prefix="", tags=["debug-sms"])

@router.get("/debug/sms-config")
def sms_config():
    """Show current Twilio/SMS settings (no secrets), useful before turning DRY_RUN off."""
    return {
        "SMS_DRY_RUN": bool(getattr(config, "SMS_DRY_RUN", True)),
        "TWILIO_ACCOUNT_SID_set": bool(getattr(config, "TWILIO_ACCOUNT_SID", "")),
        "TWILIO_AUTH_TOKEN_set": bool(getattr(config, "TWILIO_AUTH_TOKEN", "")),
        "TWILIO_FROM": getattr(config, "TWILIO_FROM", "") or "",
        "TWILIO_MESSAGING_SERVICE_SID": getattr(config, "TWILIO_MESSAGING_SERVICE_SID", "") or "",
    }

@router.post("/debug/sms-test")
def sms_test(payload: dict = Body(...)):
    """
    Send a test SMS (honors SMS_DRY_RUN). Body: {"to":"+1XXXXXXXXXX","message":"hello"}
    """
    to = (payload.get("to") or "").strip()
    msg = (payload.get("message") or "Test from HVAC MVP").strip()
    if not to:
        return {"ok": False, "error": "Missing 'to'."}
    ok = send_sms(to, msg)
    return {"ok": bool(ok), "dry_run": bool(getattr(config, "SMS_DRY_RUN", True))}
