# app/routers/public.py
from fastapi import APIRouter, Request, Response, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel, Field
from app import config
from app.services.email import send_booking_confirmation, send_booking_reminder
from sqlmodel import Session, select
from app.db import engine, get_session
from app.models import Booking as BookingModel
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.services.sms import (
    booking_confirmation_sms,
    booking_reminder_sms,
    send_sms,
    booking_office_notify_sms,
    get_brand_for_tenant,   # 👈 add this
)
from fastapi import Depends

router = APIRouter(prefix="/public", tags=["public"])

# --- reschedule token helpers ---
import hmac, hashlib, base64, time
from urllib.parse import urlencode


def _hmac_secret() -> str:
    # Fall back so booking never breaks in dev if DEBUG_BEARER is unset
    return (getattr(config, "DEBUG_BEARER", None) or "dev-secret")


def _sign(data: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def _make_resched_token(booking_id: int, tenant: str, ttl_seconds: int = 7 * 24 * 3600) -> str:
    exp = int(time.time()) + ttl_seconds
    payload = f"{booking_id}.{tenant}.{exp}"
    sig = _sign(payload, _hmac_secret())  # safe even if DEBUG_BEARER missing
    token = f"{payload}.{sig}"
    return base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")


def _parse_resched_token(token_b64: str) -> tuple[int, str]:
    try:
        raw = base64.urlsafe_b64decode(token_b64 + "==").decode()
        booking_id_str, tenant, exp_str, sig = raw.split(".")
        payload = f"{booking_id_str}.{tenant}.{exp_str}"
        if _sign(payload, _hmac_secret()) != sig:
            raise ValueError("bad-signature")
        if int(exp_str) < int(time.time()):
            raise ValueError("expired")
        return int(booking_id_str), tenant
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad reschedule token: {e}")


@router.get("/lead-form")
def lead_form(request: Request, redirect: str = "/thanks", api_key: str | None = None, tenant_key: str | None = None):
    """
    Simple lead form.
    - If ?tenant_key=XYZ is present, the form posts to /lead?tenant_key=XYZ (browser-friendly).
    - If ?api_key=XYZ is present, JS sends it as X-API-Key (back-compat).
    """
    # prefer tenant_key; fall back to api_key
    tenant_key = tenant_key or request.query_params.get("tenant_key")
    api_key = api_key or request.query_params.get("api_key")

    # build action with tenant_key in query for zero-header embeds
    action = "/lead"
    if tenant_key:
        action += f"?tenant_key={tenant_key}"

    html = f"""
<!doctype html>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{config.FROM_NAME} — Lead Form</title>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; padding: 16px; background:#f7f7f8; }}
  .card {{ max-width: 420px; margin: 0 auto; background:#fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.06); padding: 16px; }}
  h1 {{ font-size: 18px; margin: 0 0 8px; }}
  p  {{ margin: 6px 0 14px; color:#444; }}
  label {{ display:block; font-size: 12px; color:#333; margin:10px 0 6px; }}
  input, textarea {{ width:100%; box-sizing:border-box; padding:10px; border:1px solid #ddd; border-radius:8px; font-size:14px; }}
  button {{ width:100%; margin-top:14px; padding:12px; border:0; border-radius:8px; background:#2563eb; color:#fff; font-weight:600; cursor:pointer; }}
  .hint {{ font-size:12px; color:#666; margin-top:8px; }}
  .hp {{ position:absolute; left:-10000px; width:0; height:0; opacity:0; pointer-events:none; }}
</style>
<div class="card">
  <h1>Contact {config.FROM_NAME}</h1>
  <p>Book the next available slot: <a href="{config.BOOKING_LINK}" target="_blank" rel="noopener">{config.BOOKING_LINK}</a></p>
  <form id="leadForm" autocomplete="on" action="{action}" method="post">
    <input class="hp" type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true" />
    <label>Name</label>
    <input name="name" placeholder="Full name" />
    <label>Phone *</label>
    <input name="phone" placeholder="+1XXXXXXXXXX" required />
    <label>Email</label>
    <input name="email" type="email" placeholder="you@example.com" />
    <label>Message</label>
    <textarea name="message" rows="3" placeholder="What’s going on?"></textarea>
    <button type="submit">Send</button>
    <div class="hint">We’ll text you a link to book. SMS may be in DRY-RUN during testing.</div>
  </form>
</div>
<script>
  const form = document.getElementById('leadForm');
  const qs = new URLSearchParams(window.location.search);
  const redirectTo = qs.get('redirect') || "{redirect}";
  const apiKey = qs.get('api_key') || "{api_key or ''}";

  form.addEventListener('submit', async (e) => {{
    // If action has ?tenant_key=..., just let the browser submit normally (no headers needed)
    if (form.action.includes('tenant_key=')) return;

    // Otherwise, do the fetch to attach X-API-Key (back-compat)
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    try {{
      const headers = {{ 'Content-Type':'application/json' }};
      if (apiKey) headers['X-API-Key'] = apiKey;

      const r = await fetch('/lead', {{
        method: 'POST',
        headers,
        body: JSON.stringify(data)
      }});
      if (r.ok) window.location.href = redirectTo;
      else {{
        const body = await r.text();
        alert('Submit failed: ' + body);
      }}
    }} catch (err) {{
      alert('Network error: ' + err);
    }}
  }});
</script>
"""
    return Response(content=html, media_type="text/html")


@router.get("/thanks")
def thanks():
    return Response(
        content="<h2>Thanks! We’ll be in touch shortly.</h2>",
        media_type="text/html",
    )


# ---- PUBLIC: create booking (email + SMS) ----

class PublicBookingIn(BaseModel):
    # tenant may come from body OR URL (?tenant=...), so keep it optional in body
    tenant: Optional[str] = None
    service: str = "default"
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    # accept either "notes" (normal) or legacy "note"
    notes: Optional[str] = Field(default=None, alias="note")
    # prefer starts_at_iso, but tolerate "starts_at" or "start_iso" via extra fields
    starts_at_iso: Optional[str] = None

    class Config:
        extra = "allow"  # tolerate unexpected fields like starts_at/start_iso


class PublicBookingOut(BaseModel):
    id: int
    starts_at_iso: str
    name: str
    email_sent: bool
    sms_sent: bool          # include SMS flag
    tenant: str  # echo back


@router.post("/bookings", response_model=PublicBookingOut)
def public_create_booking(
    payload: PublicBookingIn,
    tenant: Optional[str] = Query(None, description="tenant slug or key (fallback if not in body)"),
    session: Session = Depends(get_session),  # 👈 add session so we can write to BookingModel
):
    # Resolve tenant: body -> query -> default
    tenant_val = (payload.tenant or tenant or "default").strip()

    # Resolve time field from multiple possibilities
    starts_str = (
        payload.starts_at_iso
        or getattr(payload, "starts_at", None)
        or getattr(payload, "start_iso", None)
    )
    if not starts_str:
        raise HTTPException(status_code=400, detail="starts_at_iso is required")

    # 1) parse time
    try:
        starts = datetime.fromisoformat(starts_str.replace("Z", "+00:00"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad starts_at_iso: {e}")

    # ---------- A) legacy raw SQLite table (keep as-is for availability/reschedule) ----------
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tenant_key TEXT NOT NULL,
                  name TEXT NOT NULL,
                  phone TEXT,
                  email TEXT,
                  address TEXT,
                  note TEXT,
                  service TEXT,
                  starts_at TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO bookings
                  (tenant_key, name, phone, email, address, note, service, starts_at, created_at)
                VALUES
                  (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_val,
                    payload.name,
                    payload.phone,
                    payload.email,
                    payload.address,
                    payload.notes,   # handles "notes" or alias "note"
                    payload.service,
                    starts.isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            booking_id = conn.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    # ---------- B) mirror into BookingModel so /upcoming & portal see it ----------
    try:
        from zoneinfo import ZoneInfo

        BUSINESS_TZ = ZoneInfo("America/New_York")

        # Normalize to UTC for BookingModel
        if starts.tzinfo is None:
            # starts came from public HTML → treat as business local time
            starts_utc = starts.replace(tzinfo=BUSINESS_TZ).astimezone(timezone.utc)
        else:
            # already tz-aware → just normalize
            starts_utc = starts.astimezone(timezone.utc)

        end_utc = starts_utc + timedelta(hours=1)

        booking_row = BookingModel(
            tenant_id=tenant_val,
            name=payload.name or "",
            phone=(payload.phone or "") or "",
            email=(payload.email or None),
            start=starts_utc,
            end=end_utc,
            notes=(payload.notes or None),
            source="public",  # 👈 mark that this came from the public page
        )
        session.add(booking_row)
        session.commit()
    except Exception as e:
        # don't break the public booking if the mirror fails
        print(f"[PUBLIC→BookingModel mirror error] {e!r}")

    # 3) send confirmation email (with reschedule link if token works)
    try:
        token = _make_resched_token(booking_id, tenant_val)
        base_link = config.BOOKING_LINK.split("?")[0]  # e.g., http://localhost:5173/book/index.html
        reschedule_url = f"{base_link}?{urlencode({'tenant': tenant_val, 'reschedule': token})}"
    except Exception:
        # Never fail the booking if link generation hiccups
        reschedule_url = None

    email_payload = {
        "name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "address": payload.address,
        "service": payload.service,
        "starts_at_iso": starts.isoformat(),
        "reschedule_url": reschedule_url,
    }

    email_sent = send_booking_confirmation(tenant_val, email_payload)

    sms_payload = {
        "name": payload.name,
        "phone": payload.phone,
        "service": payload.service,
        "starts_at_iso": starts.isoformat(),
    }

    # Customer SMS confirmation
    sms_sent = booking_confirmation_sms(tenant_val, sms_payload)

    # Office SMS notification (doesn't affect response)
    _office_ok = booking_office_notify_sms(tenant_val, sms_payload)

    return PublicBookingOut(
        id=booking_id,
        starts_at_iso=starts.isoformat(),
        name=payload.name,
        email_sent=email_sent,
        sms_sent=sms_sent,
        tenant=tenant_val,
    )



@router.get("/embed/lead.js")
def lead_widget_js(request: Request, redirect: str = "/thanks"):
    """
    Injects an iframe of /public/lead-form, passing tenant_key or api_key.
    """
    base = f"{request.url.scheme}://{request.headers.get('host')}"
    js = f"""
(function() {{
  var s = document.currentScript;
  var redirect = (s && s.dataset && s.dataset.redirect) ? s.dataset.redirect : "{redirect}";
  var tenantKey = (s && s.dataset && s.dataset.tenantKey) ? s.dataset.tenantKey : "";
  var apiKey  = (s && s.dataset && s.dataset.apiKey) ? s.dataset.apiKey : "";
  var iframe = document.createElement('iframe');
  var src = "{base}/public/lead-form?redirect=" + encodeURIComponent(redirect);
  if (tenantKey) {{
    src += "&tenant_key=" + encodeURIComponent(tenantKey);
  }} else if (apiKey) {{
    src += "&api_key=" + encodeURIComponent(apiKey);
  }}
  iframe.src = src;
  iframe.style.width = "100%";
  iframe.style.maxWidth = "420px";
  iframe.style.height = "560px";
  iframe.style.border = "0";
  iframe.setAttribute("title", "HVAC Lead Form");
  (s.parentElement || document.body).appendChild(iframe);
}})();
""".strip()
    return Response(
        content=js,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ---- PUBLIC: availability ----

class Slot(BaseModel):
    start_iso: str
    end_iso: str
    service: str


@router.get("/availability", response_model=List[Slot])
@router.get("/bookings/availability", response_model=List[Slot])  # alias path some UIs use
def public_availability(
    request: Request,
    tenant: Optional[str] = Query(None, description="tenant slug or key"),
    service: str = Query("default", description="service code, e.g., tuneup"),
    days: int = Query(7, ge=1, le=30, description="how many days ahead"),
    start_hour: int = Query(7, ge=0, le=23),   # DEFAULT 7am
    end_hour: int = Query(18, ge=1, le=24),    # DEFAULT 6pm
    duration_min: int = Query(60, ge=15, le=480),

    # some frontends pass these; keep optional and harmless
    date: Optional[str] = Query(None, description="YYYY-MM-DD start (optional)"),
    tz: Optional[str] = Query("America/New_York", description="IANA tz (optional)"),
):
    """
    Returns open slots for the next N days in working hours.
    Filters out any start times already booked for this tenant.
    Tenant is resolved from query ?tenant=... or x-tenant-id header, else 'default'.

    Times are generated in the given tz (default America/New_York),
    stored/returned as UTC (Z), so the frontend can display local correctly.
    """
    # ---- resolve tenant (query -> header -> default)
    tenant_val = (tenant or request.headers.get("x-tenant-id") or "default").strip()

    # ---- resolve timezone
    try:
        local_tz = ZoneInfo(tz or "America/New_York")
    except Exception:
        local_tz = ZoneInfo("America/New_York")

    # ---- time window
    now_local = datetime.now(timezone.utc)

    now_utc = now_local.astimezone(timezone.utc)

    # if a specific date is provided, start from that local day if it's in the future
    if date:
        try:
            y, m, d = map(int, date.split("-"))
            anchor_local = datetime(y, m, d, tzinfo=local_tz)
            if anchor_local > now_local:
                now_local = anchor_local
                now_utc = now_local.astimezone(timezone.utc)
        except Exception:
            pass

    window_start = now_utc.isoformat()
    window_end = (now_utc + timedelta(days=days + 1)).isoformat()

    # ---- load booked start-times for this tenant within the window
    booked_minutes: set[tuple[int, int, int, int, int]] = set()
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tenant_key TEXT NOT NULL,
                  name TEXT NOT NULL,
                  phone TEXT,
                  email TEXT,
                  address TEXT,
                  note TEXT,
                  service TEXT,
                  starts_at TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )
            rows = conn.exec_driver_sql(
                """
                SELECT starts_at
                FROM bookings
                WHERE tenant_key = ?
                  AND datetime(starts_at) >= datetime(?)
                  AND datetime(starts_at) <  datetime(?)
                """,
                (tenant_val, window_start, window_end),
            ).all()
        for (s,) in rows:
            try:
                dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
                dt_utc = dt.astimezone(timezone.utc)
                booked_minutes.add((dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour, dt_utc.minute))
            except Exception:
                continue
    except Exception:
        booked_minutes = set()

    # ---- build open slots in local time, convert to UTC, skip booked
    out: List[Slot] = []
    for d in range(days):
        day_local = (now_local + timedelta(days=d)).date()
        for h in range(start_hour, end_hour + 1):  # inclusive end_hour -> 6pm slot exists
            local_start = datetime(
                day_local.year, day_local.month, day_local.day, h, 0, tzinfo=local_tz
            )
            start_utc = local_start.astimezone(timezone.utc)
            end_utc = start_utc + timedelta(minutes=duration_min)

            if start_utc < now_utc:
                continue

            key = (start_utc.year, start_utc.month, start_utc.day, start_utc.hour, start_utc.minute)
            if key in booked_minutes:
                continue

            out.append(
                Slot(
                    start_iso=start_utc.isoformat().replace("+00:00", "Z"),
                    end_iso=end_utc.isoformat().replace("+00:00", "Z"),
                    service=service,
                )
            )

    return out


# LIST bookings for a tenant (array result)
@router.get("/bookings")
def public_list_bookings(
    tenant: str = Query(..., description="tenant slug or key"),
):
    """
    List bookings for a tenant.
    Adds a boolean 'completed' field based on booking_reviews.
    """
    try:
        with engine.begin() as conn:
            # Ensure core bookings table exists
            conn.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS bookings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tenant_key TEXT NOT NULL,
                  name TEXT NOT NULL,
                  phone TEXT,
                  email TEXT,
                  address TEXT,
                  note TEXT,
                  service TEXT,
                  starts_at TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
            """)

            # tiny table to track review / completion
            conn.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS booking_reviews (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  booking_id INTEGER NOT NULL,
                  tenant_key TEXT NOT NULL,
                  sent_at TEXT NOT NULL
                )
            """)

            rows = conn.exec_driver_sql(
                """
                SELECT
                  b.id,
                  b.tenant_key,
                  b.name,
                  b.phone,
                  b.note,
                  b.service,
                  b.starts_at,
                  b.created_at,
                  EXISTS (
                    SELECT 1
                    FROM booking_reviews r
                    WHERE r.booking_id = b.id
                      AND r.tenant_key = b.tenant_key
                  ) AS completed
                FROM bookings b
                WHERE b.tenant_key = ?
                ORDER BY datetime(b.starts_at) DESC
                """,
                (tenant,),
            ).mappings().all()

            return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB list error: {e}")

@router.post("/reminders/run")
def run_email_reminders():
    """
    Find bookings ~24h and ~2h from now (±5 minutes), send reminders (once), record sent.
    """
    now_utc = datetime.now(timezone.utc)
    tolerance_min = 5

    # windows to check
    targets = [
        ("24h", now_utc + timedelta(hours=24)),
        ("2h", now_utc + timedelta(hours=2)),
    ]

    sent_counts = {"24h": 0, "2h": 0}
    try:
        with engine.begin() as conn:
            # Ensure the log table exists
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS booking_reminders (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  booking_id INTEGER NOT NULL,
                  kind TEXT NOT NULL,          -- '24h' or '2h'
                  sent_at TEXT NOT NULL
                )
                """
            )

            for kind, target_dt in targets:
                # Find bookings near the target window that haven't been reminded for this kind
                rows = conn.exec_driver_sql(
                    """
                    SELECT b.id, b.tenant_key, b.name, b.email, b.phone, b.address, b.service, b.starts_at
                    FROM bookings b
                    WHERE ABS((julianday(b.starts_at) - julianday(?)) * 24.0 * 60.0) <= ?
                      AND NOT EXISTS (
                        SELECT 1 FROM booking_reminders r
                        WHERE r.booking_id = b.id AND r.kind = ?
                      )
                    """,
                    (target_dt.isoformat(), tolerance_min, kind),
                ).mappings().all()

                for r in rows:
                    payload = {
                        "name": r["name"],
                        "email": r["email"],
                        "phone": r["phone"],
                        "address": r["address"],
                        "service": r["service"],
                        "starts_at_iso": r["starts_at"],
                    }

                    # send email + SMS; count as "sent" if either succeeds
                    email_ok = send_booking_reminder(r["tenant_key"], payload, kind)
                    sms_ok = booking_reminder_sms(r["tenant_key"], payload, kind)

                    if email_ok or sms_ok:
                        conn.exec_driver_sql(
                            "INSERT INTO booking_reminders (booking_id, kind, sent_at) VALUES (?, ?, ?)",
                            (r["id"], kind, datetime.now(timezone.utc).isoformat()),
                        )
                        sent_counts[kind] += 1

        return {"ok": True, "sent": sent_counts, "now_utc": now_utc.isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reminders error: {e}")


# --- tiny debug endpoint to verify DB path + counts ---
@router.get("/debug/db")
def public_debug_db():
    try:
        with engine.begin() as conn:
            rows = conn.exec_driver_sql(
                """
                SELECT tenant_key, COUNT(*) AS n
                FROM bookings
                GROUP BY tenant_key
                ORDER BY tenant_key
                """
            ).mappings().all()
            counts = [dict(r) for r in rows]
            db_url = str(engine.url)
        return {"db": db_url, "counts": counts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB debug error: {e}")


@router.delete("/bookings/{booking_id}")
def public_delete_booking(
    booking_id: int,
    tenant: Optional[str] = Query(None, description="optional tenant filter"),
):
    """
    Delete a booking by id. If ?tenant= is provided, restrict deletion to that tenant.
    The portal currently calls DELETE /public/bookings/{id} without tenant, so we support both.
    """
    try:
        with engine.begin() as conn:
            # Ensure table exists (noop if already there)
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tenant_key TEXT NOT NULL,
                  name TEXT NOT NULL,
                  phone TEXT,
                  email TEXT,
                  address TEXT,
                  note TEXT,
                  service TEXT,
                  starts_at TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )

            if tenant:
                result = conn.exec_driver_sql(
                    "DELETE FROM bookings WHERE id = ? AND tenant_key = ?",
                    (booking_id, tenant),
                )
            else:
                result = conn.exec_driver_sql(
                    "DELETE FROM bookings WHERE id = ?",
                    (booking_id,),
                )
            deleted = result.rowcount or 0

        if deleted == 0:
            raise HTTPException(status_code=404, detail="Not Found")
        return {"ok": True, "deleted": deleted}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB delete error: {e}")


@router.post("/bookings/{booking_id}/complete")
def public_complete_booking(
    booking_id: int,
    tenant: Optional[str] = Query(None, description="optional tenant filter"),
):
    """
    Mark a booking as completed and send a review SMS to the customer.
    Also logs the send so you don't double-send later.
    """
    try:
        with engine.begin() as conn:
            # Make sure table exists
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tenant_key TEXT NOT NULL,
                  name TEXT NOT NULL,
                  phone TEXT,
                  email TEXT,
                  address TEXT,
                  note TEXT,
                  service TEXT,
                  starts_at TEXT NOT NULL,
                  created_at TEXT NOT NULL
                )
                """
            )

            row = conn.exec_driver_sql(
                """
                SELECT id, tenant_key, name, phone, service, starts_at
                FROM bookings
                WHERE id = ?
                """,
                (booking_id,),
            ).mappings().first()

            if not row:
                raise HTTPException(status_code=404, detail="Booking not found")

            tenant_val = (tenant or row["tenant_key"]).strip()

            # tiny log table so we don't double-send reviews later
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS booking_reviews (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  booking_id INTEGER NOT NULL,
                  tenant_key TEXT NOT NULL,
                  sent_at TEXT NOT NULL
                )
                """
            )

            # Check if we've already sent a review request for this booking
            already = conn.exec_driver_sql(
                """
                SELECT 1 FROM booking_reviews
                WHERE booking_id = ? AND tenant_key = ?
                LIMIT 1
                """,
                (row["id"], tenant_val),
            ).first()

            if not already:
                # 🔥 send review SMS immediately when Complete is clicked
                if row["phone"]:
                    brand = get_brand_for_tenant(tenant_val)
                    review_link = brand.get("review_link")

                    sms_payload = {
                        "name": row["name"],
                        "phone": row["phone"],
                        "service": row["service"],
                        "starts_at_iso": row["starts_at"],
                        "review_link": review_link,  # 👈 force tenant review URL through
                    }

                    booking_reminder_sms(tenant_val, sms_payload, "review")

                # log that we sent (or at least attempted)
                conn.exec_driver_sql(
                    """
                    INSERT INTO booking_reviews (booking_id, tenant_key, sent_at)
                    VALUES (?, ?, ?)
                    """,
                    (row["id"], tenant_val, datetime.now(timezone.utc).isoformat()),
                )

        return {"ok": True, "booking_id": booking_id, "tenant": tenant_val}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Complete error: {e}")
