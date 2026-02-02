import json
from typing import Any, Optional
from sqlmodel import Session

from app.models import AuditEvent


def _safe_json(payload: Any) -> str:
    try:
        return json.dumps(payload, default=str)
    except Exception:
        return json.dumps({"_serialization_error": True, "raw": str(payload)})


def backup_event(
    session: Session,
    *,
    category: str,
    action: str,
    tenant_id: Optional[str] = None,
    user_email: Optional[str] = None,
    payload: Any = None,
    ok: bool = True,
    error: Optional[str] = None,
) -> str:
    # Best-effort only — never raises.
    try:
        row = AuditEvent(
            tenant_id=tenant_id,
            user_email=user_email,
            category=category,
            action=action,
            payload_json=_safe_json(payload or {}),
            ok=ok,
            error=error,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        return ""
