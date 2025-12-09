# app/services/email.py
from __future__ import annotations

import logging
import ssl
import smtplib
import json
import urllib.request
from urllib.error import HTTPError, URLError
from email.message import EmailMessage
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo  # stdlib in Python 3.9+

from app import config

log = logging.getLogger(__name__)

# ---- internal helpers --------------------------------------------------------


def _dedup_preserve(emails: list[str]) -> list[str]:
    seen = set()
    out = []
    for e in emails:
        e2 = (e or "").strip().lower()
        if not e2 or e2 in seen:
            continue
        seen.add(e2)
        out.append(e)
    return out


def _as_list(v: str | Iterable[str] | None) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v]
    return [x for x in v if x]


def _detect_sendgrid_api_key() -> str | None:
    """
    Prefer explicit SENDGRID_API_KEY; otherwise, if user configured SendGrid SMTP
    (host=smtp.sendgrid.net, username=apikey) with an SG.* password, use that.
    """
    api_key = getattr(config, "SENDGRID_API_KEY", None)
    if api_key:
        return api_key
    host = getattr(config, "SMTP_HOST", "") or ""
    user = getattr(config, "SMTP_USERNAME", "") or ""
    pwd = getattr(config, "SMTP_PASSWORD", "") or ""
    if host.lower().strip() == "smtp.sendgrid.net" and user == "apikey" and pwd.startswith("SG."):
        return pwd
    return None


def _send_via_sendgrid(
    to: list[str],
    subject: str,
    text: str,
    html: str | None = None,
    reply_to: str | None = None,
) -> bool:
    api_key = _detect_sendgrid_api_key()
    if not api_key:
        return False  # no SendGrid API key configured

    payload = {
        "personalizations": [{"to": [{"email": e} for e in to]}],
        "from": {
            "email": config.FROM_EMAIL,
            "name": getattr(config, "FROM_NAME", "") or config.FROM_EMAIL,
        },
        "subject": subject,
        "content": [{"type": "text/plain", "value": text or ""}],
    }
    if html:
        payload["content"].append({"type": "text/html", "value": html})
    if reply_to:
        payload["reply_to"] = {"email": reply_to}

    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20):
            pass
        log.info("SendGrid API send ok → %s", to)
        return True
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            body = "<no body>"
        log.error("SendGrid HTTP %s: %s", e.code, body)
        return False
    except URLError as e:
        log.error("SendGrid network error: %s", e)
        return False
    except Exception as e:
        log.error("SendGrid send failed: %s", e)
        return False


def _send_via_smtp(
    to: list[str],
    subject: str,
    text: str,
    html: str | None = None,
    reply_to: str | None = None,
) -> bool:
    host = getattr(config, "SMTP_HOST", None)
    user = getattr(config, "SMTP_USERNAME", None)
    pwd = getattr(config, "SMTP_PASSWORD", None)
    try:
        port = int(getattr(config, "SMTP_PORT", 587))
    except Exception:
        port = 587

    if not (host and user and pwd):
        log.error("SMTP creds missing (host/user/pwd)")
        return False

    msg = EmailMessage()
    from_name = getattr(config, "FROM_NAME", "") or config.FROM_EMAIL
    msg["From"] = f"{from_name} <{config.FROM_EMAIL}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text or "")
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.ehlo()
            s.starttls(context=context)
            s.ehlo()
            s.login(user, pwd)
            s.send_message(msg)
        log.info("SMTP send ok → %s via %s:%s", to, host, port)
        return True
    except smtplib.SMTPException as e:
        log.error("SMTP send failed: %s", e)
        return False
    except Exception as e:
        log.error("SMTP error: %s", e)
        return False


# ---- public API --------------------------------------------------------------


def send_email(
    to: str | Iterable[str],
    subject: str,
    text: str,
    html: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """
    Sends an email using SendGrid (HTTP API) if available; otherwise SMTP.
    - Respects config.EMAIL_DRY_RUN (prints/logs but doesn't send)
    - `to` can be a string or list of strings
    - optional `reply_to`
    """
    to_list = _as_list(to)
    if not to_list:
        log.error("send_email called with empty recipient list")
        return False

    if getattr(config, "EMAIL_DRY_RUN", True):
        log.info("[EMAIL DRY RUN] to=%s subject=%s", to_list, subject)
        print(f"[EMAIL DRY RUN] to={to_list} subject={subject}")
        return True

    # Try SendGrid API first if key is present; fall back to SMTP
    if _detect_sendgrid_api_key() and _send_via_sendgrid(to_list, subject, text, html, reply_to):
        return True
    return _send_via_smtp(to_list, subject, text, html, reply_to)


# ---- office email helper -----------------------------------------------------


def _office_email_for_tenant(tenant: str) -> str:
    """
    Optionally map tenant -> office email via config.TENANT_OFFICE_EMAILS like:
      "default:owner@torevez.com,acme:dispatch@acme.com"
    Falls back to config.EMAIL_OFFICE or config.FROM_EMAIL.
    """
    raw = getattr(config, "TENANT_OFFICE_EMAILS", "") or ""
    mapping: dict[str, str] = {}
    for part in [p.strip() for p in raw.split(",") if ":" in p]:
        k, v = part.split(":", 1)
        mapping[k.strip()] = v.strip()
    return mapping.get(tenant) or getattr(config, "EMAIL_OFFICE", None) or config.FROM_EMAIL


def _local_time_str(iso: str) -> str:
    """
    Pretty local time formatter for emails.

    Examples (TZ-aware):
      12/5 2:00 PM EST        (if current year)
      12/5/2026 2:00 PM EST   (if different year)
    """
    try:
        tz_name = getattr(config, "TZ", None)
        if not tz_name and hasattr(config, "settings"):
            tz_name = getattr(config.settings, "TZ", "America/New_York")
        tz_name = tz_name or "America/New_York"

        tz = ZoneInfo(tz_name)
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz)
        now_year = datetime.now(tz).year

        if dt.year == now_year:
            s = dt.strftime("%m/%d %I:%M %p %Z")
        else:
            s = dt.strftime("%m/%d/%Y %I:%M %p %Z")

        s = s.replace("/0", "/").replace(" 0", " ")
        return s
    except Exception:
        return iso


# ---- booking confirmation ----------------------------------------------------


def _booking_subject(tenant: str, service: str, name: str, starts_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(starts_iso.replace("Z", "+00:00"))
        when = dt.strftime("%b %d, %I:%M %p")
    except Exception:
        when = starts_iso
    return f"[{tenant}] Booked: {service} for {name} @ {when}"


def _booking_text(tenant: str, p: dict) -> str:
    lines = [
        f"Hi {p.get('name', '')},",
        "",
        "Your appointment is confirmed.",
        f"Service: {p.get('service', 'default')}",
        f"When:   {_local_time_str(p.get('starts_at_iso', ''))}",
        f"Phone:  {p.get('phone', '')}",
        f"Address:{p.get('address', '')}",
        "",
    ]
    if p.get("reschedule_url"):
        lines += [f"Reschedule: {p['reschedule_url']}", ""]
    lines += [
        "If you need to reschedule, just reply to this email.",
        "",
        f"- {getattr(config, 'FROM_NAME', tenant)} Team",
    ]
    return "\n".join(lines)


def _booking_html(tenant: str, p: dict) -> str:
    resched_html = (
        f'<p><a href="{p.get("reschedule_url")}">Reschedule your appointment</a></p>'
        if p.get("reschedule_url")
        else ""
    )
    return f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial">
      <p>Hi {p.get('name','')},</p>
      <p>Your <b>{p.get('service','default')}</b> is scheduled for <b>{_local_time_str(p.get('starts_at_iso',''))}</b>.</p>
      <p><b>Phone:</b> {p.get('phone','')}&nbsp;&nbsp; <b>Address:</b> {p.get('address','')}</p>
      {resched_html}
      <p>If you need to reschedule, just reply to this email.</p>
      <p>— {getattr(config, 'FROM_NAME', tenant)} Team</p>
    </div>
    """.strip()


def send_booking_confirmation(tenant: str, payload: dict) -> bool:
    """
    payload: { name, email?, phone?, address?, service, starts_at_iso, reschedule_url? }

    Sends to:
      - OFFICE (always, from EMAIL_OFFICE or per-tenant mapping)
      - CUSTOMER (if provided)
    De-dupes automatically so SendGrid/SMTP never gets duplicates.
    """
    subject = _booking_subject(
        tenant,
        payload.get("service", "default"),
        payload.get("name", ""),
        payload.get("starts_at_iso", ""),
    )
    text = _booking_text(tenant, payload)
    html = _booking_html(tenant, payload)

    office = _office_email_for_tenant(tenant)
    cust = (payload.get("email") or "").strip()

    recipients = _dedup_preserve([office, cust])

    if not recipients:
        log.error("send_booking_confirmation: no recipients (office=%r, cust=%r)", office, cust)
        return False

    log.info("Booking email → recipients=%s subject=%s", recipients, subject)
    print(f"[EMAIL BOOKING] to={recipients} subject={subject}")  # visible in console

    return send_email(recipients, subject, text, html=html, reply_to=office)


# ---- reminder emails (24h / 2h / etc.) --------------------------------------


def _reminder_subject(tenant: str, service: str, name: str, starts_iso: str, window: str) -> str:
    """
    window: "24h", "2h", "review", etc.
    """
    try:
        dt = datetime.fromisoformat(starts_iso.replace("Z", "+00:00"))
        when = dt.strftime("%b %d, %I:%M %p")
    except Exception:
        when = starts_iso
    return f"[{tenant}] Reminder ({window}): {service} for {name} @ {when}"


def _reminder_text(tenant: str, p: dict, window: str) -> str:
    label = "appointment" if window not in ("24h", "2h") else f"{window} appointment"
    lines = [
        f"Hi {p.get('name','')},",
        "",
        f"This is your {label} reminder.",
        f"Service: {p.get('service','default')}",
        f"When:   {_local_time_str(p.get('starts_at_iso',''))}",
        "",
    ]
    if p.get("reschedule_url"):
        lines += [f"Reschedule: {p['reschedule_url']}", ""]
    lines += [
        "If you need to reschedule, just reply to this email.",
        "",
        f"- {getattr(config, 'FROM_NAME', tenant)} Team",
    ]
    return "\n".join(lines)


def _reminder_html(tenant: str, p: dict, window: str) -> str:
    label = "appointment" if window not in ("24h", "2h") else f"{window} appointment"
    resched_html = (
        f'<p><a href="{p.get("reschedule_url")}">Reschedule your appointment</a></p>'
        if p.get("reschedule_url")
        else ""
    )
    return f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial">
      <p>Hi {p.get('name','')},</p>
      <p>This is your <b>{label}</b> reminder.</p>
      <p><b>Service:</b> {p.get('service','default')}</p>
      <p><b>When:</b> {_local_time_str(p.get('starts_at_iso',''))}</p>
      {resched_html}
      <p>If you need to reschedule, just reply to this email.</p>
      <p>— {getattr(config, 'FROM_NAME', tenant)} Team</p>
    </div>
    """.strip()


def send_booking_reminder(tenant: str, payload: dict, window: str) -> bool:
    """
    window: "24h" or "2h" (or any tag like "review" if you reuse it)

    payload: { name, email?, phone?, address?, service, starts_at_iso, reschedule_url? }

    Sends to:
      - OFFICE (always)
      - CUSTOMER (if email present)
    """
    subject = _reminder_subject(
        tenant,
        payload.get("service", "default"),
        payload.get("name", ""),
        payload.get("starts_at_iso", ""),
        window,
    )
    text = _reminder_text(tenant, payload, window)
    html = _reminder_html(tenant, payload, window)

    office = _office_email_for_tenant(tenant)
    cust = (payload.get("email") or "").strip()

    recipients = _dedup_preserve([office, cust])

    if not recipients:
        log.error("send_booking_reminder: no recipients")
        return False

    log.info("Reminder email (%s) → recipients=%s subject=%s", window, recipients, subject)
    print(f"[EMAIL REMINDER {window}] to={recipients} subject={subject}")
    return send_email(recipients, subject, text, html=html, reply_to=office)
