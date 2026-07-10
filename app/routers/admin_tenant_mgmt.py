# app/routers/admin_tenant_mgmt.py
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy import delete, text

from fastapi import BackgroundTasks

from app.db import get_session
from app.models import Tenant, Lead, Booking, Review, ReminderSent, TenantSettings, ApiKey
from app.models_finance import FinanceRevenue, FinanceCost
from app.routers.auth import get_current_user
from app.services.sms import tenant_ready_sms, new_signup_alert_sms

router = APIRouter(prefix="/admin/mgmt", tags=["admin-mgmt"])

ALL_FEATURES = ["vapi", "bookings", "leads", "finance", "reviews", "reminders"]


class UpdateFeaturesRequest(BaseModel):
    features: List[str]


class AssignVapiNumberRequest(BaseModel):
    vapi_phone_number_id: str  # Vapi phoneNumberId, e.g. "phn_xxxx" — empty string to clear


def _require_admin(current_user: Dict[str, Any], session: Session) -> None:
    slug = current_user.get("tenant_slug") or current_user.get("tenant")
    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant or not tenant.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/tenants")
def list_tenants(
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user, session)

    # ensure features column exists
    try:
        session.exec(text("SAVEPOINT sp_mgmt_features"))
        session.exec(text("ALTER TABLE tenant ADD COLUMN features TEXT"))
        session.exec(text("RELEASE SAVEPOINT sp_mgmt_features"))
    except Exception:
        session.exec(text("ROLLBACK TO SAVEPOINT sp_mgmt_features"))

    rows = session.exec(
        text("SELECT id, slug, name, business_name, email, phone, is_active, is_admin, created_at, features, twilio_number, assistant_status, carrier, carrier_setup_complete FROM tenant ORDER BY created_at DESC")
    ).all()

    result = []
    for r in rows:
        features_raw = (r.features if hasattr(r, "features") else None) or ""
        features_list = [f for f in features_raw.split(",") if f] if features_raw else []
        result.append({
            "id": r.id,
            "slug": r.slug,
            "name": r.name or "",
            "business_name": r.business_name or "",
            "email": r.email or "",
            "phone": r.phone or "",
            "is_active": r.is_active,
            "is_admin": r.is_admin,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "features": features_list,
            "vapi_phone_number_id": (r.twilio_number if hasattr(r, "twilio_number") else None) or "",
            "assistant_status": (r.assistant_status if hasattr(r, "assistant_status") else None) or "active",
            "carrier": (r.carrier if hasattr(r, "carrier") else None) or "",
            "carrier_setup_complete": bool(r.carrier_setup_complete if hasattr(r, "carrier_setup_complete") else False),
        })
    return result


@router.patch("/tenants/{slug}/features")
def update_tenant_features(
    slug: str,
    payload: UpdateFeaturesRequest,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user, session)

    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    valid = [f for f in payload.features if f in ALL_FEATURES]
    features_str = ",".join(valid) if valid else None

    session.exec(
        text("UPDATE tenant SET features = :features WHERE slug = :slug")
        .bindparams(features=features_str, slug=slug)
    )
    session.commit()

    return {"ok": True, "slug": slug, "features": valid}


@router.patch("/tenants/{slug}/vapi-number")
def assign_vapi_number(
    slug: str,
    payload: AssignVapiNumberRequest,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Assign (or clear) a Vapi Phone Number ID for a tenant."""
    _require_admin(current_user, session)

    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    new_value = payload.vapi_phone_number_id.strip()

    # Prevent two tenants sharing the same number
    if new_value:
        conflict = session.exec(
            select(Tenant).where(
                Tenant.twilio_number == new_value,
                Tenant.slug != slug,
            )
        ).first()
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"Phone number ID already assigned to tenant '{conflict.slug}'",
            )

    tenant.twilio_number = new_value or None
    session.add(tenant)
    session.commit()

    return {"ok": True, "slug": slug, "vapi_phone_number_id": new_value}


@router.post("/tenants/{slug}/mark-ready")
def mark_assistant_ready(
    slug: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Set assistant_status = 'ready' and SMS the customer."""
    _require_admin(current_user, session)

    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if getattr(tenant, "assistant_status", None) == "active":
        raise HTTPException(status_code=400, detail="Tenant is already active")

    session.exec(
        text("UPDATE tenant SET assistant_status = 'ready' WHERE slug = :slug").bindparams(slug=slug)
    )
    session.commit()

    phone = (tenant.phone or "").strip()
    if phone:
        background_tasks.add_task(tenant_ready_sms, phone)
    else:
        print(f"[MARK READY] No phone for tenant {slug!r}; skipping customer SMS", flush=True)

    return {"ok": True, "slug": slug, "assistant_status": "ready", "sms_sent": bool(phone)}


@router.get("/tenants/{slug}/export")
def export_tenant_data(
    slug: str,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user, session)

    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    output = io.StringIO()
    writer = csv.writer(output)

    # --- Leads ---
    writer.writerow(["section", "id", "created_at", "name", "phone", "email", "message", "status", "source"])
    leads = session.exec(select(Lead).where(Lead.tenant_id == slug)).all()
    for r in leads:
        writer.writerow(["lead", r.id, r.created_at, r.name, r.phone, r.email or "", r.message or "", r.status or "", r.source or ""])

    # --- Bookings ---
    writer.writerow([])
    writer.writerow(["section", "id", "created_at", "name", "phone", "email", "start", "end", "notes", "source"])
    bookings = session.exec(select(Booking).where(Booking.tenant_id == slug)).all()
    for r in bookings:
        writer.writerow(["booking", r.id, r.created_at, r.name, r.phone, r.email or "", r.start, r.end, r.notes or "", r.source or ""])

    # --- Finance Revenue ---
    writer.writerow([])
    writer.writerow(["section", "id", "created_at", "amount", "source", "notes", "part_code", "job_type"])
    revenues = session.exec(select(FinanceRevenue).where(FinanceRevenue.tenant_id == slug)).all()
    for r in revenues:
        writer.writerow(["revenue", r.id, r.created_at, r.amount, r.source, r.notes or "", r.part_code or "", r.job_type or ""])

    # --- Finance Costs ---
    writer.writerow([])
    writer.writerow(["section", "id", "created_at", "amount", "category", "vendor", "notes", "hours", "hourly_rate", "part_code", "job_type"])
    costs = session.exec(select(FinanceCost).where(FinanceCost.tenant_id == slug)).all()
    for r in costs:
        writer.writerow(["cost", r.id, r.created_at, r.amount, r.category, r.vendor or "", r.notes or "", r.hours, r.hourly_rate, r.part_code or "", r.job_type or ""])

    csv_bytes = output.getvalue().encode("utf-8")
    filename = f"tenant_{slug}_export.csv"
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tenants/{slug}/leads")
def list_tenant_leads(
    slug: str,
    limit: int = 500,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Return full lead objects for a tenant. Admin-only."""
    _require_admin(current_user, session)

    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    leads = session.exec(
        select(Lead).where(Lead.tenant_id == slug).order_by(Lead.created_at.desc()).limit(limit)
    ).all()

    from app.routers.leads import _is_good_lead

    items = []
    for r in leads:
        items.append({
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "name": r.name or "",
            "phone": r.phone or "",
            "email": r.email or "",
            "message": r.message or "",
            "status": r.status or "",
            "source": r.source or "",
            "service_address": getattr(r, "service_address", None) or "",
            "service_urgency": getattr(r, "service_urgency", None) or "",
            "zip": getattr(r, "zip", None) or "",
            "notes": getattr(r, "notes", None) or "",
            "job_won": getattr(r, "job_won", None) or False,
            "job_value": getattr(r, "job_value", None),
            "needs_verification": getattr(r, "needs_verification", None) or False,
            "customer_type": getattr(r, "customer_type", None) or "",
            "property_type": getattr(r, "property_type", None) or "",
            "is_good_lead": _is_good_lead(r),
        })

    return {"items": items, "total": len(items)}


@router.get("/signups")
def list_signups(
    limit: int = 50,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Return recent signup events for the admin dashboard notification feed."""
    _require_admin(current_user, session)

    rows = session.exec(text("""
        SELECT
            ae.created_at,
            ae.user_email,
            ae.tenant_id AS slug,
            t.business_name,
            t.phone,
            ae.action
        FROM audit_event ae
        LEFT JOIN tenant t ON t.slug = ae.tenant_id
        WHERE ae.category = 'auth'
          AND ae.action IN ('signup_success', 'register_success')
        ORDER BY ae.created_at DESC
        LIMIT :limit
    """).bindparams(limit=limit)).all()

    result = []
    for r in rows:
        created_at = r.created_at
        if created_at and hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        result.append({
            "created_at": created_at,
            "email": r.user_email or "",
            "slug": r.slug or "",
            "business_name": r.business_name or "",
            "phone": r.phone or "",
            "via": "invite" if r.action == "signup_success" else "self-serve",
        })
    return result


@router.delete("/tenants/{slug}")
def delete_tenant(
    slug: str,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user, session)

    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    caller_slug = current_user.get("tenant_slug") or current_user.get("tenant")
    if slug == caller_slug:
        raise HTTPException(status_code=400, detail="Cannot delete your own tenant")

    print(f"[TENANT DELETE] tenant_id={tenant.id} slug={slug!r} name={tenant.name!r}")

    # Hard delete all records scoped strictly to this tenant's slug
    session.exec(delete(Lead).where(Lead.tenant_id == slug))
    session.exec(delete(Booking).where(Booking.tenant_id == slug))
    session.exec(delete(Review).where(Review.tenant_id == slug))
    session.exec(delete(ReminderSent).where(ReminderSent.tenant_id == slug))
    session.exec(delete(FinanceRevenue).where(FinanceRevenue.tenant_id == slug))
    session.exec(delete(FinanceCost).where(FinanceCost.tenant_id == slug))
    session.exec(delete(TenantSettings).where(TenantSettings.tenant_id == slug))
    # ApiKey uses integer tenant_id FK
    session.exec(delete(ApiKey).where(ApiKey.tenant_id == tenant.id))
    session.delete(tenant)
    session.commit()

    return {"ok": True, "deleted_slug": slug}