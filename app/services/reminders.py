# app/routers/reviews.py
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session, select

from app import config, storage
from app.services.sms import send_sms
from app.services.email import send_email  # <-- added
from app.db import get_session
from app.models import Review as ReviewModel
from app.utils.phone import normalize_us_phone

router = APIRouter(prefix="", tags=["reviews"])


def _tenant_from_headers(request: Request) -> str:
    auth = (request.headers.get("authorization") or "")
    api_key = (request.headers.get("x-api-key") or "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else api_key.strip()
    return config.TENANT_KEYS.get(token, "public")


@router.post("/jobs/complete")
def mark_job_complete(
    payload: dict,
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Body: { phone, name?, job_id?, notes?, email? }
    Sends review SMS (DRY-RUN honored) + optional email copy, logs to DB (+ CSV if DB_FIRST=false).
    """
    tenant_id = _tenant_from_headers(request)

    phone = normalize_us_phone(payload.get("phone") or "")
    email = (payload.get("email") or "").strip()  # <-- optional
    name = (payload.get("name") or "").strip() or "there"
    job_id = (payload.get("job_id") or "").strip() or None
    notes = (payload.get("notes") or "").strip() or None

    review_link = getattr(config, "GOOGLE_REVIEW_LINK", "") or ""
    msg = f"Thanks {name} for choosing {config.FROM_NAME}! If we did a great job, would you leave a review? {review_link}".strip()

    sms_ok = False
    if phone:
        try:
            sms_ok = send_sms(phone, msg)
        except Exception as e:
            print(f"[REVIEW SMS ERROR] {e}")

    # Optional email copy (DRY-RUN in email service)
    email_ok = False
    if email:
        try:
            sub = f"Thanks from {config.FROM_NAME} — quick review?"
            txt = f"Hi {name if name!='there' else ''},\n\n{msg}\n"
            html = f"<p>Hi {name if name!='there' else ''},</p><p>{msg}</p>"
            email_ok = send_email(email, sub, txt, html)
        except Exception as e:
            print(f"[REVIEW EMAIL ERROR] {e}")

    # CSV write ONLY if DB_FIRST is false (kept for backup compatibility)
    if not getattr(config, "DB_FIRST", True):
        storage.save_review(
            {
                "phone": phone,
                "name": name,
                "job_id": job_id or "",
                "notes": notes or "",
                "tenant_id": tenant_id,
            },
            sms_body=msg,
            sms_sent=sms_ok,
            source="api",
        )

    # DB write (primary)
    session.add(
        ReviewModel(
            phone=phone,
            name=name if name != "there" else "",
            job_id=job_id,
            notes=notes,
            review_link=review_link or None,
            sms_sent=bool(sms_ok),
            tenant_id=tenant_id,
        )
    )
    session.commit()

    return {"ok": True, "sms_sent": bool(sms_ok), "email_sent": bool(email_ok)}


@router.get("/debug/reviews")
def debug_reviews(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    source: str = Query("db", pattern="^(csv|db)$"),
    session: Session = Depends(get_session),
):
    """
    source=csv: read data/reviews.csv (not tenant-filtered unless CSV has tenant_id)
    source=db: read Review table, scoped to tenant
    """
    tenant_id = _tenant_from_headers(request)

    if source == "db":
        rows = session.exec(
            select(ReviewModel)
            .where(ReviewModel.tenant_id == tenant_id)
            .order_by(ReviewModel.id.desc())
            .limit(limit)
        ).all()
        items = [
            {
                "id": r.id,
                "created_at": (r.created_at.isoformat() if r.created_at else None),
                "name": r.name or "",
                "phone": r.phone or "",
                "job_id": r.job_id or "",
                "notes": r.notes or "",
                "sms_sent": bool(r.sms_sent),
                "source": "jobs.complete",
                "tenant_id": r.tenant_id,
            } for r in rows
        ]
        return {"count": len(items), "items": items}

    # CSV fallback
    items = storage.read_reviews(limit)
    # filter CSV if it has tenant_id; otherwise return raw
    filtered = [it for it in items if (it.get("tenant_id") == tenant_id)] if items and isinstance(items[0], dict) and "tenant_id" in items[0] else items
    return {"count": len(filtered), "items": filtered}
