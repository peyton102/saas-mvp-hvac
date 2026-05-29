# app/routers/admin_tenant_mgmt.py
from __future__ import annotations

import csv
import io
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy import delete

from app.db import get_session
from app.models import Tenant, Lead, Booking, Review, ReminderSent, TenantSettings, ApiKey
from app.models_finance import FinanceRevenue, FinanceCost
from app.routers.auth import get_current_user

router = APIRouter(prefix="/admin/mgmt", tags=["admin-mgmt"])


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
    tenants = session.exec(select(Tenant).order_by(Tenant.created_at.desc())).all()
    return [
        {
            "id": t.id,
            "slug": t.slug,
            "name": t.name or "",
            "business_name": t.business_name or "",
            "email": t.email or "",
            "is_active": t.is_active,
            "is_admin": t.is_admin,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "twilio_number": t.twilio_number or "",
        }
        for t in tenants
    ]


class VapiNumberIn(BaseModel):
    vapi_phone_number_id: Optional[str] = ""


@router.patch("/tenants/{slug}/vapi-number")
def assign_vapi_number(
    slug: str,
    body: VapiNumberIn,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_admin(current_user, session)
    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.twilio_number = (body.vapi_phone_number_id or "").strip()
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return {"ok": True, "slug": slug, "twilio_number": tenant.twilio_number}


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