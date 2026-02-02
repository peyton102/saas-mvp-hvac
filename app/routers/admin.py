# app/routers/admin.py
from datetime import datetime, timedelta, timezone
from app.models import Tenant
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from sqlalchemy import delete, func, or_

from app.db import get_session
from app.models import Lead, Booking, Review, ReminderSent
from ..deps import get_tenant_id  # ✅ use shared tenant resolver
from app.deps import get_tenant_id
router = APIRouter(prefix="/admin", tags=["admin"])
from sqlalchemy import text
from sqlalchemy import func  # at top if not already imported
from typing import List, Dict

def _utcnow():
    return datetime.now(timezone.utc)


def _like_filters(model, like: str):
    """
    Case-insensitive LIKE compatible with SQLite.
    Builds OR(lower(col) LIKE '%like%') across a few text columns if present.
    """
    needle = f"%{(like or '').lower()}%"
    exprs = []
    for attr_name in ("name", "email", "phone", "message", "notes"):
        if hasattr(model, attr_name):
            col = getattr(model, attr_name)
            exprs.append(func.lower(col).like(needle))
    return or_(*exprs) if exprs else None


@router.post("/debug/purge-test-data")
def purge_test_data(
    older_than_days: int = Query(0, ge=0, le=365),   # 0 = ignore age filter
    like: str = Query("test"),
    dry_run: bool = Query(True),
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),         # ✅ tenant injected
):
    """
    Tenant-scoped purge for Leads/Bookings/Reviews/ReminderSent.
    Requires your existing /debug/* bearer lock.
    """
    now = _utcnow()
    cutoff = now - timedelta(days=older_than_days) if older_than_days > 0 else None

    def _count(model) -> int:
        stmt = select(model.id).where(model.tenant_id == tenant_id)
        lf = _like_filters(model, like) if like else None
        if cutoff and hasattr(model, "created_at"):
            stmt = stmt.where(model.created_at < cutoff)
        if lf is not None:
            stmt = stmt.where(lf)
        return len(session.exec(stmt).all())

    def _purge(model) -> int:
        stmt = delete(model).where(model.tenant_id == tenant_id)
        lf = _like_filters(model, like) if like else None
        if cutoff and hasattr(model, "created_at"):
            stmt = stmt.where(model.created_at < cutoff)
        if lf is not None:
            stmt = stmt.where(lf)
        result = session.exec(stmt)
        session.commit()
        try:
            return int(result.rowcount or 0)
        except Exception:
            return 0

    counts: Dict[str, int] = {
        "leads": _count(Lead),
        "bookings": _count(Booking),
        "reviews": _count(Review),
        "reminders_sent": _count(ReminderSent),
    }

    deleted = {"leads": 0, "bookings": 0, "reviews": 0, "reminders_sent": 0}
    if not dry_run:
        deleted["leads"] = _purge(Lead)
        deleted["bookings"] = _purge(Booking)
        deleted["reviews"] = _purge(Review)
        deleted["reminders_sent"] = _purge(ReminderSent)

    return {
        "tenant_id": tenant_id,
        "dry_run": dry_run,
        "older_than_days": older_than_days,
        "like": like,
        "counts": counts,
        "deleted": deleted,
    }
# --- create helpful indexes (idempotent) ------------------------------------

@router.post("/debug/create-indexes")
def debug_create_indexes(session: Session = Depends(get_session)):
    """
    Create tenant-focused indexes (safe to run multiple times).
    Works on SQLite; uses IF NOT EXISTS and SQLAlchemy text().
    """
    # Use explicit table names to avoid quoting surprises.
    # (These match the default SQLModel table names in your app.)
    tbl_lead = "lead"
    tbl_booking = "booking"
    tbl_reminders = "remindersent"
    tbl_review = "review"

    statements = [
        # Leads
        f"CREATE INDEX IF NOT EXISTS idx_{tbl_lead}_tenant ON {tbl_lead}(tenant_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{tbl_lead}_tenant_phone ON {tbl_lead}(tenant_id, phone)",

        # Bookings
        f"CREATE INDEX IF NOT EXISTS idx_{tbl_booking}_tenant ON {tbl_booking}(tenant_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{tbl_booking}_tenant_start ON {tbl_booking}(tenant_id, start)",

        # Reminders
        f"CREATE INDEX IF NOT EXISTS idx_{tbl_reminders}_tenant ON {tbl_reminders}(tenant_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{tbl_reminders}_tenant_start ON {tbl_reminders}(tenant_id, booking_start)",

        # Reviews
        f"CREATE INDEX IF NOT EXISTS idx_{tbl_review}_tenant ON {tbl_review}(tenant_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{tbl_review}_tenant_phone ON {tbl_review}(tenant_id, phone)",
    ]

    created = 0
    for stmt in statements:
        session.exec(text(stmt))
        created += 1

    session.commit()
    return {"ok": True, "created_or_existing": created}
@router.get("/debug/audit-tenant-data")
def debug_audit_tenant_data(session: Session = Depends(get_session)):
    """
    Summarize rows by tenant_id for core tables.
    Helps spot any 'public' rows that slipped through.
    """
    def _by_tenant(model) -> List[Dict[str, int]]:
        rows = (
            session.query(getattr(model, "tenant_id"), func.count(model.id))
            .group_by(getattr(model, "tenant_id"))
            .all()
        )
        return [{"tenant_id": t or "NULL", "count": int(c)} for t, c in rows]

    data = {
        "leads": _by_tenant(Lead),
        "bookings": _by_tenant(Booking),
        "reviews": _by_tenant(Review),
        "reminders_sent": _by_tenant(ReminderSent),
    }

    has_public = any(any(r["tenant_id"] == "public" and r["count"] > 0 for r in v) for v in data.values())
    return {"ok": True, "has_public_rows": has_public, "by_table": data}
# --- repair: migrate 'public' rows to caller's tenant (debug-only) ------------

@router.post("/debug/repair-tenant-ids")
def repair_tenant_ids(
    tenant_id: str = Depends(get_tenant_id),          # ✅ resolve tenant reliably
    dry_run: bool = Query(True),
    older_than_days: int = Query(0, ge=0, le=365),
    like: str = Query("", description="optional case-insensitive substring filter"),
    session: Session = Depends(get_session),
):
    """
    DEBUG-ONLY: Re-stamp rows with tenant_id='public' to the caller's tenant.
    Defaults to DRY RUN. Use ?dry_run=false to apply.
    """
    now = _utcnow()
    cutoff = now - timedelta(days=older_than_days) if older_than_days > 0 else None

    def _select_public(model):
        stmt = select(model).where(model.tenant_id == "public")
        lf = _like_filters(model, like) if like else None
        if cutoff and hasattr(model, "created_at"):
            stmt = stmt.where(model.created_at < cutoff)
        if lf is not None:
            stmt = stmt.where(lf)
        return session.exec(stmt).all()

    touched = {"leads": 0, "bookings": 0, "reviews": 0, "reminders_sent": 0}
    previews = {"leads": [], "bookings": [], "reviews": [], "reminders_sent": []}

    targets = [
        ("leads", Lead),
        ("bookings", Booking),
        ("reviews", Review),
        ("reminders_sent", ReminderSent),
    ]

    for label, model in targets:
        rows = _select_public(model)
        previews[label] = [
            {"id": r.id, "created_at": getattr(r, "created_at", None), "phone": getattr(r, "phone", None)}
            for r in rows[:25]
        ]
        if not dry_run and rows:
            for r in rows:
                r.tenant_id = tenant_id
            session.commit()
        touched[label] = len(rows)

    return {
        "tenant_id": tenant_id,
        "dry_run": dry_run,
        "older_than_days": older_than_days,
        "like": like,
        "would_touch_counts": touched,
        "preview_first25": previews,
    }
@router.get("/audit/users")
def admin_audit_users(session: Session = Depends(get_session)):
    rows = session.exec(
        select(Tenant.email, Tenant.slug, Tenant.created_at)
        .order_by(Tenant.created_at.desc())
    ).all()

    return [
        {
            "email": r[0],
            "tenant_slug": r[1],
            "created_at": r[2],
            "deleted_at": None,
        }
        for r in rows
    ]
