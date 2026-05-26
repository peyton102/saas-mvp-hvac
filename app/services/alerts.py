# app/services/alerts.py
import os
from app.services.sms import send_sms

# Alert destination — set ALERT_SMS_TO in your environment (same var as sms.py).
ALERT_PHONE = os.getenv("ALERT_SMS_TO", "").strip()

def alert_error(subject: str, details: str):
    if not ALERT_PHONE:
        return False
    body = f"{subject}\n\n{details}"
    return send_sms(ALERT_PHONE, body)
