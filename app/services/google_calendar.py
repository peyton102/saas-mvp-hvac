from __future__ import annotations
import os, json, re
from pathlib import Path
from typing import List, Tuple
from datetime import datetime, timedelta, time as dtime, timezone
from dateutil import parser as dateparser
from zoneinfo import ZoneInfo
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from app import config

# --- scopes & OAuth flow
def _scopes() -> List[str]:
    s = os.getenv("GOOGLE_SCOPES", "https://www.googleapis.com/auth/calendar.readonly")
    return [p.strip() for p in s.replace(" ", ",").split(",") if p.strip()] or \
           ["https://www.googleapis.com/auth/calendar.readonly"]

def build_flow() -> Flow:
    cid = os.getenv("GOOGLE_CLIENT_ID")
    csec = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    if not (cid and csec and redirect):
        raise RuntimeError("Missing GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_OAUTH_REDIRECT_URI")
    cfg = {"web": {
        "client_id": cid,
        "client_secret": csec,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }}
    return Flow.from_client_config(cfg, scopes=_scopes(), redirect_uri=redirect)

# --- token storage (single-user dev)
def _token_path() -> Path:
    d = Path(os.getenv("GOOGLE_TOKEN_DIR", "data/google_tokens"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "default.json"

def save_creds(creds: Credentials) -> None:
    _token_path().write_text(creds.to_json(), encoding="utf-8")

def load_creds() -> Credentials | None:
    fp = _token_path()
    if not fp.exists(): return None
    creds = Credentials.from_authorized_user_info(
        json.loads(fp.read_text(encoding="utf-8")), scopes=_scopes()
    )
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request()); save_creds(creds)
    return creds

def ensure_service():
    creds = load_creds()
    if not creds:
        raise PermissionError("Not authorized with Google yet")
    svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return svc, creds

# --- calendar helpers
def freebusy(svc, *, start_iso: str, end_iso: str, tz_str: str, calendar_ids: List[str]) -> List[Tuple[datetime, datetime]]:
    body = {"timeMin": start_iso, "timeMax": end_iso, "timeZone": tz_str,
            "items": [{"id": c} for c in calendar_ids if c]}
    resp = svc.freebusy().query(body=body).execute()
    intervals: List[Tuple[datetime, datetime]] = []
    for info in resp.get("calendars", {}).values():
        for b in info.get("busy", []):
            intervals.append((dateparser.isoparse(b["start"]), dateparser.isoparse(b["end"])))
    intervals.sort(key=lambda x: x[0])
    merged: List[Tuple[datetime, datetime]] = []
    for s, e in intervals:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
    return merged

def generate_slots(
    *, start: datetime, end: datetime, tz_str: str,
    busy: List[Tuple[datetime, datetime]],
    business_hours: str, slot_minutes: int, buffer_minutes: int = 0
) -> List[dict]:
    local = ZoneInfo(tz_str)
    start = (start if start.tzinfo else start.replace(tzinfo=timezone.utc)).astimezone(local)
    end = (end if end.tzinfo else end.replace(tzinfo=timezone.utc)).astimezone(local)

    bh_start_s, bh_end_s = business_hours.split("-")
    bh_start = dtime.fromisoformat(bh_start_s)
    bh_end = dtime.fromisoformat(bh_end_s)

    expanded = []
    for s, e in busy:
        s = (s if s.tzinfo else s.replace(tzinfo=timezone.utc)).astimezone(local) - timedelta(minutes=buffer_minutes)
        e = (e if e.tzinfo else e.replace(tzinfo=timezone.utc)).astimezone(local) + timedelta(minutes=buffer_minutes)
        expanded.append((s, e))

    out: List[dict] = []
    day = start.date()
    while day <= end.date():
        day_start = datetime.combine(day, bh_start, tzinfo=local)
        day_end = datetime.combine(day, bh_end, tzinfo=local)
        cur = max(day_start, start); stop = min(day_end, end)
        while cur + timedelta(minutes=slot_minutes) <= stop:
            slot_start = cur; slot_end = cur + timedelta(minutes=slot_minutes)
            conflict = any(not (slot_end <= bs or slot_start >= be) for bs, be in expanded)
            if not conflict:
                out.append({"start": slot_start.isoformat(), "end": slot_end.isoformat()})
            cur += timedelta(minutes=slot_minutes)
        day = day + timedelta(days=1)
    return out
def create_event(
    svc,
    *,
    calendar_id: str,
    summary: str,
    description: str,
    start_dt,
    end_dt,
    tz_str: str,
    attendee_email: str | None = None,
    attendee_name: str | None = None,
):
    """
    Inserts a timed event. Datetimes can be naive or tz-aware; we coerce to tz_str.
    Returns the created event dict (includes 'id' and 'htmlLink').
    """
    def _to_local_iso(dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(tz_str)).isoformat(timespec="seconds")

    body = {
        "summary": summary,
        "description": description or "",
        "start": {"dateTime": _to_local_iso(start_dt), "timeZone": tz_str},
        "end":   {"dateTime": _to_local_iso(end_dt),   "timeZone": tz_str},
    }

    attendees = []
    if attendee_email:
        a = {"email": attendee_email}
        if attendee_name:
            a["displayName"] = attendee_name
        attendees.append(a)
    if attendees:
        body["attendees"] = attendees

    ev = svc.events().insert(calendarId=calendar_id, body=body).execute()
    return ev


def get_service():
    """
    Return an authorized Google Calendar API service using the saved OAuth token file.
    Legacy single-user mode. Use get_service_for_tenant() for per-tenant calendar sync.
    """
    token_dir = getattr(config, "GOOGLE_TOKEN_DIR", "data/google_tokens")
    token_path = Path(token_dir) / "default.json"
    if not token_path.exists():
        raise RuntimeError(f"Google token not found at {token_path}. Re-auth at /oauth/google/start")
    scopes = str(getattr(config, "GOOGLE_SCOPES", "")).split()
    if not scopes:
        scopes = ["https://www.googleapis.com/auth/calendar"]
    creds = Credentials.from_authorized_user_file(str(token_path), scopes=scopes)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def get_service_for_tenant(tenant, session):
    """
    Return an authorized Google Calendar API service for the given Tenant row.
    Reads tokens from the tenant DB row; auto-refreshes if expired and saves back.
    Returns None if the tenant has not connected Google Calendar (no refresh token).
    On refresh failure (revoked access), nulls out the tokens and returns None.
    """
    if not tenant.gcal_refresh_token:
        return None

    cid = os.getenv("GOOGLE_CLIENT_ID")
    csec = os.getenv("GOOGLE_CLIENT_SECRET")
    if not (cid and csec):
        print("[GCAL] Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET env vars")
        return None

    expiry_dt = None
    if tenant.gcal_token_expires_at:
        # google-auth uses naive UTC datetimes internally — must pass naive here
        expiry_dt = datetime.utcfromtimestamp(tenant.gcal_token_expires_at)

    creds = Credentials(
        token=tenant.gcal_access_token,
        refresh_token=tenant.gcal_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cid,
        client_secret=csec,
        scopes=_scopes(),
        expiry=expiry_dt,
    )

    if not creds.valid:
        try:
            creds.refresh(Request())
            tenant.gcal_access_token = creds.token
            if creds.expiry:
                # creds.expiry is naive UTC — use timegm to avoid server-tz assumptions
                import calendar as _cal
                tenant.gcal_token_expires_at = _cal.timegm(creds.expiry.timetuple())
            session.add(tenant)
            session.commit()
        except Exception as e:
            print(f"[GCAL] Token refresh failed for tenant '{getattr(tenant, 'slug', '?')}': {e!r}")
            tenant.gcal_refresh_token = None
            tenant.gcal_access_token = None
            tenant.gcal_token_expires_at = None
            session.add(tenant)
            session.commit()
            return None

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Inbound sync: Google Calendar → Torevez
# ---------------------------------------------------------------------------

# Matches most common US phone formats: 555-123-4567 / (555) 123-4567 / 5551234567 / +15551234567
_PHONE_RE = re.compile(
    r'(?<!\d)'
    r'(?:\+?1[\s.\-]?)?'
    r'(?:\(?\d{3}\)?[\s.\-]?)'
    r'\d{3}[\s.\-]?\d{4}'
    r'(?!\d)',
)


def _parse_phone(text: str) -> str:
    """Return first US phone number found in text, or ''."""
    m = _PHONE_RE.search(text or "")
    return m.group(0).strip() if m else ""


def _parse_event_dt(dt_obj: dict) -> datetime | None:
    """
    Parse a Google Calendar start/end object to a UTC-naive datetime.
    Returns None for all-day events (date-only) or unparseable values.
    """
    dt_str = (dt_obj or {}).get("dateTime")
    if not dt_str:
        return None  # all-day event — no time, skip
    try:
        dt = dateparser.isoparse(dt_str)
        if dt.tzinfo:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _parse_event(event: dict) -> dict:
    """
    Extract name, phone, email, notes from a Google Calendar event with no format assumptions.

    Scans ALL text fields together (summary, description, location, attendee names/emails)
    so phone numbers and names are found regardless of where the office manager puts them.

    Name priority:  (1) first non-organizer attendee display name
                    (2) event summary as-is (no prefix stripping)
                    (3) "Unknown"
    Phone:          regex scan of the full combined text blob
    Email:          first non-organizer attendee email
    Notes:          raw description stored verbatim
    """
    summary     = (event.get("summary")     or "").strip()
    description = (event.get("description") or "").strip()
    location    = (event.get("location")    or "").strip()

    attendees      = event.get("attendees") or []
    organizer_email = (event.get("organizer") or {}).get("email", "")

    customer = next(
        (a for a in attendees if a.get("email") != organizer_email and not a.get("self")),
        None,
    )

    # Name
    name = ""
    if customer:
        name = (customer.get("displayName") or "").strip()
    if not name:
        name = summary or "Unknown"

    # Email
    email = (customer.get("email") or "").strip() if customer else ""

    # Phone — scan everything combined so it doesn't matter where the number lives
    combined = " ".join(filter(None, [
        summary,
        description,
        location,
        *[a.get("displayName", "") for a in attendees],
        *[a.get("email", "")        for a in attendees],
    ]))
    phone = _parse_phone(combined)

    return {"name": name, "email": email, "phone": phone, "notes": description}


def establish_sync_token(tenant, session) -> bool:
    """
    Page through the tenant's calendar from now onwards to get a nextSyncToken
    without importing any events. Call once right after OAuth so the cron job
    only picks up events created AFTER the connection was made.
    Returns True on success.
    """
    svc = get_service_for_tenant(tenant, session)
    if not svc:
        return False

    calendar_id = (tenant.gcal_calendar_id or "primary").strip()

    try:
        resp = svc.events().list(
            calendarId=calendar_id,
            timeMin=datetime.now(timezone.utc).isoformat(),
            singleEvents=True,
            maxResults=2500,
        ).execute()

        # nextSyncToken only appears on the last page — paginate to exhaust
        while resp.get("nextPageToken"):
            resp = svc.events().list(
                calendarId=calendar_id,
                pageToken=resp["nextPageToken"],
                singleEvents=True,
                maxResults=2500,
            ).execute()

        sync_token = resp.get("nextSyncToken")
        if sync_token:
            tenant.gcal_sync_token = sync_token
            tenant.gcal_last_synced_at = datetime.utcnow()
            session.add(tenant)
            session.commit()
            return True
        return False
    except Exception as e:
        print(f"[GCAL] establish_sync_token failed for '{getattr(tenant, 'slug', '?')}': {e!r}")
        return False


def sync_new_bookings(tenant, session) -> dict:
    """
    Fetch new/changed Google Calendar events for one tenant and import them as Booking rows.
    Fires confirmation SMS + office SMS + email for each import, exactly like a direct booking.
    Returns {"imported": N, "skipped": N, "errors": [...]}.
    """
    from app.models import Booking as BookingModel
    from sqlmodel import select as _select
    from app.services.sms import booking_confirmation_sms, booking_office_notify_sms
    from app.services.email import send_booking_confirmation
    from app.utils.phone import normalize_us_phone
    from app.routers.tenant import get_tenant_tz

    result: dict = {"imported": 0, "skipped": 0, "errors": []}

    # No sync token yet — establish baseline now, import nothing this run
    if not tenant.gcal_sync_token:
        establish_sync_token(tenant, session)
        return result

    svc = get_service_for_tenant(tenant, session)
    if svc is None:
        return result

    calendar_id = (tenant.gcal_calendar_id or "primary").strip()

    try:
        resp = svc.events().list(
            calendarId=calendar_id,
            syncToken=tenant.gcal_sync_token,
            singleEvents=True,
            maxResults=2500,
        ).execute()
    except Exception as e:
        err = str(e)
        if "410" in err or "Gone" in err or "fullSyncRequired" in err:
            # Sync token expired — reset baseline, pick up new events next run
            print(f"[GCAL SYNC] Sync token expired for '{tenant.slug}', resetting baseline")
            tenant.gcal_sync_token = None
            session.add(tenant)
            session.commit()
            establish_sync_token(tenant, session)
            return result
        result["errors"].append(err)
        return result

    tenant_tz = get_tenant_tz(tenant.slug, session)

    for event in (resp.get("items") or []):
        try:
            if event.get("status") == "cancelled":
                result["skipped"] += 1
                continue

            gcal_event_id = event.get("id", "")
            if not gcal_event_id:
                result["skipped"] += 1
                continue

            # Dedup — skip if already imported
            if session.exec(
                _select(BookingModel)
                .where(BookingModel.tenant_id == tenant.slug)
                .where(BookingModel.gcal_event_id == gcal_event_id)
            ).first():
                result["skipped"] += 1
                continue

            start_dt = _parse_event_dt(event.get("start") or {})
            end_dt = _parse_event_dt(event.get("end") or {})
            if start_dt is None:
                result["skipped"] += 1  # all-day event
                continue
            if end_dt is None:
                end_dt = start_dt + timedelta(hours=1)

            parsed = _parse_event(event)

            # Import criteria: must have a start time AND (phone OR non-empty title)
            event_summary = (event.get("summary") or "").strip()
            if not event_summary and not parsed["phone"]:
                result["skipped"] += 1
                continue

            name = parsed["name"]
            email = parsed["email"] or None
            e164 = normalize_us_phone(parsed["phone"]) if parsed["phone"] else ""
            notes = parsed["notes"] or None

            session.add(BookingModel(
                tenant_id=tenant.slug,
                name=name,
                phone=e164 or "",
                email=email,
                start=start_dt,
                end=end_dt,
                notes=notes,
                source="google_calendar",
                gcal_event_id=gcal_event_id,
            ))
            session.commit()

            # Localize start time for SMS/email display
            start_local_iso = (
                start_dt.replace(tzinfo=timezone.utc)
                .astimezone(tenant_tz)
                .isoformat(timespec="seconds")
            )
            sms_payload = {
                "name": name,
                "phone": e164 or "",
                "service": "appointment",
                "starts_at_iso": start_local_iso,
            }

            if e164:
                try:
                    booking_confirmation_sms(tenant.slug, sms_payload)
                except Exception as ex:
                    print(f"[GCAL SYNC] Customer SMS error (event {gcal_event_id}): {ex!r}")

            try:
                booking_office_notify_sms(tenant.slug, sms_payload)
            except Exception as ex:
                print(f"[GCAL SYNC] Office SMS error (event {gcal_event_id}): {ex!r}")

            if email:
                try:
                    send_booking_confirmation(tenant.slug, {
                        "name": name,
                        "email": email,
                        "phone": e164 or "",
                        "address": "",
                        "service": "appointment",
                        "starts_at_iso": start_local_iso,
                        "reschedule_url": getattr(config, "BOOKING_LINK", "") or "",
                    })
                except Exception as ex:
                    print(f"[GCAL SYNC] Email error (event {gcal_event_id}): {ex!r}")

            result["imported"] += 1

        except Exception as ex:
            print(f"[GCAL SYNC] Error on event {event.get('id', '?')}: {ex!r}")
            result["errors"].append(str(ex))
            try:
                session.rollback()
            except Exception:
                pass

    # Persist new sync token and last-synced timestamp
    new_token = resp.get("nextSyncToken")
    if new_token:
        tenant.gcal_sync_token = new_token
    tenant.gcal_last_synced_at = datetime.utcnow()
    session.add(tenant)
    session.commit()

    return result
