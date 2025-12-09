# app/routers/admin_tenants.py
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Tenant
from app import config

router = APIRouter(prefix="/admin/tenants", tags=["admin-tenants"])

def _require_admin(auth_header: str | None) -> None:
    expected = getattr(config, "ADMIN_BEARER", None)
    if not expected or not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if auth_header.split(" ", 1)[1] != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

class UpsertBody(BaseModel):
    slug: str
    name: str = "Default"

@router.post("/seed-default")
def seed_default(authorization: str | None = Header(None),
                 db: Session = Depends(get_session)):
    _require_admin(authorization)
    t = db.exec(select(Tenant).where(Tenant.slug == "default")).first()
    if not t:
        t = Tenant(slug="default", name="Default")
        db.add(t)
        db.commit()
        db.refresh(t)
        return {"ok": True, "created": True, "tenant": t.slug}
    return {"ok": True, "created": False, "tenant": t.slug}

@router.post("/upsert")
def upsert(body: UpsertBody,
           authorization: str | None = Header(None),
           db: Session = Depends(get_session)):
    _require_admin(authorization)
    t = db.exec(select(Tenant).where(Tenant.slug == body.slug)).first()
    if not t:
        t = Tenant(slug=body.slug, name=body.name)
        db.add(t)
    else:
        t.name = body.name or t.name
    db.commit()
    return {"ok": True, "tenant": body.slug}
