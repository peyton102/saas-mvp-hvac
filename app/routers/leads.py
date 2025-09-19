from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app import config, storage
from app.services.sms import send_sms
from app.schemas import LeadIn, LeadOut
from app.utils.phone import normalize_us_phone
from app.db import get_session
from app.models import Lead as LeadModel

router = APIRouter(prefix="", tags=["leads"])


@router.post("/lead", response_model=LeadOut)
def create_lead(payload: LeadIn, session: Session = Depends(get_session)):
    # Normalize to E.164
    e164 = normalize_us_phone(payload.phone)

    # SMS body
    first = (payload.name or "").split(" ")[0] if payload.name else "there"
    body = (
        f"Hey {first}, thanks for contacting {config.FROM_NAME}! "
        f"Grab the next available slot here: {config.BOOKING_LINK}. "
        f"Prefer a call? Reply here."
    )

    # Throttle duplicate texts
    if storage.sent_recently(e164, minutes=config.ANTI_SPAM_MINUTES):
        print(f"[THROTTLE] Skipping SMS to {e164} (last sent within {config.ANTI_SPAM_MINUTES} min)")
        ok = False
        # CSV log
        storage.save_lead({**payload.model_dump(), "phone": e164}, sms_body=body, sms_sent=ok, source="api")
        # DB write
        session.add(LeadModel(
            name=(payload.name or "").strip(),
            phone=e164,
            email=(payload.email or "").strip(),
            message=(payload.message or "").strip(),
        ))
        session.commit()
        return LeadOut(sms_sent=ok)

    # Send (honors SMS_DRY_RUN)
    ok = send_sms(e164, body)
    # CSV log
    storage.save_lead({**payload.model_dump(), "phone": e164}, sms_body=body, sms_sent=ok, source="api")
    # DB write
    session.add(LeadModel(
        name=(payload.name or "").strip(),
        phone=e164,
        email=(payload.email or "").strip(),
        message=(payload.message or "").strip(),
    ))
    session.commit()

    return LeadOut(sms_sent=ok)


@router.get("/debug/leads")
def debug_leads(
    limit: int = 20,
    source: str = "csv",
    session: Session = Depends(get_session),
):
    if source.lower() == "db":
        rows = session.exec(
            select(LeadModel).order_by(LeadModel.id.desc()).limit(limit)
        ).all()
        items = [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "name": r.name,
                "phone": r.phone,
                "email": r.email,
                "message": r.message,
            }
            for r in rows
        ]
        return {"count": len(items), "items": items}
    # default CSV path (keeps existing behavior)
    items = storage.read_leads(limit)
    return {"count": len(items), "items": items}
