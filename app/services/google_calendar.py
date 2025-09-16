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
    tz_str: str,
    start: datetime,
    end: datetime,
    summary: str,
    description: str | None = None,
    attendees: list[str] | None = None,
):
    body = {
        "summary": summary,
        "description": description or "",
        "start": {"dateTime": start.isoformat(), "timeZone": tz_str},
        "end": {"dateTime": end.isoformat(), "timeZone": tz_str},
    }
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees if e]
    ev = svc.events().insert(calendarId=calendar_id, body=body).execute()
    return {"id": ev.get("id"), "htmlLink": ev.get("htmlLink")}
# --- create event helper (simple MVP)
def create_event(
    svc,
    *,
    calendar_id: str,
    summary: str,
    description: str | None,
    start_dt,   # datetime (aware or naive)
    end_dt,     # datetime (aware or naive)
    tz_str: str,
    attendee_email: str | None = None,
    attendee_name: str | None = None,
) -> dict:
    """
    Inserts a timed event into Google Calendar.
    Returns {'id': ..., 'htmlLink': ..., 'start': ..., 'end': ...}
    """
    from datetime import timezone
    from zoneinfo import ZoneInfo

    z = ZoneInfo(tz_str)
    # normalize to desired timezone and ISO8601
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    start_iso = start_dt.astimezone(z).isoformat()
    end_iso = end_dt.astimezone(z).isoformat()

    attendees = []
    if attendee_email:
        att = {"email": attendee_email}
        if attendee_name:
            att["displayName"] = attendee_name
        attendees.append(att)

    body = {
        "summary": summary,
        "description": description or "",
        "start": {"dateTime": start_iso, "timeZone": tz_str},
        "end": {"dateTime": end_iso, "timeZone": tz_str},
        "attendees": attendees,
    }

    ev = svc.events().insert(calendarId=calendar_id, body=body).execute()
    return {
        "id": ev.get("id"),
        "htmlLink": ev.get("htmlLink"),
        "start": ev.get("start", {}).get("dateTime"),
        "end": ev.get("end", {}).get("dateTime"),
    }
