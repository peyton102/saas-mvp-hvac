# app/routers/sms_debug.py
from fastapi import APIRouter, Depends, Request
from app import config
from app.services.sms import send_sms, is_dry_run
from ..deps import get_tenant_id

router = APIRouter(prefix="", tags=["sms-debug"])

@router.get("/debug/sms-config")
def sms_config(request: Request, tenant_id: str = Depends(get_tenant_id)):
    return {
        "tenant_id": tenant_id,
        "account_sid_len": len(config.settings.TWILIO_ACCOUNT_SID or ""),
        "messaging_service_sid_len": len(config.settings.TWILIO_MESSAGING_SERVICE_SID or ""),
        "from_number": config.settings.TWILIO_FROM or "",
        "dry_run": is_dry_run(),  # <- live read each call
    }

@router.post("/debug/sms-test")
def sms_test(payload: dict, tenant_id: str = Depends(get_tenant_id)):
    to = (payload.get("to") or "").strip()
    body = (payload.get("body") or "test").strip()
    ok = send_sms(to, body)
    return {"ok": bool(ok), "dry_run": is_dry_run()}
