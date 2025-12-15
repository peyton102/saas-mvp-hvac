# app/models.py
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import UniqueConstraint, String
from sqlmodel import SQLModel, Field, Relationship

# ---------- Core tables ----------


class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True
    )
    name: str
    phone: str
    email: Optional[str] = None
    message: Optional[str] = None
    tenant_id: str = Field(default="public", index=True)  # <-- keep "public"
    status: Optional[str] = Field(default="new", max_length=20)


class Booking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    name: str
    phone: str
    email: Optional[str] = None
    start: datetime
    end: datetime
    notes: Optional[str] = None
    source: Optional[str] = None  # e.g., "calendly", "direct"
    tenant_id: str = Field(default="public", index=True)  # <-- keep "public"
    completed_at: Optional[datetime] = Field(default=None, index=True)

class Review(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    phone: str
    name: Optional[str] = None
    job_id: Optional[str] = None
    notes: Optional[str] = None
    review_link: Optional[str] = None
    sms_sent: Optional[bool] = None
    tenant_id: str = Field(default="public", index=True)  # <-- keep "public"


class Tenant(SQLModel, table=True):
    __tablename__ = "tenant"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, default="")
    slug: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    is_active: bool = Field(default=True, index=True)

    # business meta
    business_name: Optional[str] = Field(default="", max_length=255)
    website: Optional[str] = Field(default="", max_length=255)
    address: Optional[str] = Field(default="", max_length=255)

    # Google reviews
    google_place_id: Optional[str] = Field(default="", max_length=128)
    review_google_url: Optional[str] = Field(default="", max_length=512)

    # NEW: contact / branding fields
    email: Optional[str] = Field(default="", max_length=255)          # office email
    phone: Optional[str] = Field(default="", max_length=50)           # office phone
    booking_link: Optional[str] = Field(default="", max_length=512)   # public booking URL
    office_sms_to: Optional[str] = Field(default="", max_length=50)   # internal SMS alerts
    office_email_to: Optional[str] = Field(default="", max_length=255)  # internal email alerts

    # --- QBO fields ---
    qbo_realm_id: Optional[str] = None
    qbo_access_token: Optional[str] = None
    qbo_refresh_token: Optional[str] = None
    qbo_token_expires_at: Optional[int] = None

    api_keys: List["ApiKey"] = Relationship(back_populates="tenant")


class TenantSettings(SQLModel, table=True):
    """
    Per-tenant settings: single source of truth for branding + review config.
    """
    __tablename__ = "tenant_settings"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Link back to Tenant by slug (your tenant identity everywhere)
    tenant_id: str = Field(foreign_key="tenant.slug", index=True)

    # 🔑 These are what reviews / SMS / branding should read from
    business_name: Optional[str] = Field(default="", max_length=255)
    business_phone: Optional[str] = Field(default="", max_length=50)
    review_link: Optional[str] = Field(default="", max_length=512)

    # Optional extras if you want to drive internal alerts from settings
    office_sms_to: Optional[str] = Field(default="", max_length=50)
    office_email_to: Optional[str] = Field(default="", max_length=255)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)



class ReminderSent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    phone: str
    name: Optional[str] = None
    booking_start: Optional[datetime] = None
    booking_end: Optional[datetime] = None
    message: Optional[str] = None  # SMS body
    template: Optional[str] = None  # e.g., "24h", "2h"
    source: Optional[str] = None  # e.g., "cron"
    sms_sent: Optional[bool] = None
    tenant_id: str = Field(default="public", index=True)  # <-- keep "public"


# ---------- Idempotency helper ----------


class WebhookDedup(SQLModel, table=True):
    __tablename__ = "webhook_dedup"
    __table_args__ = (UniqueConstraint("source", "event_id", name="uq_webhook_source_event"),)

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(index=True)
    event_id: str = Field(index=True)


class ApiKey(SQLModel, table=True):
    __tablename__ = "api_key"

    id: Optional[int] = Field(default=None, primary_key=True)
    # NEVER store raw tokens once we switch—this will hold a hash later
    hashed_key: str = Field(index=True, unique=True)
    label: str = Field(default="")  # e.g., “Front desk iPad”, “Zapier hook”
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    last_used_at: Optional[datetime] = Field(default=None, index=True)
    is_active: bool = Field(default=True, index=True)

    # tenant link
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    tenant: Optional[Tenant] = Relationship(back_populates="api_keys")
