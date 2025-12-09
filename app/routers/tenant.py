# app/routers/tenant.py
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app import config
from app.db import get_session
from app.deps import get_tenant_id
from app.models import Tenant
from app.services.review_link_resolver import resolve_and_save_google_review_link

router = APIRouter(prefix="/tenant", tags=["tenant"])

# ---------------- config helpers ----------------


def _tenant_overrides() -> Dict[str, Dict[str, Any]]:
    """
    Per-tenant overrides from config (or config.settings).
    Shape:
    {
      "default": {
        "FROM_NAME": "Your Brand",
        "BOOKING_LINK": "https://...",
        "REVIEW_GOOGLE_URL": "https://example.com/review"
      },
      "acme": { ... }
    }
    """
    brands = getattr(config, "TENANT_BRANDS", None)
    if brands is None and hasattr(config, "settings"):
        brands = getattr(config.settings, "TENANT_BRANDS", None)
    return brands or {}


def review_link(tenant_id: str, db: "Optional[object]" = None) -> Optional[str]:
    """
    Resolve the tenant's review link with priority:
      1) TENANT_BRANDS[tenant_id].REVIEW_GOOGLE_URL
      2) Global config REVIEW_GOOGLE_URL
      3) DB lookup: Tenant.review_google_url (if a db session is provided)
    Returns a URL string or None.
    """
    overrides = _tenant_overrides().get(tenant_id, {})
    link = (overrides.get("REVIEW_GOOGLE_URL") or "").strip()
    if link:
        return link

    link = (
        getattr(config, "REVIEW_GOOGLE_URL", None)
        or getattr(getattr(config, "settings", object()), "REVIEW_GOOGLE_URL", None)
    )
    if isinstance(link, str) and link.strip():
        return link.strip()

    if db is not None:
        try:
            t = db.exec(select(Tenant).where(Tenant.slug == tenant_id)).first()
            if t and isinstance(getattr(t, "review_google_url", None), str):
                db_link = t.review_google_url.strip()
                if db_link:
                    return db_link
        except Exception:
        #    logging could go here
            pass

    return None


def brand(tenant_id: str, db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Return branding with keys:
      - FROM_NAME
      - BOOKING_LINK
      - REVIEW_GOOGLE_URL
      - OFFICE_SMS_TO
      - OFFICE_EMAIL_TO
    """
    overrides = _tenant_overrides().get(tenant_id, {})

    FROM_NAME = (
        overrides.get("FROM_NAME")
        or getattr(config, "FROM_NAME", None)
        or getattr(getattr(config, "settings", object()), "FROM_NAME", "Your HVAC")
    )

    BOOKING_LINK = (
        overrides.get("BOOKING_LINK")
        or getattr(config, "BOOKING_LINK", None)
        or getattr(
            getattr(config, "settings", object()),
            "BOOKING_LINK",
            "https://calendly.com/yourhvac/estimate",
        )
    )

    override_or_global_review = (
        overrides.get("REVIEW_GOOGLE_URL")
        or getattr(config, "REVIEW_GOOGLE_URL", None)
        or getattr(getattr(config, "settings", object()), "REVIEW_GOOGLE_URL", None)
    )
    if isinstance(override_or_global_review, str) and override_or_global_review.strip():
        review_url = override_or_global_review.strip()
    else:
        review_url = review_link(tenant_id, db=db)

    office_sms = (
        overrides.get("OFFICE_SMS_TO")
        or getattr(config, "OFFICE_SMS_TO", None)
        or getattr(getattr(config, "settings", object()), "OFFICE_SMS_TO", None)
    )

    office_email = (
        overrides.get("OFFICE_EMAIL_TO")
        or getattr(config, "OFFICE_EMAIL_TO", None)
        or getattr(getattr(config, "settings", object()), "OFFICE_EMAIL_TO", None)
    )

    if db is not None:
        try:
            t = db.exec(select(Tenant).where(Tenant.slug == tenant_id)).first()
        except Exception:
            t = None

        if t is not None:
            if getattr(t, "business_name", None):
                FROM_NAME = t.business_name
            elif getattr(t, "name", None):
                FROM_NAME = t.name

            if getattr(t, "booking_link", None):
                if t.booking_link.strip():
                    BOOKING_LINK = t.booking_link.strip()

            if getattr(t, "office_sms_to", None):
                if t.office_sms_to.strip():
                    office_sms = t.office_sms_to.strip()

            if getattr(t, "office_email_to", None):
                if t.office_email_to.strip():
                    office_email = t.office_email_to.strip()

    return {
        "FROM_NAME": FROM_NAME,
        "BOOKING_LINK": BOOKING_LINK,
        "REVIEW_GOOGLE_URL": review_url,
        "OFFICE_SMS_TO": office_sms,
        "OFFICE_EMAIL_TO": office_email,
    }


# ---------------- settings models ----------------


class PlaceIdIn(BaseModel):
    tenant_slug: str
    google_place_id: str


class ReviewUrlIn(BaseModel):
    tenant_slug: str
    review_google_url: str


class TenantSettingsIn(BaseModel):
    business_name: Optional[str] = None
    booking_link: Optional[str] = None
    office_sms_to: Optional[str] = None
    office_email_to: Optional[str] = None
    review_google_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class ProfileIn(BaseModel):
    tenant_slug: str
    business_name: str | None = ""
    website: str | None = ""
    address: str | None = ""


class AutoResolveIn(BaseModel):
    tenant_slug: str


# ---------------- routes ----------------


@router.post("/settings/reviews/placeid")
def set_place_id(body: PlaceIdIn, db: Session = Depends(get_session)):
    t = db.exec(select(Tenant).where(Tenant.slug == body.tenant_slug)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")

    t.google_place_id = body.google_place_id.strip()
    t.review_google_url = (
        f"https://search.google.com/local/writereview?placeid={t.google_place_id}"
    )
    db.add(t)
    db.commit()
    db.refresh(t)

    return {
        "ok": True,
        "tenant": t.slug,
        "google_place_id": t.google_place_id,
        "review_google_url": t.review_google_url,
    }


@router.post("/settings/reviews/url")
def set_review_url(body: ReviewUrlIn, db: Session = Depends(get_session)):
    t = db.exec(select(Tenant).where(Tenant.slug == body.tenant_slug)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")

    t.review_google_url = body.review_google_url.strip()
    db.add(t)
    db.commit()
    db.refresh(t)

    return {
        "ok": True,
        "tenant": t.slug,
        "review_google_url": t.review_google_url,
    }


@router.post("/settings/profile")
def set_profile(data: ProfileIn, db: Session = Depends(get_session)):
    t = db.exec(select(Tenant).where(Tenant.slug == data.tenant_slug)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    t.business_name = (data.business_name or "").strip()
    t.website = (data.website or "").strip()
    t.address = (data.address or "").strip()
    db.add(t)
    db.commit()
    db.refresh(t)
    return {
        "ok": True,
        "tenant": t.slug,
        "business_name": t.business_name,
        "website": t.website,
        "address": t.address,
    }


@router.post("/settings/reviews/auto")
def auto_resolve_review_link(body: AutoResolveIn, db: Session = Depends(get_session)):
    res = resolve_and_save_google_review_link(db, body.tenant_slug)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "resolve_failed"))
    return res


@router.post("/settings")
def update_tenant_settings(
    body: TenantSettingsIn,
    tenant_id: str = Depends(get_tenant_id),
    db: Session = Depends(get_session),
):
    t = db.exec(select(Tenant).where(Tenant.slug == tenant_id)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")

    data = body.dict(exclude_none=True)

    for key, value in list(data.items()):
        if isinstance(value, str):
            data[key] = value.strip()

    for key, value in data.items():
        setattr(t, key, value)

    db.add(t)
    db.commit()
    db.refresh(t)

    return {"ok": True, "tenant": t.slug, "updated": data}


@router.get("/settings")
def get_tenant_settings(
    tenant_id: str = Depends(get_tenant_id),
    db: Session = Depends(get_session),
):
    t = db.exec(select(Tenant).where(Tenant.slug == tenant_id)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return {
        "slug": t.slug,
        "business_name": t.business_name,
        "booking_link": t.booking_link,
        "office_sms_to": t.office_sms_to,
        "office_email_to": t.office_email_to,
        "review_google_url": t.review_google_url,
        "email": t.email,
        "phone": t.phone,
        "website": t.website,
        "address": t.address,
    }


@router.get("/settings/debug-brand")
def debug_tenant_brand(
    tenant_id: str = Depends(get_tenant_id),
    db: Session = Depends(get_session),
):
    return brand(tenant_id, db=db)
