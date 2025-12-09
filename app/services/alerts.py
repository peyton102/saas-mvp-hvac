# app/services/alerts.py
from app.services.sms import send_sms

# HARD-CODED ALERT DESTINATION (your number)
ALERT_PHONE = "+18145642212"  # your number in E.164 format

def alert_error(subject: str, details: str):
    body = f"{subject}\n\n{details}"
    return send_sms(ALERT_PHONE, body)
