from __future__ import annotations
import os, json
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
        expiry_dt = datetime.fromtimestamp(tenant.gcal_token_expires_at, tz=timezone.utc)

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
                tenant.gcal_token_expires_at = int(creds.expiry.timestamp())
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
