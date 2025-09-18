# app/models.py
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    name: str
    phone: str
    email: Optional[str] = None
    message: Optional[str] = None


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


class Review(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    phone: str
    name: Optional[str] = None
    job_id: Optional[str] = None
    notes: Optional[str] = None
    review_link: Optional[str] = None  # e.g., GOOGLE_REVIEW_LINK
    sms_sent: Optional[bool] = None
