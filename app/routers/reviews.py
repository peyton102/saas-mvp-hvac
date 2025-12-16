# app/routers/reviews.py
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session, select
from datetime import datetime, timedelta, timezone

from app import config, storage
from app.services.sms import send_sms
from app.services.email import send_email
from app.db import get_session
from app.models import Review as ReviewModel
from app.utils.phone import normalize_us_phone
from app.deps import get_tenant_id  # ✅ tenant resolver
from app.tenantold import brand

router = APIRouter(prefix="", tags=["reviews"])


# ----------------------- helpers -----------------------

def _blocked_number(phone: str) -> bool:
    bl = (getattr(config, "SMS_BLOCKLIST", "") or "").split(",")
    return phone in [x.strip() for x in bl if x.strip()]


def _review_link_for_tenant(tenant_id: str, session: Session) -> str:
    """
    Prefer per-tenant REVIEW_GOOGLE_URL via brand(…, db=session).
    Fallbacks:
      - config.GOOGLE_REVIEW_LINK (legacy)
      - brand(..., db=session)['BOOKING_LINK'] (last resort)
    """
    try:
        b = brand(tenant_id, db=session)
        link = (b.get("REVIEW_GOOGLE_URL") or "").strip()
        if link:
            return link
    except Exception:
        pass

    # legacy global fallback
    link = (getattr(config, "GOOGLE_REVIEW_LINK", "") or "").strip()
    if link:
        return link

    # last resort: booking link
    try:
        b = brand(tenant_id, db=session)
        return (b.get("BOOKING_LINK") or "").strip()
    except Exception:
        return ""


def _from_name_for_tenant(tenant_id: str) -> str:
    try:
        b = brand(tenant_id)
        return b.get("FROM_NAME") or getattr(config, "FROM_NAME", "Our Team")
    except Exception:
        return getattr(config, "FROM_NAME", "Our Team")


# ------------------------- routes -------------------------

@router.post("/jobs/complete")
def mark_job_complete(
    payload: dict,
    request: Request,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    After-job review request.
    Body: { phone, name?, job_id?, notes?, email?, message? }

    - Normalizes phone
    - Throttles via storage.sent_recently (ANTI_SPAM_MINUTES)
    - Honors SMS_BLOCKLIST
    - Sends SMS + optional email copy
    - DB-first to Review table; CSV only if DB_FIRST=false
    - Stamps tenant_id
    """
    phone = normalize_us_phone(payload.get("phone") or "")
    email = (payload.get("email") or "").strip()
    name = (payload.get("name") or "").strip() or "there"
    job_id = (payload.get("job_id") or "").strip() or None
    notes = (payload.get("notes") or "").strip() or None

    # per-tenant review link + from name
    review_link = _review_link_for_tenant(tenant_id, session)
    from_name = _from_name_for_tenant(tenant_id)

    # Allow custom message override
    msg = (payload.get("message") or
           f"Thanks {name} for choosing {from_name}! If we did a great job, would you leave a review? {review_link}").strip()

    # SMS
    sms_ok = False
    if phone and not _blocked_number(phone):
        minutes = int(getattr(config, "ANTI_SPAM_MINUTES", 120))
        try:
            if not storage.sent_recently(phone, minutes=minutes):
                sms_ok = send_sms(phone, msg)
            else:
                print(f"[REVIEWS] Throttled SMS to {phone} ({minutes}m)")
        except Exception as e:
            print(f"[REVIEW SMS ERROR] {e}")

    # Email (optional)
    email_ok = False
    if email:
        try:
            sub = f"Thanks from {from_name} — quick review?"
            hi_name = name if name != "there" else ""
            txt = f"Hi {hi_name},\n\n{msg}\n"
            html = f"<p>Hi {hi_name},</p><p>{msg}</p>"
            email_ok = send_email(email, sub, txt, html)
        except Exception as e:
            print(f"[REVIEW EMAIL ERROR] {e}")

    # CSV write ONLY if DB_FIRST is false (kept for backup compatibility)
    if not getattr(config, "DB_FIRST", True):
        try:
            storage.save_review(
                {
                    "phone": phone,
                    "name": name,
                    "job_id": job_id or "",
                    "notes": notes or "",
                    "tenant_id": tenant_id,
                },
                sms_body=msg,
                sms_sent=bool(sms_ok),
                source="api",
            )
        except TypeError:
            # older storage.save_review without tenant_id support
            storage.save_review(
                {
                    "phone": phone,
                    "name": name,
                    "job_id": job_id or "",
                    "notes": notes or "",
                },
                sms_body=msg,
                sms_sent=bool(sms_ok),
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
    limit: int = Query(20, ge=1, le=200),
    source: str = Query("db", pattern="^(csv|db)$"),
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """
    source=db (default): read Review table (tenant-scoped)
    source=csv: read data/reviews.csv (filtered by tenant_id if present)
    """
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
                "created_at": (
    (r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc))
    .astimezone(timezone.utc)
    .isoformat(timespec="seconds")
    .replace("+00:00", "Z")
    if r.created_at else None
),

                "phone": r.phone,
                "name": r.name,
                "job_id": r.job_id,
                "notes": r.notes,
                "review_link": r.review_link or "",
                "sms_sent": bool(r.sms_sent),
                "tenant_id": r.tenant_id,
            }
            for r in rows
        ]
        return {"count": len(items), "items": items}

    # CSV
    items = storage.read_reviews(limit)
    if items and isinstance(items[0], dict) and "tenant_id" in items[0]:
        items = [it for it in items if it.get("tenant_id") == tenant_id]
    return {"count": len(items), "items": items}
