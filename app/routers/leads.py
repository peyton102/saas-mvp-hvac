# app/routers/leads.py
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select
from sqlalchemy import text
from dateutil import parser as dtparse
from app.tenant import brand
from app import config, storage
from app.services.sms import send_sms
from app.schemas import LeadIn, LeadOut
from app.utils.phone import normalize_us_phone
from app.db import get_session
from app.models import Lead as LeadModel
from ..deps import get_tenant_id  # tenant resolver


router = APIRouter(prefix="", tags=["leads"])

@router.get("/whoami")
def whoami(tenant_id: str = Depends(get_tenant_id)):
    return {"tenant_id": tenant_id}

@router.post("/lead", response_model=LeadOut)
async def create_lead(
    request: Request,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    # --- Parse body (support JSON + form) ---
    ct = (request.headers.get("content-type") or "").lower()
    raw = {}
    if ct.startswith("application/json"):
        try:
            raw = await request.json()
        except Exception:
            raw = {}
    elif ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        try:
            form = await request.form()
            raw = dict(form)
        except Exception:
            raw = {}
    else:
        # last attempt: try JSON then form
        try:
            raw = await request.json()
        except Exception:
            try:
                form = await request.form()
                raw = dict(form)
            except Exception:
                raw = {}

    # --- Honeypot: hidden "website" field ---
    if str(raw.get("website", "")).strip():
        print("[HONEYPOT] Dropped lead (website field filled).")
        return LeadOut(sms_sent=False)

    # --- Validate via schema ---
    try:
        payload = LeadIn(**raw)  # <-- payload is defined here
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid lead payload: {e}")

    # Normalize phone
    e164 = normalize_us_phone(payload.phone)
    if not e164:
        raise HTTPException(status_code=400, detail="Invalid phone number.")

    # ---- Per-tenant branding (after payload exists) ----
    b = brand(tenant_id)  # {"FROM_NAME": "...", "BOOKING_LINK": "..."}

    # SMS body
    first = (payload.name or "").split(" ")[0] if payload.name else "there"
    body = (
        f"Hey {first}, thanks for contacting {b['FROM_NAME']}! "
        f"Grab the next available slot here: {b['BOOKING_LINK']}. "
        f"Prefer a call? Reply here."
    )

    # --- DB-based throttle (per-tenant) ---
    minutes = int(getattr(config.settings, "ANTI_SPAM_MINUTES", 30))
    recent = session.exec(
        select(LeadModel)
        .where((LeadModel.phone == e164) & (LeadModel.tenant_id == tenant_id))
        .order_by(LeadModel.created_at.desc())
        .limit(1)
    ).first()

    sms_ok = True
    if recent:
        now = datetime.utcnow()
        if (now - recent.created_at) < timedelta(minutes=minutes):
            print(f"[THROTTLE] Skipping SMS to {e164} (within {minutes}m) tenant={tenant_id}")
            sms_ok = False

    # Send SMS if not throttled (honors DRY_RUN)
    if sms_ok:
        sms_ok = send_sms(e164, body)

    # CSV log (only when DB_FIRST is false)
    if not getattr(config.settings, "DB_FIRST", True):
        storage.save_lead(
            {**payload.model_dump(), "phone": e164},
            sms_body=body,
            sms_sent=sms_ok,
            source="api",
        )

    # DB write (stamp tenant_id)
    session.add(
        LeadModel(
            name=(payload.name or "").strip(),
            phone=e164,
            email=(payload.email or "").strip() or None,
            message=(payload.message or "").strip() or None,
            tenant_id=tenant_id,
        )
    )
    session.commit()

    return LeadOut(sms_sent=bool(sms_ok))

@router.get("/debug/leads")
def debug_leads(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    source: str = Query("db", pattern="^(csv|db)$"),
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    source=db: read from SQLite Lead table, scoped to caller's tenant_id
    source=csv: read data/leads.csv (no tenant scope unless your CSV has that column)
    """
    if source == "db":
        rows = session.exec(
            select(LeadModel)
            .where(LeadModel.tenant_id == tenant_id)
            .order_by(LeadModel.id.desc())
            .limit(limit)
        ).all()
        items = [
            {
                "id": r.id,
                "created_at": (r.created_at.isoformat() if r.created_at else None),
                "name": r.name,
                "phone": r.phone,
                "email": r.email or "",
                "message": r.message or "",
                "tenant_id": r.tenant_id,
            }
            for r in rows
        ]
        return {"count": len(items), "items": items}

    # CSV (best-effort; no tenant filter unless your CSV includes tenant_id and storage filters it)
    items = storage.read_leads(limit)
    return {"count": len(items), "items": items}


@router.post("/debug/import-leads-csv-to-db")
def import_leads_csv_to_db(limit: int = 10000, session: Session = Depends(get_session)):
    """
    One-time helper: read leads.csv and insert any missing rows into the Lead table.
    Dedupe by (phone, created_at, COALESCE(message,'')) to avoid duplicates.
    """
    items = storage.read_leads(limit)
    inserted = 0
    skipped = 0

    for it in items:
        phone = (it.get("phone") or "").strip()
        created_raw = it.get("created_at") or ""
        msg = (it.get("message") or "").strip()

        # parse timestamp
        try:
            created_dt = dtparse.isoparse(created_raw.replace("Z", "+00:00"))
        except Exception:
            skipped += 1
            continue

        # already in DB?
        exists = session.exec(
            select(LeadModel).where(
                (LeadModel.phone == phone) &
                (LeadModel.created_at == created_dt) &
                (LeadModel.message == (msg or None))
            ).limit(1)
        ).first()
        if exists:
            skipped += 1
            continue

        row = LeadModel(
            created_at=created_dt,
            name=(it.get("name") or "").strip(),
            phone=phone,
            email=(it.get("email") or "").strip() or None,
            message=msg or None,
        )
        session.add(row)
        inserted += 1

    session.commit()
    return {"ok": True, "inserted": inserted, "skipped": skipped, "total_csv": len(items)}


@router.post("/debug/dedupe-leads-db")
def dedupe_leads_db(session: Session = Depends(get_session)):
    """
    One-time cleanup: keep the earliest row per (phone, created_at, COALESCE(message,'')).
    """
    sql = text("""
        DELETE FROM lead
        WHERE id NOT IN (
          SELECT MIN(id)
          FROM lead
          GROUP BY phone, created_at, COALESCE(message, '')
        )
    """)
    session.exec(sql)
    session.commit()
    return {"ok": True}
@router.get("/debug/whoami-verbose", tags=["debug"])
def whoami_verbose(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
):
    auth = request.headers.get("authorization") or ""
    x_api = request.headers.get("x-api-key") or request.headers.get("X-API-Key") or ""
    return {
        "tenant_id": tenant_id,
        "headers_seen": {
            "authorization_startswith": auth[:16] + "..." if auth else "",
            "x_api_key_present": bool(x_api),
        },
        "state": {
            "request.state.tenant_id": getattr(request.state, "tenant_id", None),
        },
    }
