# app/routers/leads.py
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select
from sqlalchemy import text
from fastapi import status
from dateutil import parser as dtparse
from app.tenantold import brand
from app import config, storage
from app.services.sms import send_sms  # still ok to keep imported (used nowhere now)
from app.schemas import LeadIn, LeadOut
from app.utils.phone import normalize_us_phone
from app.db import get_session
from app.models import Lead as LeadModel
from ..deps import get_tenant_id  # tenant resolver
from app.services.sms import lead_auto_reply_sms, lead_office_notify_sms  # already imported

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
        payload = LeadIn(**raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid lead payload: {e}")

    # Normalize phone
    e164 = normalize_us_phone(payload.phone)
    if not e164:
        raise HTTPException(status_code=400, detail="Invalid phone number.")

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

    # Build payload once for both SMS helpers
    sms_payload = {
        "name": payload.name,
        "phone": e164,
        "email": payload.email,
        "message": payload.message or "",
    }

    # Customer auto-reply (only if not throttled)
    if sms_ok:
        sms_ok = lead_auto_reply_sms(tenant_id, sms_payload)

    # Office notification (no throttle – internal)
    _office_ok = lead_office_notify_sms(tenant_id, sms_payload)

    # CSV log (only when DB_FIRST is false)
    if not getattr(config.settings, "DB_FIRST", True):
        sms_body_for_log = (
            f"Lead auto-reply sent to {e164} (tenant={tenant_id})"
            if sms_ok
            else "SMS not sent (throttled or error)"
        )
        storage.save_lead(
            {**payload.model_dump(), "phone": e164},
            sms_body=sms_body_for_log,
            sms_sent=sms_ok,
            source="api",
        )

    # DB write (stamp tenant_id + status, and source if the column exists)
    session.add(
        LeadModel(
            name=(payload.name or "").strip(),
            phone=e164,
            email=(payload.email or "").strip() or None,
            message=(payload.message or "").strip() or None,
            tenant_id=tenant_id,
            status="new",
            **({"source": "web_form"} if hasattr(LeadModel, "source") else {}),
        )
    )
    session.commit()

    return LeadOut(sms_sent=bool(sms_ok))

@router.delete("/debug/leads/{lead_id}")
def delete_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    row = session.get(LeadModel, lead_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Not found")
    session.delete(row)
    session.commit()
    return {"ok": True, "deleted": lead_id}


@router.patch("/leads/{lead_id}/status")
def update_lead_status(
    lead_id: int,
    payload: dict,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    new_status = (payload.get("status") or "").lower()
    allowed = {"new", "contacted", "won", "lost"}
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed)}")

    row = session.get(LeadModel, lead_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Not found")

    row.status = new_status
    session.add(row)
    session.commit()
    return {"ok": True, "id": lead_id, "status": new_status}


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
                "status": (getattr(r, "status", None) or "new"),
                "tenant_id": r.tenant_id,
            }
            for r in rows
        ]
        return {"count": len(items), "items": items}

    # CSV (best-effort; no tenant filter unless your CSV includes tenant_id and storage filters it)
    items = storage.read_leads(limit)
    return {"count": len(items), "items": items}


@router.post("/debug/import-leads-csv-to-db")
def import_leads_csv_to_db(
    limit: int = 10000,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    One-time helper: read leads.csv and insert any missing rows into the Lead table
    *for this tenant*.

    Dedupe by (phone, created_at, COALESCE(message,'')) within this tenant.
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

        # already in DB for THIS tenant?
        exists = session.exec(
            select(LeadModel).where(
                (LeadModel.phone == phone)
                & (LeadModel.created_at == created_dt)
                & (LeadModel.message == (msg or None))
                & (LeadModel.tenant_id == tenant_id)   # 👈 tenant-scoped
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
            tenant_id=tenant_id,   # 👈 stamp tenant
        )
        session.add(row)
        inserted += 1

    session.commit()
    return {"ok": True, "tenant_id": tenant_id, "inserted": inserted, "skipped": skipped, "total_csv": len(items)}

@router.post("/debug/dedupe-leads-db")
def dedupe_leads_db(
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    One-time cleanup: for THIS tenant, keep the earliest row per
    (phone, created_at, COALESCE(message,'')) and delete the rest.
    Done in Python to avoid SQLite quirks.
    """
    # Pull all leads for this tenant ordered by created_at then id
    rows = session.exec(
        select(LeadModel)
        .where(LeadModel.tenant_id == tenant_id)
        .order_by(LeadModel.phone, LeadModel.created_at, LeadModel.id)
    ).all()

    seen = set()
    to_delete = []

    for lead in rows:
        key = (
            lead.phone or "",
            lead.created_at.isoformat() if lead.created_at else "",
            lead.message or "",
        )
        if key in seen:
            to_delete.append(lead.id)
        else:
            seen.add(key)

    if not to_delete:
        return {"ok": True, "tenant_id": tenant_id, "deleted": 0}

    # Delete duplicates for this tenant
    session.exec(
        text(
            "DELETE FROM lead WHERE tenant_id = :tenant_id AND id IN :ids"
        ).bindparams(tenant_id=tenant_id, ids=tuple(to_delete))
    )
    session.commit()

    return {"ok": True, "tenant_id": tenant_id, "deleted": len(to_delete)}


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
@router.get("/leads")
def list_leads(
    limit: int = Query(200, ge=1, le=500),
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Portal-facing list of leads for the current tenant.
    """
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
            "status": (getattr(r, "status", None) or "new"),
            "tenant_id": r.tenant_id,
        }
        for r in rows
    ]
    return {"count": len(items), "items": items}
@router.delete("/leads/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead_public(
    lead_id: int,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    Portal-facing delete. Same logic as /debug/leads/{lead_id}, but without /debug.
    """
    row = session.get(LeadModel, lead_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Not found")

    session.delete(row)
    session.commit()
    return