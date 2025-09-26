# app/services/email.py
import smtplib, ssl
from email.message import EmailMessage
from app import config
import logging

log = logging.getLogger(__name__)

def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    if getattr(config, "EMAIL_DRY_RUN", True):
        log.info("[EMAIL DRY RUN] to=%s subject=%s", to, subject)
        print(f"[EMAIL DRY RUN] to={to} subject={subject}")
        return True
    if not (config.SMTP_HOST and config.SMTP_USERNAME and config.SMTP_PASSWORD):
        log.error("SMTP creds missing")
        return False

    msg = EmailMessage()
    msg["From"] = config.FROM_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        log.error("Email send failed: %s", e)
        return False
