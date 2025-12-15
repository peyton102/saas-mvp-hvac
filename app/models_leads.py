# app/models_leads.py
from __future__ import annotations
from typing import Optional
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import DateTime, text

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")),
        default_factory=utcnow,
    )

    tenant_id: str = Field(index=True)

    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    message: Optional[str] = None
    status: str = Field(default="new")  # new | contacted | won | lost
    source: str = Field(default="web")   # e.g., web/voice/sms
