from pydantic import BaseModel, EmailStr

class LeadIn(BaseModel):
    name: str | None = None
    phone: str
    email: EmailStr | None = None
    message: str | None = None
    send_auto_reply: bool = False
    manual_entry: bool = False

class LeadOut(BaseModel):
    sms_sent: bool
