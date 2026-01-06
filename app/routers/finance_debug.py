# app/routers/finance_debug.py
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.db import get_session
from app.deps import get_tenant_id

# 🔁 Robust imports: try multiple class name variants so red underlines go away.
# Your module name is `models_finance` (singular) — we’ll use that first.
try:
    from app.models_finance import FinanceRevenue as RevenueModel, FinanceCost as CostModel
except Exception:
    try:
        # Some projects name them shorter:
        from app.models_finance import Revenue as RevenueModel, Cost as CostModel
    except Exception:
        # Fallbacks if they live in app.models
        from app.models import FinanceRevenue as RevenueModel, FinanceCost as CostModel

router = APIRouter(prefix="/debug/finance", tags=["debug-finance"])

def _auth_ok(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)) -> None:
    # Your app allows either Debug Bearer or X-API-Key on /debug routes
    if not x_api_key and not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization or X-API-Key")

@router.get("/recent")
def recent(
    limit: int = 20,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
    _: None = Depends(_auth_ok),
):
    revs = (
        session.query(RevenueModel)
        .filter(RevenueModel.tenant_id == tenant_id)
        .order_by(RevenueModel.created_at.desc())
        .limit(limit)
        .all()
    )
    costs = (
        session.query(CostModel)
        .filter(CostModel.tenant_id == tenant_id)
        .order_by(CostModel.created_at.desc())
        .limit(limit)
        .all()
    )

    def row_r(r, kind: str):
        return {
            "id": getattr(r, "id", None),
            "amount": str(getattr(r, "amount", "")),
            "source": getattr(r, "source", None),
            "category": getattr(r, "category", None),
            "vendor": getattr(r, "vendor", None),
            "notes": getattr(r, "notes", None),

            # ✅ ADD THESE:
            "part_code": getattr(r, "part_code", None),
            "job_type": getattr(r, "job_type", None),

            "created_at": getattr(r, "created_at", None),
            "kind": kind,
        }
    return {
        "revenue": [row_r(r, "revenue") for r in revs],
        "costs": [row_r(c, "cost") for c in costs],
    }


@router.delete("/revenue/{item_id}")
def delete_revenue(
    item_id: int,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
    _: None = Depends(_auth_ok),
):
    row = session.query(RevenueModel).filter(
        RevenueModel.id == item_id,
        RevenueModel.tenant_id == tenant_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    session.delete(row)
    session.commit()
    return {"ok": True, "deleted": item_id, "kind": "revenue"}

@router.delete("/cost/{item_id}")
def delete_cost(
    item_id: int,
    session: Session = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
    _: None = Depends(_auth_ok),
):
    row = session.query(CostModel).filter(
        CostModel.id == item_id,
        CostModel.tenant_id == tenant_id
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    session.delete(row)
    session.commit()
    return {"ok": True, "deleted": item_id, "kind": "cost"}
