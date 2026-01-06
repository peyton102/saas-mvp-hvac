# app/models_finance.py
from __future__ import annotations

from typing import Optional
from decimal import Decimal
from datetime import datetime, timezone

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import DateTime, text


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FinanceRevenue(SQLModel, table=True):
    """Revenue line item (tenant-scoped)."""
    id: Optional[int] = Field(default=None, primary_key=True)

    # timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
        default_factory=utcnow,
    )

    # multitenancy
    tenant_id: str = Field(index=True)

    # core amounts/metadata
    amount: Decimal = Field(default=Decimal("0"))
    source: str = Field(default="unknown")
    booking_id: Optional[int] = None
    lead_id: Optional[int] = None
    notes: Optional[str] = None

    part_code: Optional[str] = Field(default=None, index=True)
    job_type: Optional[str] = Field(default=None, index=True)


class FinanceCost(SQLModel, table=True):
    """Cost line item (tenant-scoped)."""
    id: Optional[int] = Field(default=None, primary_key=True)

    # timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
        default_factory=utcnow,
    )

    # multitenancy
    tenant_id: str = Field(index=True)

    # core amounts/metadata
    amount: Decimal = Field(default=Decimal("0"))
    category: str = Field(default="general")
    vendor: Optional[str] = None
    notes: Optional[str] = None

    # labor tracking (numeric, default 0 so we can sum safely)
    hours: Decimal = Field(default=Decimal("0"))
    hourly_rate: Decimal = Field(default=Decimal("0"))

    part_code: Optional[str] = Field(default=None, index=True)
    job_type: Optional[str] = Field(default=None, index=True)


# Optional aliases (in case other modules import these names)
Revenue = FinanceRevenue
Cost = FinanceCost
