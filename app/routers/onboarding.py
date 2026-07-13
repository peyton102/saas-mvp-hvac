# app/routers/onboarding.py
"""
Authenticated onboarding endpoints — called by the carrier setup wizard.
All routes require a valid JWT (Authorization: Bearer <token>).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from sqlalchemy import text

from app.db import get_session
from app.models import Tenant
from app.routers.auth import get_current_user
from app.services.sms import send_sms

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _admin_dest() -> Optional[str]:
    return os.getenv("ALERT_SMS_TO", "").strip() or None


class SaveCarrierRequest(BaseModel):
    carrier: str  # e.g. "verizon", "att", "tmobile", "metro", "spectrum", "cricket", "boost", "other"


@router.patch("/carrier")
def save_carrier(
    payload: SaveCarrierRequest,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Persist the carrier choice the customer picked in Step 1."""
    slug = current_user["tenant_slug"]
    carrier = payload.carrier.strip().lower()
    session.exec(
        text("UPDATE tenant SET carrier = :carrier WHERE slug = :slug")
        .bindparams(carrier=carrier, slug=slug)
    )
    session.commit()
    return {"ok": True, "carrier": carrier}


@router.post("/complete")
def complete_setup(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Customer clicked 'Yes, it worked.' — set status = active and alert admin.
    """
    slug = current_user["tenant_slug"]
    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    session.exec(
        text("""
            UPDATE tenant
            SET assistant_status = 'active', carrier_setup_complete = TRUE
            WHERE slug = :slug
        """).bindparams(slug=slug)
    )
    session.commit()

    def _alert():
        dest = _admin_dest()
        if not dest:
            return
        business = (tenant.business_name or slug).strip()
        carrier = (getattr(tenant, "carrier", None) or "unknown").strip()
        ts = datetime.now(timezone.utc).strftime("%m/%d %H:%M UTC")
        send_sms(dest, (
            f"Customer is LIVE!\n"
            f"Business: {business}\n"
            f"Carrier: {carrier}\n"
            f"Time: {ts}"
        ))

    background_tasks.add_task(_alert)
    return {"ok": True, "assistant_status": "active"}


@router.post("/help")
def request_help(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Customer clicked 'Get help' — alert admin with name, carrier, situation.
    """
    slug = current_user["tenant_slug"]
    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    def _alert():
        dest = _admin_dest()
        if not dest:
            return
        business = (tenant.business_name or slug).strip()
        carrier = (getattr(tenant, "carrier", None) or "unknown").strip()
        email = (tenant.email or "").strip()
        send_sms(dest, (
            f"Customer stuck at call forwarding!\n"
            f"Business: {business}\n"
            f"Carrier: {carrier}\n"
            f"Email: {email}"
        ))

    background_tasks.add_task(_alert)
    return {"ok": True}
