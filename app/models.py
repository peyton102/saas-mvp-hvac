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
