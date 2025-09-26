from typing import Optional
from decimal import Decimal
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Column, DateTime, text

def utcnow():
    return datetime.now(tz=timezone.utc)

class Revenue(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
        default_factory=utcnow,
    )
    tenant_id: str
    amount: Decimal = Field(default=Decimal("0"))
    source: str = Field(default="unknown")
    booking_id: Optional[int] = None
    lead_id: Optional[int] = None
    notes: Optional[str] = None

class Cost(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
        default_factory=utcnow,
    )
    tenant_id: str
    amount: Decimal = Field(default=Decimal("0"))
    category: str = Field(default="general")
    vendor: Optional[str] = None
    notes: Optional[str] = None
