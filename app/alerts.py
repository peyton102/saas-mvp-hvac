# app/alerts.py
import logging

from app.services import sms  # uses send_sms(to: str, body: str)

logger = logging.getLogger(__name__)

# 🔔 Hard-coded alert destination (your phone)
ALERT_PHONE = "+18145642212"


def send_error_alert(message: str) -> None:
    """
    Send a crash/500 alert SMS to the owner phone.

    Uses the SAME Twilio helper as the rest of the app (app.services.sms.send_sms)
    so we don't fight separate config.
    """
    msg = (message or "").strip()
    if not msg:
        msg = "Server error (empty detail)"

    # keep it short-ish for SMS
    if len(msg) > 900:
        msg = msg[:900] + "..."

    try:
        ok = sms.send_sms(ALERT_PHONE, msg)
        if ok:
            logger.info("[alerts] sent error SMS to %s", ALERT_PHONE)
        else:
            logger.error("[alerts] send_sms returned False for %s", ALERT_PHONE)
    except Exception as e:
        logger.error("[alerts] failed to send SMS alert: %r", e)
