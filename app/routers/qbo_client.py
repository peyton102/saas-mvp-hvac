# app/routers/qbo_client.py
from __future__ import annotations
from datetime import date
from typing import List, Dict, Any, Optional

import os
import json
import logging
import httpx

from fastapi import HTTPException
from sqlmodel import Session, select
from app import models_finance


log = logging.getLogger("qbo")

# ----------------------------
# Safe defaults (non-breaking)
# ----------------------------
DRY_RUN: bool = True
QBO_PROXY_BASE: str = os.environ.get("QBO_PROXY_BASE", "").rstrip("/")

# Resolve by NAME if possible (IDs optional)
ITEM_NAME: Optional[str] = os.environ.get("QBO_ITEM_NAME", "Services")
CUSTOMER_NAME: Optional[str] = os.environ.get("QBO_CUSTOMER_NAME", "Test Customer")
EXPENSE_ACCT_NAME: Optional[str] = os.environ.get("QBO_EXPENSE_ACCT_NAME", "Cost of Goods Sold")
DEFAULT_VENDOR_NAME: Optional[str] = os.environ.get("QBO_VENDOR_NAME")  # optional

# If you already know IDs, set them here; otherwise we’ll try by name via query.
QBO_ITEM_ID: Optional[str] = None
QBO_CUSTOMER_ID: Optional[str] = None
QBO_EXPENSE_ACCT_ID: Optional[str] = None
QBO_DEFAULT_VENDOR_ID: Optional[str] = None

# ---------------------------------
# Optional idempotency (if model exists)
# ---------------------------------
try:
    QboExport = models_finance.QboExport
except AttributeError:
    QboExport = None

def _already_exported(session: Session, kind: str, row_id: int) -> bool:
    if QboExport is None:
        return False
    stmt = select(QboExport).where(QboExport.kind == kind, QboExport.row_id == row_id)
    return session.exec(stmt).first() is not None

def _mark_exported(session: Session, kind: str, row_id: int, qbo_id: str, note: str = ""):
    if QboExport is None:
        return
    rec = QboExport(kind=kind, row_id=row_id, qbo_id=qbo_id, note=note)
    session.add(rec)
    session.commit()
def qbo_create_sales_receipt(tenant, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Local import avoids circular import and keeps other files untouched
    from app.routers import qbo as qbo_router
    return qbo_router.qbo_post(tenant, "salesreceipt", payload)

def qbo_create_bill(tenant, payload: Dict[str, Any]) -> Dict[str, Any]:
    from app.routers import qbo as qbo_router
    return qbo_router.qbo_post(tenant, "bill", payload)

# ----------------------------
# Lightweight proxy callers
# ----------------------------
def _tenant_headers(tenant) -> Dict[str, str]:
    tid = None
    for f in ("key", "tenant_key", "tenant_id", "slug", "name", "id"):
        if hasattr(tenant, f):
            tid = str(getattr(tenant, f))
            break
    return {
        "ngrok-skip-browser-warning": "true",
        "x-tenant-id": tid or "default",
        "X-API-Key": tid or "default",
        "Content-Type": "application/json",
    }

def qbo_post(tenant, entity: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not QBO_PROXY_BASE:
        fake = {"Id": f"DRYRUN-{entity}-{payload.get('PrivateNote') or 'no-note'}"}
        log.info("QBO DRY-RUN POST %s: %s -> %s", entity, payload, fake)
        return fake

    url = f"{QBO_PROXY_BASE}/qbo/create"
    params = {"entity": entity}
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, params=params, headers=_tenant_headers(tenant), content=json.dumps(payload))
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=f"QBO proxy error: {r.text}")
        data = r.json()
        if isinstance(data, dict) and "Id" in data:
            return data
        if isinstance(data, dict):
            inner = next((v for v in data.values() if isinstance(v, dict) and "Id" in v), None)
            if inner:
                return inner
        raise HTTPException(status_code=502, detail=f"QBO proxy malformed create response: {data}")
    except Exception as exc:
        if DRY_RUN:
            fake = {"Id": f"DRYRUN-{entity}-{payload.get('PrivateNote') or 'no-note'}"}
            log.warning("QBO POST fallback to DRY-RUN due to %s. Payload=%s", exc, payload)
            return fake
        raise

def qbo_query(tenant, sql: str) -> List[Dict[str, Any]]:
    if not QBO_PROXY_BASE:
        log.info("QBO DRY-RUN QUERY (proxy base unset): %s", sql)
        return []
    url = f"{QBO_PROXY_BASE}/qbo/query"
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, headers=_tenant_headers(tenant), params={"sql": sql})
        if r.status_code == 404:
            log.info("QBO query route not found; returning [] for DRY-RUN.")
            return []
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=f"QBO proxy error: {r.text}")
        data = r.json()
        if isinstance(data, dict) and "QueryResponse" in data:
            qr = data["QueryResponse"]
            for v in qr.values():
                if isinstance(v, list):
                    return v
            return []
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        log.warning("QBO QUERY failed (%s). Returning []. sql=%s", exc, sql)
        return []

# ----------------------------
# Helpers to resolve IDs by name
# ----------------------------
def _resolve_id_by_name(tenant, entity: str, name: str) -> Optional[str]:
    """Resolve an entity ID by exact Name using the proxy (if available)."""
    if not name:
        return None

    table_map = {"Item": "Item", "Customer": "Customer", "Account": "Account", "Vendor": "Vendor"}
    table = table_map.get(entity)
    if not table:
        return None

    # Escape single quotes for QBO SQL safely (build string first; no nested escapes in f-string)
    name_escaped = name.replace("'", "''")
    sql = f"SELECT Id, Name FROM {table} WHERE Name = '{name_escaped}'"

    rows = qbo_query(tenant, sql)
    if rows:
        rid = str(rows[0].get("Id"))
        log.info("Resolved %s '%s' -> Id %s", entity, name, rid)
        return rid

    log.info("Could not resolve %s by name '%s' (proxy unavailable or not found).", entity, name)
    return None

def _ensure_mapping_ids(tenant) -> Dict[str, Optional[str]]:
    item_id = QBO_ITEM_ID or _resolve_id_by_name(tenant, "Item", ITEM_NAME)
    cust_id = QBO_CUSTOMER_ID or _resolve_id_by_name(tenant, "Customer", CUSTOMER_NAME)
    acct_id = QBO_EXPENSE_ACCT_ID or _resolve_id_by_name(tenant, "Account", EXPENSE_ACCT_NAME)
    vend_id = QBO_DEFAULT_VENDOR_ID or _resolve_id_by_name(tenant, "Vendor", DEFAULT_VENDOR_NAME) if DEFAULT_VENDOR_NAME else None
    return {"item": item_id, "customer": cust_id, "account": acct_id, "vendor": vend_id}

# ----------------------------
# PUBLIC: export_finance
# ----------------------------
def export_finance(
    session: Session,
    tenant,
    revenues: List[models_finance.Revenue],
    costs: List[models_finance.Cost],
    start: date,
    end: date,
) -> Dict[str, Any]:
    ids = _ensure_mapping_ids(tenant)
    have_ids = all([ids["item"], ids["customer"], ids["account"]])
    real_exports_ok = (not DRY_RUN) or (QBO_PROXY_BASE and have_ids)

    created_sales, created_bills = [], []

    # Revenues -> SalesReceipt
    for r in revenues:
        row_id = int(r.id)
        if _already_exported(session, "revenue", row_id):
            continue

        payload = {
            "TxnDate": (r.created_at.date() if r.created_at else start).isoformat(),
            "PrivateNote": f"export:{row_id}",
            "Line": [{
                "Amount": float(r.amount or 0),
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {
                    "ItemRef": {"value": ids["item"] or "DRYRUN-ITEM"}
                },
            }],
            "CustomerRef": {"value": ids["customer"] or "DRYRUN-CUSTOMER"},
        }

        created = qbo_post(tenant, "SalesReceipt", payload) if real_exports_ok else {"Id": f"DRYRUN-SR-{row_id}"}
        created_sales.append(created)
        _mark_exported(session, "revenue", row_id, created["Id"], payload["PrivateNote"])

    # Costs -> Bill
    for c in costs:
        row_id = int(c.id)
        if _already_exported(session, "cost", row_id):
            continue

        bill_line = {
            "Amount": float(c.amount or 0),
            "DetailType": "AccountBasedExpenseLineDetail",
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"value": ids["account"] or "DRYRUN-COGS"}
            },
        }

        payload = {
            "TxnDate": (c.created_at.date() if c.created_at else start).isoformat(),
            "PrivateNote": f"export:{row_id}",
            "Line": [bill_line],
        }
        if ids["vendor"] or (getattr(c, "vendor", None)):
            payload["VendorRef"] = {"value": ids["vendor"] or str(getattr(c, "vendor"))}

        created = qbo_post(tenant, "Bill", payload) if real_exports_ok else {"Id": f"DRYRUN-BILL-{row_id}"}
        created_bills.append(created)
        _mark_exported(session, "cost", row_id, created["Id"], payload["PrivateNote"])

    # Best-effort label
    tenant_label = None
    for f in ("key", "slug", "name", "id", "tenant_key", "tenant_id"):
        if hasattr(tenant, f):
            tenant_label = str(getattr(tenant, f))
            break

    return {
        "revenues_exported": len(created_sales),
        "costs_exported": len(created_bills),
        "tenant": tenant_label or "unknown",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "mode": "real" if real_exports_ok else "dry-run",
    }
