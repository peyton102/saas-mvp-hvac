# app/services/reminders.py
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import List, Dict, Any

from app import config, storage


def _tz():
    try:
        return ZoneInfo(getattr(config, "TZ", "America/New_York"))
    except ZoneInfoNotFoundError:
        return timezone.utc


def _parse_iso(s: str | None) -> datetime | None:
    """Parse ISO timestamps like '2025-09-15T14:00:00Z' or with offsets."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _reminder_offsets() -> list[timedelta]:
    """
    Read desired reminder offsets from config.REMINDERS (e.g., '24h,2h').
    Supports 'h' (hours) and 'm' (minutes). Defaults to [24h, 2h].
    """
    spec = getattr(config, "REMINDERS", "24h,2h")
    out: list[timedelta] = []
    for part in spec.split(","):
        part = part.strip().lower()
        if not part:
            continue
        if part.endswith("h"):
            out.append(timedelta(hours=float(part[:-1])))
        elif part.endswith("m"):
            out.append(timedelta(minutes=float(part[:-1])))
    return out or [timedelta(hours=24), timedelta(hours=2)]


def preview_due_reminders(
    now: datetime | None = None,
    look_back_minutes: int | None = None,
) -> List[Dict[str, Any]]:
    """
    Return a list of reminder payloads that would be sent *right now*.
    - Uses bookings from storage.read_bookings(limit=1000)
    - A reminder is 'due' if now is within REMINDER_WINDOW_SECONDS of the target time.
    - look_back_minutes lets you catch recently-missed reminders (optional).
    """
    tz = _tz()
    now_local = now.astimezone(tz) if now else datetime.now(tz)
    window_sec = int(getattr(config, "REMINDER_WINDOW_SECONDS", 600))  # 10 minutes default
    offsets = _reminder_offsets()

    bookings = storage.read_bookings(limit=1000)
    due: list[dict] = []

    for b in bookings:
        phone = (b.get("invitee_phone") or "").strip()
        if not phone:
            continue

        start_raw = b.get("start_time") or ""
        start_dt = _parse_iso(start_raw)
        if not start_dt:
            continue

        start_local = start_dt.astimezone(tz)

        for off in offsets:
            target = start_local - off
            delta_s = (now_local - target).total_seconds()
            if abs(delta_s) <= window_sec or (
                look_back_minutes and 0 <= delta_s <= look_back_minutes * 60
            ):
                # Human-friendly "when" text
                total_min = int(off.total_seconds() // 60)
                hrs, mins = divmod(total_min, 60)
                when_txt = f"{hrs}h" if mins == 0 else (f"{mins}m" if hrs == 0 else f"{hrs}h{mins}m")

                # Time string portable across OS (no %-I)
                time_str = start_local.strftime("%I:%M %p on %a %b %d").lstrip("0")
                msg = (
                    f"Reminder: your appointment with {config.FROM_NAME} is at {time_str} "
                    f"({getattr(config, 'TZ', 'America/New_York')}). "
                    f"To reschedule: {config.BOOKING_LINK}"
                )

                due.append({
                    "phone": phone,
                    "offset": when_txt,                 # e.g., '24h' or '2h'
                    "start_time_local": start_local.isoformat(timespec="minutes"),
                    "message": msg,
                })

    return due
