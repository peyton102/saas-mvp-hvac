# app/services/email.py
from __future__ import annotations

import logging
import ssl
import smtplib
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


def _send_via_smtp(
    to: list[str],
    subject: str,
    text: str,
    html: str | None = None,
    reply_to: str | None = None,
) -> bool:
    host = getattr(config, "SMTP_HOST", None) or ""
    user = getattr(config, "SMTP_USERNAME", None) or ""
    pwd = getattr(config, "SMTP_PASSWORD", None) or ""
    try:
        port = int(getattr(config, "SMTP_PORT", 587))
    except Exception:
        port = 587
    from_email = getattr(config, "FROM_EMAIL", "") or ""
    from_name = getattr(config, "FROM_NAME", "") or from_email

    print(f"[SMTP] attempting send — host={host!r} port={port} user={user!r} from={from_email!r} to={to}")
    log.info("[SMTP] attempting send — host=%r port=%s user=%r from=%r to=%s", host, port, user, from_email, to)

    if not host:
        print("[SMTP] ERROR: SMTP_HOST is not set")
        log.error("[SMTP] SMTP_HOST is not set")
        return False
    if not user:
        print("[SMTP] ERROR: SMTP_USERNAME is not set")
        log.error("[SMTP] SMTP_USERNAME is not set")
        return False
    if not pwd:
        print("[SMTP] ERROR: SMTP_PASSWORD is not set")
        log.error("[SMTP] SMTP_PASSWORD is not set")
        return False
    if not from_email:
        print("[SMTP] ERROR: FROM_EMAIL is not set")
        log.error("[SMTP] FROM_EMAIL is not set")
        return False

    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text or "")
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        print(f"[SMTP] connecting to {host}:{port} ...")
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.set_debuglevel(1)  # prints full SMTP conversation to stdout
            print("[SMTP] connected — sending EHLO ...")
            s.ehlo()
            print("[SMTP] starting TLS ...")
            s.starttls(context=context)
            s.ehlo()
            print(f"[SMTP] logging in as {user!r} ...")
            s.login(user, pwd)
            print("[SMTP] login OK — sending message ...")
            s.send_message(msg)
        print(f"[SMTP] send OK → to={to} subject={subject!r}")
        log.info("[SMTP] send OK → to=%s subject=%r", to, subject)
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"[SMTP] AUTH FAILED (bad username/password) — {e}")
        log.error("[SMTP] AUTH FAILED — %s", e)
        return False
    except smtplib.SMTPConnectError as e:
        print(f"[SMTP] CONNECT FAILED to {host}:{port} — {e}")
        log.error("[SMTP] CONNECT FAILED to %s:%s — %s", host, port, e)
        return False
    except smtplib.SMTPException as e:
        print(f"[SMTP] SMTP error — {type(e).__name__}: {e}")
        log.error("[SMTP] SMTP error — %s: %s", type(e).__name__, e)
        return False
    except OSError as e:
        print(f"[SMTP] network/OS error connecting to {host}:{port} — {e}")
        log.error("[SMTP] network/OS error — %s", e)
        return False
    except Exception as e:
        print(f"[SMTP] unexpected error — {type(e).__name__}: {e}")
        log.error("[SMTP] unexpected error — %s: %s", type(e).__name__, e)
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
    Sends an email via SMTP.
    - Respects config.EMAIL_DRY_RUN (logs but doesn't send)
    - `to` can be a string or list of strings
    - optional `reply_to`
    """
    to_list = _as_list(to)
    if not to_list:
        print("[EMAIL] ERROR: send_email called with empty recipient list")
        log.error("[EMAIL] send_email called with empty recipient list")
        return False

    if getattr(config, "EMAIL_DRY_RUN", False):
        print(f"[EMAIL DRY RUN] to={to_list} subject={subject!r}")
        log.info("[EMAIL DRY RUN] to=%s subject=%r", to_list, subject)
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


def send_password_reset_email(email: str, reset_url: str) -> bool:
    """Send a password reset link to the given email address."""
    from_name = getattr(config, "FROM_NAME", "HVAC Bot")
    subject = f"Reset your {from_name} password"
    text = (
        f"Click the link below to reset your password. It expires in 1 hour.\n\n"
        f"{reset_url}\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )
    html = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;max-width:480px">
      <p>Click the button below to reset your <strong>{from_name}</strong> password.
         The link expires in <strong>1 hour</strong>.</p>
      <p>
        <a href="{reset_url}"
           style="display:inline-block;padding:12px 28px;background:#f97316;color:#111827;
                  font-weight:700;text-decoration:none;border-radius:8px">
          Reset Password
        </a>
      </p>
      <p style="color:#6b7280;font-size:13px">
        Or copy this link:<br>{reset_url}
      </p>
      <p style="color:#6b7280;font-size:13px">
        If you didn't request a password reset, you can safely ignore this email.
      </p>
    </div>
    """.strip()
    return send_email(email, subject, text, html=html)


def send_welcome_email(email: str, business_name: str, portal_url: str) -> bool:
    """Send a welcome / account-created email to a new tenant."""
    from_name = getattr(config, "FROM_NAME", "Torevez")
    subject = f"Welcome to {from_name} — your account is ready"
    login_url = portal_url.rstrip("/")
    text = (
        f"Your {from_name} account for {business_name} is ready.\n\n"
        f"You're on a free 30-day trial — no credit card needed.\n\n"
        f"Log in here: {login_url}\n\n"
        f"Questions? Just reply to this email.\n\n"
        f"— The {from_name} Team"
    )
    html = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;max-width:520px;padding:32px 24px;background:#ffffff">
      <div style="font-size:28px;font-weight:900;margin-bottom:24px">
        <span style="color:#111827">Tore</span><span style="color:#f97316">vez</span>
      </div>
      <h2 style="color:#111827;font-size:22px;margin:0 0 12px">Your account is ready.</h2>
      <p style="color:#374151;margin:0 0 8px">
        <strong>{business_name}</strong> has been set up on your free 30-day trial.
      </p>
      <p style="color:#374151;margin:0 0 24px">No credit card needed — just log in and get started.</p>
      <a href="{login_url}"
         style="display:inline-block;padding:14px 32px;background:#f97316;color:#111827;
                font-weight:700;font-size:16px;text-decoration:none;border-radius:8px">
        Go to Dashboard
      </a>
      <p style="color:#9ca3af;font-size:12px;margin-top:32px">
        Questions? Reply to this email and we'll help you out.
      </p>
    </div>
    """.strip()
    return send_email(email, subject, text, html=html)


def send_monthly_summary_email(email: str, business_name: str, stats: dict, portal_url: str) -> bool:
    """Send the monthly 'here's what Torevez did for you' recap email."""
    from_name = getattr(config, "FROM_NAME", "Torevez")
    month = stats.get("month", "this month")
    subject = f"Here's what {from_name} caught for you in {month}"
    login_url = portal_url.rstrip("/")

    leads = stats.get("leads_captured", 0)
    bookings = stats.get("bookings_made", 0)
    won = stats.get("jobs_won", 0)
    revenue = stats.get("revenue_this_month", 0.0)
    missed = stats.get("missed_calls_answered", 0)

    text_body = (
        f"Here's your {month} recap for {business_name}:\n\n"
        f"  Leads captured:       {leads}\n"
        f"  Bookings made:        {bookings}\n"
        f"  Jobs won:             {won}"
        + (f" (${revenue:,.0f})" if revenue else "") + "\n"
        f"  Missed calls answered:{missed}\n\n"
        f"View your full dashboard: {login_url}\n\n"
        f"— The {from_name} Team"
    )

    rev_line = f"<strong>${revenue:,.0f}</strong> in revenue" if revenue else f"<strong>{won} job{'s' if won != 1 else ''} won</strong>"

    html = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;max-width:520px;padding:32px 24px;background:#ffffff">
      <div style="font-size:28px;font-weight:900;margin-bottom:24px">
        <span style="color:#111827">Tore</span><span style="color:#f97316">vez</span>
      </div>
      <h2 style="color:#111827;font-size:20px;margin:0 0 6px">Your {month} recap</h2>
      <p style="color:#6b7280;margin:0 0 24px;font-size:14px">{business_name}</p>

      <table style="width:100%;border-collapse:collapse;margin-bottom:24px">
        <tr style="background:#f9fafb">
          <td style="padding:12px 16px;font-size:14px;color:#374151;border-radius:8px 0 0 8px">Leads captured</td>
          <td style="padding:12px 16px;font-size:22px;font-weight:900;color:#111827;text-align:right">{leads}</td>
        </tr>
        <tr>
          <td style="padding:12px 16px;font-size:14px;color:#374151">Bookings made</td>
          <td style="padding:12px 16px;font-size:22px;font-weight:900;color:#111827;text-align:right">{bookings}</td>
        </tr>
        <tr style="background:#f9fafb">
          <td style="padding:12px 16px;font-size:14px;color:#374151">Jobs won</td>
          <td style="padding:12px 16px;font-size:22px;font-weight:900;color:#f97316;text-align:right">{rev_line}</td>
        </tr>
        <tr>
          <td style="padding:12px 16px;font-size:14px;color:#374151">Missed calls answered</td>
          <td style="padding:12px 16px;font-size:22px;font-weight:900;color:#111827;text-align:right">{missed}</td>
        </tr>
      </table>

      <a href="{login_url}"
         style="display:inline-block;padding:14px 32px;background:#f97316;color:#111827;
                font-weight:700;font-size:15px;text-decoration:none;border-radius:8px">
        View Dashboard
      </a>

      <p style="color:#9ca3af;font-size:12px;margin-top:32px">
        You're receiving this because you use {from_name} to manage your business.
      </p>
    </div>
    """.strip()

    return send_email(email, subject, text_body, html=html)


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
