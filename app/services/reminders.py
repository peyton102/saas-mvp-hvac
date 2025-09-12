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
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _reminder_offsets() -> list[timedelta]:
    spec = getattr(config, "REMINDERS", "24h,2h")
    out: list[timedelta] = []
    for part in spec.split(","):
        p = part.strip().lower()
        if not p: continue
        if p.endswith("h"): out.append(timedelta(hours=float(p[:-1])))
        elif p.endswith("m"): out.append(timedelta(minutes=float(p[:-1])))
    return out or [timedelta(hours=24), timedelta(hours=2)]

def preview_due_reminders(now: datetime | None = None, look_back_minutes: int | None = None) -> List[Dict[str, Any]]:
    tz = _tz()
    now_local = now.astimezone(tz) if now else datetime.now(tz)
    window_sec = int(getattr(config, "REMINDER_WINDOW_SECONDS", 600))
    offsets = _reminder_offsets()

    bookings = storage.read_bookings(limit=1000)
    due: list[dict] = []

    for b in bookings:
        phone = (b.get("invitee_phone") or "").strip()
        if not phone:
            continue
        start_dt = _parse_iso(b.get("start_time") or "")
        if not start_dt:
            continue
        start_local = start_dt.astimezone(tz)

        for off in offsets:
            target = start_local - off
            delta_s = (now_local - target).total_seconds()
            if abs(delta_s) <= window_sec or (look_back_minutes and 0 <= delta_s <= look_back_minutes * 60):
                total_min = int(off.total_seconds() // 60)
                hrs, mins = divmod(total_min, 60)
                when_txt = f"{hrs}h" if mins == 0 else (f"{mins}m" if hrs == 0 else f"{hrs}h{mins}m")
                time_str = start_local.strftime("%I:%M %p on %a %b %d").lstrip("0")
                msg = (
                    f"Reminder: your appointment with {config.FROM_NAME} is at {time_str} "
                    f"({getattr(config, 'TZ', 'America/New_York')}). To reschedule: {config.BOOKING_LINK}"
                )
                due.append({
                    "phone": phone,
                    "offset": when_txt,
                    "start_time_local": start_local.isoformat(timespec="minutes"),
                    "message": msg,
                })
    return due
