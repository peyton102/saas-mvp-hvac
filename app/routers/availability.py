import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter
from dateutil import parser as dateparser
from app.services.google_calendar import ensure_service, load_creds, freebusy, generate_slots

router = APIRouter()

@router.get("/availability")
def availability(start: str | None = None, end: str | None = None):
    if not load_creds():
        return {"ok": False, "authorized": False, "authorize_url": "/oauth/google/start"}

    tz_str = os.getenv("TZ", "America/New_York")
    cal_ids = [c.strip() for c in os.getenv("GOOGLE_CALENDAR_IDS", "primary").split(",") if c.strip()]
    business_hours = os.getenv("BUSINESS_HOURS", "09:00-17:00")
    slot_minutes = int(os.getenv("SLOT_MINUTES", "60"))
    buffer_minutes = int(os.getenv("SLOT_BUFFER_MINUTES", "0"))

    now = datetime.now(timezone.utc)
    start_dt = dateparser.isoparse(start) if start else now
    end_dt = dateparser.isoparse(end) if end else (now + timedelta(days=7))

    svc, _ = ensure_service()
    busy = freebusy(
        svc,
        start_iso=start_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        end_iso=end_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        tz_str=tz_str,
        calendar_ids=cal_ids,
    )
    slots = generate_slots(
        start=start_dt,
        end=end_dt,
        tz_str=tz_str,
        busy=busy,
        business_hours=business_hours,
        slot_minutes=slot_minutes,
        buffer_minutes=buffer_minutes,
    )
    return {"ok": True, "authorized": True, "count": len(slots), "slots": slots}
