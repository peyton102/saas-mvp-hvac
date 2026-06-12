# app/services/lead_nudges.py
"""
Lead follow-up nudge service.

For every tenant, finds leads that:
  - status = 'new'  (owner hasn't marked them contacted/won/lost)
  - created more than `hours_old` hours ago
  - nudge_sent_at IS NULL  (haven't already been nudged)

Sends one follow-up SMS to the customer and stamps nudge_sent_at so it
never fires twice.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlmodel import Session

from app.services.sms import lead_nudge_sms


def _ensure_nudge_column(session: Session) -> None:
    """Add nudge_sent_at to lead table if it doesn't exist yet."""
    try:
        session.exec(text("SAVEPOINT sp_lead_nudge_col"))
        session.exec(text("ALTER TABLE lead ADD COLUMN nudge_sent_at TIMESTAMP WITH TIME ZONE"))
        session.exec(text("RELEASE SAVEPOINT sp_lead_nudge_col"))
    except Exception:
        session.exec(text("ROLLBACK TO SAVEPOINT sp_lead_nudge_col"))


def send_lead_nudges_all(hours_old: float, session: Session, max_hours_old: float = 24.0) -> dict:
    """
    Run nudges across all active tenants.

    Args:
        hours_old:     How many hours a 'new' lead must be stale before nudging.
        session:       DB session (injected by FastAPI).
        max_hours_old: Upper bound — leads older than this are skipped (default 24h = same day only).

    Returns dict with counts for logging.
    """
    _ensure_nudge_column(session)

    now = datetime.now(timezone.utc)
    cutoff_max = now - timedelta(hours=hours_old)       # must be at least this old
    cutoff_min = now - timedelta(hours=max_hours_old)   # must not be older than this

    # Only nudge leads captured within the same day window (between min and max cutoff).
    rows = session.exec(text("""
        SELECT id, tenant_id, name, phone
        FROM lead
        WHERE status = 'new'
          AND nudge_sent_at IS NULL
          AND created_at <= :cutoff_max
          AND created_at >= :cutoff_min
          AND phone IS NOT NULL
          AND phone != ''
        ORDER BY created_at ASC
    """).bindparams(cutoff_max=cutoff_max, cutoff_min=cutoff_min)).all()

    sent = 0
    failed = 0

    for row in rows:
        lead_id   = row[0]
        tenant_id = row[1]
        name      = row[2] or ""
        phone     = row[3] or ""

        ok = lead_nudge_sms(tenant_id, {"name": name, "phone": phone})

        # Stamp and commit immediately — so a mid-run kill never causes re-sends.
        now_iso = datetime.now(timezone.utc).isoformat()
        session.exec(text("""
            UPDATE lead SET nudge_sent_at = :ts WHERE id = :id
        """).bindparams(ts=now_iso, id=lead_id))
        session.commit()

        if ok:
            sent += 1
            print(f"[LEAD NUDGE] sent tenant={tenant_id} lead_id={lead_id} phone={phone}")
        else:
            failed += 1
            print(f"[LEAD NUDGE] failed tenant={tenant_id} lead_id={lead_id} phone={phone}")

    return {
        "ok": True,
        "hours_old": hours_old,
        "max_hours_old": max_hours_old,
        "leads_checked": len(rows),
        "nudges_sent": sent,
        "nudges_failed": failed,
    }
