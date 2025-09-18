# app/routers/reviews.py
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app import config, storage
from app.services.sms import send_sms
from app.db import get_session
from app.models import Review as ReviewModel

router = APIRouter(prefix="", tags=["reviews"])


@router.post("/jobs/complete")
def job_complete(payload: Dict[str, Any], session: Session = Depends(get_session)):
    """
    After-job completion: send review SMS + log to CSV + write DB row.
    Expected JSON:
      { "phone": "+1...", "name": "Customer", "job_id": "JOB-123", "notes": "what was done" }
    """
    phone: str = (payload.get("phone") or "").strip()
    if not phone:
        raise HTTPException(status_code=422, detail="phone is required")

    name: str = (payload.get("name") or "").strip()
    job_id: Optional[str] = payload.get("job_id") or None
    notes: str = (payload.get("notes") or "").strip()

    # Build SMS
    review_link = getattr(config, "GOOGLE_REVIEW_LINK", "").strip()
    body = (
        f"Thanks for choosing {config.FROM_NAME}! "
        f"If we did a great job, would you leave a quick Google review? {review_link} "
        f"— it helps a ton. Thank you!"
    ).strip()

    # Send SMS (honors SMS_DRY_RUN)
    ok = send_sms(phone, body)

    # CSV log (preserve existing behavior)
    if hasattr(storage, "save_review"):
        storage.save_review(
            {
                "phone": phone,
                "name": name,
                "job_id": job_id or "",
                "notes": notes,
            },
            sms_body=body,
            sms_sent=ok,
            source="api",
        )

    # DB write (new)
    session.add(
        ReviewModel(
            phone=phone,
            name=name or None,
            job_id=job_id,
            notes=notes or None,
            review_link=review_link or None,
            sms_sent=bool(ok),
        )
    )
    session.commit()

    return {"ok": True, "sms_sent": bool(ok)}


@router.get("/debug/reviews")
def debug_reviews(limit: int = 20, session: Session = Depends(get_session)):
    rows = session.exec(
        select(ReviewModel).order_by(ReviewModel.id.desc()).limit(limit)
    ).all()
    items = [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "phone": r.phone,
            "name": r.name,
            "job_id": r.job_id,
            "notes": r.notes,
            "review_link": r.review_link,
            "sms_sent": r.sms_sent,
        }
        for r in rows
    ]
    return {"count": len(items), "items": items}
