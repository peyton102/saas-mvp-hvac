# app/services/sms.py
import os
from typing import Optional, Dict, Any
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlmodel import select

from app.db import get_session
from app.models import Tenant, TenantSettings
from app import config
from twilio.rest import Client


def _booking_link_for_slug(tenant_slug: str) -> Optional[str]:
    """
    Build a tenant-specific booking link from config.BOOKING_LINK.

    If BOOKING_LINK is like:
      http://localhost:5173/book/index.html?tenant=default

    This returns the same URL but with ?tenant=<tenant_slug>.
    """
    base = getattr(config, "BOOKING_LINK", "").strip()
    if not base:
        return None

    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query))
    query["tenant"] = tenant_slug  # always force to this tenant

    new_query = urlencode(query)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def get_brand_for_tenant(tenant_slug: str) -> dict:
    """
    Source of truth for branding / review data.

    We are always passed the tenant *slug* (e.g. 'test-tenant-two').

    - TenantSettings is linked to Tenant via tenant.slug (string FK).
    - Tenant holds booking_link, office_sms_to, etc.
    - TenantSettings overrides Tenant fields where present.
    """
    gen = get_session()
    session = next(gen)
    try:
        # 1) find the tenant row by slug
        tenant = session.exec(
            select(Tenant).where(Tenant.slug == tenant_slug)
        ).first()

        if not tenant:
            # no tenant row – fall back to slug for name only
            return {
                "business_name": tenant_slug,
                "business_phone": None,
                "review_link": None,
                "booking_link": None,
                "office_sms_to": None,
                "office_email_to": None,
            }

        # 2) find settings row by tenant.slug (string FK)
        settings = session.exec(
            select(TenantSettings).where(TenantSettings.tenant_id == tenant.slug)
        ).first()

        # Settings override tenant where present; else fall back to tenant fields
        business_name = (
            (settings.business_name or "").strip()
            if settings
            else ""
        ) or (tenant.business_name or "").strip() or tenant.slug

        business_phone = (
            (settings.business_phone or "").strip()
            if settings
            else ""
        ) or (tenant.phone or "").strip() or None

        review_link = (
            (settings.review_link or "").strip()
            if settings
            else ""
        ) or (tenant.review_google_url or "").strip() or None

        # Booking link: respect an explicit Tenant.booking_link override
        # but if it's empty or just equal to the global default, compute from slug.
        booking_link = (tenant.booking_link or "").strip()
        global_default = getattr(config, "BOOKING_LINK", "").strip()

        if (not booking_link) or (global_default and booking_link == global_default):
            # Compute tenant-specific link from the global template
            booking_link = _booking_link_for_slug(tenant.slug) or global_default or None

        if not booking_link:
            booking_link = None

        office_sms_to = (
            (settings.office_sms_to or "").strip()
            if settings
            else ""
        ) or (tenant.office_sms_to or "").strip() or None

        office_email_to = (
            (settings.office_email_to or "").strip()
            if settings
            else ""
        ) or (tenant.office_email_to or "").strip() or None

        return {
            "business_name": business_name,
            "business_phone": business_phone,
            "review_link": review_link,
            "booking_link": booking_link,
            "office_sms_to": office_sms_to,
            "office_email_to": office_email_to,
        }
    finally:
        session.close()


def _truthy(val) -> bool:
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")


def is_dry_run() -> bool:
    # Prefer live env each call; fall back to config attr; default false
    env_val = os.getenv("SMS_DRY_RUN", None)
    if env_val is not None:
        return _truthy(env_val)
    return _truthy(getattr(config, "SMS_DRY_RUN", "false"))


def _client() -> Client:
    """
    Build a Twilio client using API Key auth:

      Client(api_key_sid, api_key_secret, account_sid)
    """
    api_key = os.getenv("TWILIO_API_KEY", getattr(config, "TWILIO_API_KEY", ""))
    secret = os.getenv("TWILIO_AUTH_TOKEN", getattr(config, "TWILIO_AUTH_TOKEN", ""))
    account = os.getenv("TWILIO_ACCOUNT_SID", getattr(config, "TWILIO_ACCOUNT_SID", ""))

    if not (api_key and secret and account):
        raise RuntimeError("Missing TWILIO_API_KEY / TWILIO_AUTH_TOKEN / TWILIO_ACCOUNT_SID")

    return Client(api_key, secret, account)


def _normalize_phone(phone: Optional[str]) -> Optional[str]:
    """
    Very light E.164-ish normalizer for US numbers.

    - Strips spaces and punctuation.
    - If 10 digits -> +1XXXXXXXXXX
    - If 11 digits starting with 1 -> +1XXXXXXXXXX
    - If already starts with '+' -> returned as-is
    """
    if not phone:
        return None

    p = phone.strip()
    if p.startswith("+"):
        return p

    digits = "".join(ch for ch in p if ch.isdigit())
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits

    return None  # let caller treat as invalid


def send_sms(to: str, body: str) -> bool:
    """
    Sends an SMS using Messaging Service if set, else TWILIO_FROM.
    Honors is_dry_run() at call time.
    Returns True if (attempted) send (or dry-run), False on error.
    """
    try:
        phone = _normalize_phone(to)
        if not phone:
            print(f"[SMS ERROR] invalid phone={to!r}")
            return False

        if is_dry_run():
            print(f"[SMS DRY-RUN] to={phone} body={body}")
            return True

        client = _client()
        svc = os.getenv(
            "TWILIO_MESSAGING_SERVICE_SID",
            getattr(config, "TWILIO_MESSAGING_SERVICE_SID", "")
        ) or None
        from_num = os.getenv(
            "TWILIO_FROM",
            getattr(config, "TWILIO_FROM", "")
        ) or None

        if not svc and not from_num:
            raise RuntimeError("Set TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM")

        kwargs = {"to": phone, "body": body}
        if svc:
            kwargs["messaging_service_sid"] = svc
        else:
            kwargs["from_"] = from_num

        msg = client.messages.create(**kwargs)
        print(f"[SMS SENT] sid={msg.sid} to={phone}")
        return True

    except Exception as e:
        print(f"[SMS ERROR] to={to} err={e}")
        return False


# ---------- time formatting helper (shared by confirmation / reminders / office) ----------

def format_pretty_time(iso_str: str) -> str:
    """
    Convert ISO string to something like:
      12/5 2:00 PM
    (no year if it's the current year; we default to config.TZ or America/New_York)
    """
    try:
        # figure out TZ
        tz_name = getattr(config, "TZ", None)
        if not tz_name and hasattr(config, "settings"):
            tz_name = getattr(config.settings, "TZ", "America/New_York")
        tz_name = tz_name or "America/New_York"

        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00")).astimezone(ZoneInfo(tz_name))
        now_year = datetime.now(ZoneInfo(tz_name)).year

        if dt.year == now_year:
            s = dt.strftime("%m/%d %I:%M %p")
        else:
            s = dt.strftime("%m/%d/%Y %I:%M %p")

        # strip leading zeros from month/day/hour
        s = s.replace("/0", "/").replace(" 0", " ")
        return s
    except Exception:
        return str(iso_str)


# ---- Booking-specific helpers ----

def booking_confirmation_sms(tenant_id: str, payload: Dict[str, Any]) -> bool:
    """
    payload fields expected: name, phone, service, starts_at_iso
    Uses TenantSettings/Tenant for business_name + booking_link.
    """
    phone = payload.get("phone")
    if not phone:
        return False

    brand = get_brand_for_tenant(tenant_id)

    business_name = brand.get("business_name") or tenant_id
    # per-tenant booking link first, then global fallback
    booking_link = brand.get("booking_link") or getattr(config, "BOOKING_LINK", "")

    name = payload.get("name") or "Customer"
    when_iso = payload.get("starts_at_iso") or ""
    service = payload.get("service") or "service"

    body = f"Hi {name}, you're booked for {service} with {business_name}."
    if when_iso:
        pretty_when = format_pretty_time(when_iso)
        body += f" Start: {pretty_when}."
    if booking_link:
        body += f" To reschedule: {booking_link}"

    return send_sms(phone, body)


def booking_reminder_sms(tenant_id: str, payload: dict, kind: str) -> bool:
    """
    kind: '24h', '2h', or 'review'
    Uses TenantSettings for business_name + review_link.
    """
    phone = payload.get("phone")
    if not phone:
        return False

    brand = get_brand_for_tenant(tenant_id)
    from_name = brand.get("business_name") or tenant_id
    review_link_default = brand.get("review_link") or None

    name = (payload.get("name") or "").split(" ")[0] or "there"
    service = payload.get("service") or "appointment"
    starts_iso = payload.get("starts_at_iso")

    # allow explicit review_link override (rare) but default to TenantSettings
    review_link = payload.get("review_link") or review_link_default

    when = "your upcoming appointment"
    if starts_iso:
        when = format_pretty_time(str(starts_iso))

    if kind == "24h":
        body = (
            f"Hi {name}, just a reminder of your {service} with {from_name} "
            f"tomorrow ({when}). Reply C to cancel or R to reschedule."
        )
    elif kind == "2h":
        body = (
            f"Hi {name}, friendly reminder of your {service} with {from_name} "
            f"in about 2 hours ({when}). Reply C to cancel or R to reschedule."
        )
    elif kind == "review":
        if review_link:
            body = (
                f"Hi {name}, thanks again for choosing {from_name}! "
                f"If we earned it, would you mind leaving a quick review here: {review_link}"
            )
        else:
            body = (
                f"Hi {name}, thanks again for choosing {from_name}! "
                f"We’d really appreciate a quick review if you have a moment."
            )
    else:
        body = f"Reminder from {from_name} about your appointment."

    return send_sms(phone, body)


def _booking_link_for_slug(tenant_slug: str) -> str | None:
    """
    Build a tenant-specific booking link from config.BOOKING_LINK.

    If BOOKING_LINK is like:
      https://saas-mvp-hvac-1.onrender.com/book/index.html?

    Then return:
      https://saas-mvp-hvac-1.onrender.com/book/index.html?tenant=<tenant_slug>
    """
    base = (getattr(config, "BOOKING_LINK", "") or "").strip()
    if not base:
        return None

    # drop any existing ?query
    base = base.split("?", 1)[0]
    return f"{base}?tenant={tenant_slug}"


def _booking_link_for_slug(tenant_slug: str) -> str | None:
    """
    Build a tenant-specific booking link from config.BOOKING_LINK.

    If BOOKING_LINK is like:
      https://saas-mvp-hvac-1.onrender.com/book/index.html?

    Then return:
      https://saas-mvp-hvac-1.onrender.com/book/index.html?tenant=<tenant_slug>
    """
    base = (getattr(config, "BOOKING_LINK", "") or "").strip()
    if not base:
        return None

    # drop any existing ?query
    base = base.split("?", 1)[0]
    return f"{base}?tenant={tenant_slug}"


def lead_auto_reply_sms(tenant_id: str, payload: dict) -> bool:
    """
    Auto-reply to a new lead.
    payload expects: name, phone, (optional) source
    """
    phone = (payload.get("phone") or "").strip()
    if not phone:
        return False

    brand = get_brand_for_tenant(tenant_id)
    business_name = brand.get("business_name") or tenant_id

    name = payload.get("name") or "there"

    # 🚫 DO NOT trust payload["booking_link"] anymore – it may be a /public/* backend URL.
    # ✅ Always derive from config / brand.
    booking_link = (
        brand.get("booking_link")
        or _booking_link_for_slug(tenant_id)
    )

    if booking_link:
        body = (
            f"Thanks for reaching out to {business_name}! "
            f"We got your request, {name}. "
            f"You can also book online here: {booking_link}"
        )
    else:
        body = (
            f"Thanks for reaching out to {business_name}! "
            f"We got your request, {name}. We'll contact you shortly."
        )

    return send_sms(phone, body)


# Global office SMS fallback from env
OFFICE_SMS_TO = os.getenv("OFFICE_SMS_TO", "").strip()


def _office_destination_for_tenant(tenant_id: str) -> Optional[str]:
    """
    Determine where to send owner / office notifications.

    Priority:
      1. TenantSettings.office_sms_to
      2. Global OFFICE_SMS_TO env
    """
    brand = get_brand_for_tenant(tenant_id)
    if brand.get("office_sms_to"):
        return brand["office_sms_to"]
    return OFFICE_SMS_TO or None


def lead_office_notify_sms(tenant_id: str, payload: dict) -> bool:
    """
    SMS to the BUSINESS OWNER when a new lead comes in.

    Uses per-tenant office_sms_to if set, else global OFFICE_SMS_TO.
    """
    office_to = _office_destination_for_tenant(tenant_id)
    if not office_to:
        print("[lead_office_notify_sms] No office SMS destination; skipping owner SMS")
        return False

    brand = get_brand_for_tenant(tenant_id)
    from_name = brand.get("business_name") or tenant_id

    name = (payload.get("name") or "").strip() or "Unknown"
    phone = payload.get("phone") or "N/A"
    email = (payload.get("email") or "").strip() or "N/A"

    # 1) Try known keys for the message
    raw_message = (
        payload.get("message")
        or payload.get("note")
        or payload.get("notes")
        or payload.get("detail")
        or payload.get("description")
        or ""
    )
    raw_message = (raw_message or "").strip()

    # 2) If still empty, build a message from "all other fields"
    if not raw_message:
        extra_parts = []
        for key, value in payload.items():
            if key in ("name", "phone", "email"):
                continue
            if value is None:
                continue
            text_val = str(value).strip()
            if not text_val:
                continue
            extra_parts.append(f"{key}: {text_val}")

        if extra_parts:
            raw_message = "; ".join(extra_parts)

    # 3) Final fallback
    message = raw_message or "(no message)"

    lines = [
        f"New lead for {from_name}:",
        f"Name: {name}",
        f"Phone: {phone}",
        f"Email: {email}",
        f"Message: {message[:200]}",
    ]
    body = "\n".join(lines)

    return send_sms(office_to, body)


def booking_office_notify_sms(tenant_id: str, payload: dict) -> bool:
    """
    Notify the office when a new booking is created.
    Uses per-tenant office_sms_to if set, else global OFFICE_SMS_TO.
    """
    office_to = _office_destination_for_tenant(tenant_id)
    if not office_to:
        print("[SMS] No office SMS destination; skipping office notify for booking.")
        return False

    brand = get_brand_for_tenant(tenant_id)
    from_name = brand.get("business_name") or tenant_id

    name = (payload.get("name") or "").strip() or "Unknown"
    phone = payload.get("phone") or ""
    service = payload.get("service") or "service"
    starts_iso = payload.get("starts_at_iso") or ""
    pretty_when = format_pretty_time(starts_iso) if starts_iso else ""

    msg = (
        f"New booking for {from_name}:\n"
        f"Name: {name} ({phone})\n"
        f"Service: {service}\n"
        f"When: {pretty_when or starts_iso or 'N/A'}"
    )

    return send_sms(office_to, msg)


# ---------- System alert SMS (add-only block) ----------

# Hard-coded alert destination for server errors (Peyton)
ALERT_SMS_TO = "+18145642212"


def alert_sms(message: str) -> bool:
    """
    Fire-and-forget alert SMS for *system errors*.
    Always goes to ALERT_SMS_TO (your number), with a short prefix + truncation.
    """
    dest = ALERT_SMS_TO
    if not dest:
        print("[ALERT SMS] No ALERT_SMS_TO set; skipping.")
        return False

    prefix = datetime.now().strftime("%m/%d %H:%M")
    body = f"[ALERT {prefix}] {message}"
    if len(body) > 320:
        body = body[:320]

    return send_sms(dest, body)
