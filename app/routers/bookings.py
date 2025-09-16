from __future__ import annotations
import os
from datetime import timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from dateutil import parser as dateparser
from googleapiclient.errors import HttpError

from app.services.google_calendar import ensure_service, create_event
from app.services.sms import send_sms
from app import storage, config

router = APIRouter(tags=["booking"])

class BookIn(BaseModel):
    start: str
    end: str                                   # keep end required (matches your current server)
    duration_minutes: int | None = None
    name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    notes: str | None = None

class BookOut(BaseModel):
    ok: bool
    event_id: str | None = None
    html_link: str | None = None
    sms_sent: bool = False

@router.post("/book", response_model=BookOut)
def book(payload: BookIn):
    try:
        tz_str = os.getenv("TZ", "America/New_York")
        cal_id = [c.strip() for c in os.getenv("GOOGLE_CALENDAR_IDS", "primary").split(",") if c.strip()][0]

        # parse datetimes
        try:
            start_dt = dateparser.isoparse(payload.start)
            end_dt = dateparser.isoparse(payload.end)
        except Exception:
            raise HTTPException(400, "Invalid 'start' or 'end' datetime (use ISO8601)")

        # google service (ok even for read-only)
        try:
            svc, creds = ensure_service()
        except PermissionError:
            raise HTTPException(401, "Not authorized with Google. Visit /oauth/google/start")

        scopes = set(creds.scopes or [])
        has_write = any(s.endswith("/auth/calendar") for s in scopes)
        print(f"[BOOK] scopes={scopes} has_write={has_write}")

        ev = None
        if has_write:
            try:
                ev = create_event(
                    svc,
                    calendar_id=cal_id,
                    summary=f"Service appointment — {config.FROM_NAME}",
                    description=(payload.notes or ""),
                    start_dt=start_dt,
                    end_dt=end_dt,
                    tz_str=tz_str,
                    attendee_email=(str(payload.email) if payload.email else None),
                    attendee_name=payload.name,
                )
                print(f"[BOOK] created event id={ev.get('id')}")
            except HttpError as e:
                print(f"[BOOK][create_event][HttpError] {e!r}")
                ev = None
            except Exception as e:
                print(f"[BOOK][create_event][Exception] {e!r}")
                ev = None

        # SMS confirmation (DRY RUN honored by send_sms)
        sms_ok = False
        if payload.phone:
            z = ZoneInfo(tz_str)
            s_local = (start_dt if start_dt.tzinfo else start_dt.replace(tzinfo=timezone.utc)).astimezone(z)
            pretty = s_local.strftime("%I:%M %p on %a %b %d").lstrip("0")
            link = (ev.get("htmlLink") if ev else "") or ""
            body = f"You're booked with {config.FROM_NAME} at {pretty}.{(' Details: ' + link) if link else ''}"
            sms_ok = send_sms(payload.phone, body)

        # log booking row
        from datetime import timezone as _tz
        storage.save_booking(
            event_id=(ev.get("id", "") if ev else ""),
            invitee_name=payload.name or "",
            invitee_email=str(payload.email or ""),
            invitee_phone=payload.phone or "",
            start_time=start_dt.astimezone(_tz.utc).isoformat().replace("+00:00", "Z"),
            end_time=end_dt.astimezone(_tz.utc).isoformat().replace("+00:00", "Z"),
            tz_str=tz_str,
            notes=payload.notes or "",
            sms_sent=sms_ok,
            source="api",
        )

        return BookOut(
            ok=True,
            event_id=(ev.get("id") if ev else None),
            html_link=(ev.get("htmlLink") if ev else None),
            sms_sent=sms_ok,
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print("[BOOK][ERROR]", repr(e))
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"{e.__class__.__name__}: {e}")
