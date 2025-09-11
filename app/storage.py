# app/storage.py
from pathlib import Path
import csv
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from app import config

# Resolve CSV path (absolute respected; relative goes under project root)
BASE_DIR = Path(__file__).resolve().parents[1]  # .../SaaSMVP
CSV_PATH = (
    Path(config.LEADS_CSV)
    if Path(config.LEADS_CSV).is_absolute()
    else BASE_DIR / config.LEADS_CSV
)

FIELDS = [
    "lead_id", "created_at", "source",
    "name", "phone", "email", "message",
    "sms_body", "sms_sent"
]

def _now_iso() -> str:
    try:
        tz = ZoneInfo(config.TZ)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")  # fallback on Windows if tzdata missing
    return datetime.now(tz).isoformat(timespec="seconds")

def save_lead(lead: dict, sms_body: str, sms_sent: bool, source: str = "api"):
    """
    Append one lead to the CSV, creating the header if it's a new file.
    """
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0

    row = {
        "lead_id": str(uuid.uuid4()),
        "created_at": _now_iso(),
        "source": source,
        "name": lead.get("name") or "",
        "phone": lead.get("phone") or "",
        "email": lead.get("email") or "",
        "message": lead.get("message") or "",
        "sms_body": sms_body,
        "sms_sent": "true" if sms_sent else "false",
    }

    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)

def read_leads(limit: int = 20) -> list[dict]:
    """
    Return the last N leads (most recent first).
    """
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))[:max(0, limit)]
from datetime import timedelta

def _parse_dt(s: str):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def sent_recently(phone: str, minutes: int = 120) -> bool:
    """
    True if we've sent an SMS to this phone within the last `minutes`.
    Checks rows with sms_sent == 'true'.
    """
    if not CSV_PATH.exists():
        return False

    try:
        with CSV_PATH.open("r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return False

    for row in reversed(rows):  # newest first
        if (row.get("phone") or "").strip() != phone.strip():
            continue
        if (row.get("sms_sent") or "").lower() != "true":
            continue
        dt = _parse_dt(row.get("created_at", ""))
        if not dt:
            continue
        # if naive, assume configured TZ
        if not dt.tzinfo:
            try:
                dt = dt.replace(tzinfo=ZoneInfo(config.TZ))
            except Exception:
                pass
        try:
            now = datetime.now(ZoneInfo(config.TZ))
        except Exception:
            now = datetime.utcnow()
        if now - dt <= timedelta(minutes=minutes):
            return True
    return False

# --- bookings CSV support ---
from pathlib import Path
import csv, uuid
from datetime import datetime, timezone

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
CSV_BOOKINGS = DATA_DIR / "bookings.csv"
BOOKING_FIELDS = [
    "booking_id","created_at","source",
    "event_id","invitee_name","invitee_email","invitee_phone",
    "start_time","end_time","timezone","notes","sms_sent",
]

def save_booking(event_id: str, invitee_name: str, invitee_email: str, invitee_phone: str,
                 start_time: str, end_time: str, tz_str: str, notes: str, sms_sent: bool,
                 source: str = "calendly"):
    new_file = not CSV_BOOKINGS.exists() or CSV_BOOKINGS.stat().st_size == 0
    row = {
        "booking_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "event_id": event_id or "",
        "invitee_name": invitee_name or "",
        "invitee_email": invitee_email or "",
        "invitee_phone": invitee_phone or "",
        "start_time": start_time or "",
        "end_time": end_time or "",
        "timezone": tz_str or "",
        "notes": notes or "",
        "sms_sent": "true" if sms_sent else "false",
    }
    with CSV_BOOKINGS.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=BOOKING_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(row)

def read_bookings(limit: int = 20) -> list[dict]:
    if not CSV_BOOKINGS.exists():
        return []
    with CSV_BOOKINGS.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))[:max(0, limit)]
