from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from app import config, storage
from app.services.sms import send_sms

# This exact name is what main.py imports
router = APIRouter(tags=["reviews"])


class CompleteJobIn(BaseModel):
    phone: str
    name: str | None = None
    email: EmailStr | None = None
    job_id: str | None = None
    notes: str | None = None


class CompleteJobOut(BaseModel):
    sms_sent: bool


@router.post("/jobs/complete", response_model=CompleteJobOut)
def mark_job_complete(payload: CompleteJobIn):
    review_link = getattr(config, "GOOGLE_REVIEW_LINK", "")
    if not review_link:
        raise HTTPException(status_code=500, detail="GOOGLE_REVIEW_LINK not set")

    first = (payload.name or "there").split(" ")[0]
    body = (
        f"Thanks {first} for choosing {config.FROM_NAME}! "
        f"If we earned it, could you leave a quick Google review? {review_link}"
    )

    ok = send_sms(payload.phone, body)

    storage.save_review_request(
        payload.model_dump(), sms_body=body, sms_sent=ok, source="api"
    )
    return CompleteJobOut(sms_sent=ok)


@router.get("/debug/reviews")
def debug_reviews(limit: int = 20):
    items = storage.read_reviews(limit)
    return {"count": len(items), "items": items}