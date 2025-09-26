# app/models.py
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint
from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

# ---------- Core tables ----------

class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    name: str
    phone: str
    email: Optional[str] = None
    message: Optional[str] = None
    tenant_id: str = Field(default="public", index=True)  # <-- keep "public"


class Booking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    name: str
    phone: str
    email: Optional[str] = None
    start: datetime
    end: datetime
    notes: Optional[str] = None
    source: Optional[str] = None  # e.g., "calendly", "direct"
    tenant_id: str = Field(default="public", index=True)  # <-- keep "public"


class Review(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    phone: str
    name: Optional[str] = None
    job_id: Optional[str] = None
    notes: Optional[str] = None
    review_link: Optional[str] = None
    sms_sent: Optional[bool] = None
    tenant_id: str = Field(default="public", index=True)  # <-- keep "public"


class ReminderSent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    phone: str
    name: Optional[str] = None
    booking_start: Optional[datetime] = None
    booking_end: Optional[datetime] = None
    message: Optional[str] = None     # SMS body
    template: Optional[str] = None    # e.g., "24h", "2h"
    source: Optional[str] = None      # e.g., "cron"
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
class Tenant(SQLModel, table=True):
    __tablename__ = "tenant"

    id: Optional[int] = Field(default=None, primary_key=True)
    # Human-friendly name to show in UIs
    name: str = Field(index=True, default="")

    # Stable slug you’ll reference in code (e.g., "default", "acme")
    slug: str = Field(index=True, unique=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    is_active: bool = Field(default=True, index=True)

    # backrefs (not required, but handy later)
    api_keys: List["ApiKey"] = Relationship(back_populates="tenant")


class ApiKey(SQLModel, table=True):
    __tablename__ = "api_key"

    id: Optional[int] = Field(default=None, primary_key=True)
    # NEVER store raw tokens once we switch—this will hold a hash later
    hashed_key: str = Field(index=True, unique=True)
    label: str = Field(default="")  # e.g., “Front desk iPad”, “Zapier hook”
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_used_at: Optional[datetime] = Field(default=None, index=True)
    is_active: bool = Field(default=True, index=True)

    # tenant link
    tenant_id: int = Field(foreign_key="tenant.id", index=True)
    tenant: Optional[Tenant] = Relationship(back_populates="api_keys")