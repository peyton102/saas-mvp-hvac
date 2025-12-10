from sqlmodel import Session, select
from app.db import engine
from app.models import Tenant
import os, time

def find_tenant(session, key):
    t = session.exec(select(Tenant).where(Tenant.id == key)).first()
    if not t and hasattr(Tenant, "slug"):
        t = session.exec(select(Tenant).where(Tenant.slug == key)).first()
    if not t and hasattr(Tenant, "tenant_id"):
        t = session.exec(select(Tenant).where(Tenant.tenant_id == key)).first()
    return t

acc   = os.getenv("QBO_ACCESS_TOKEN", "")
ref   = os.getenv("QBO_REFRESH_TOKEN", "")
realm = os.getenv("QBO_REALM_ID", "")
exp   = int(time.time()) + 3500

if not (acc and ref and realm):
    raise SystemExit("Missing QBO_ACCESS_TOKEN / QBO_REFRESH_TOKEN / QBO_REALM_ID in env")

with Session(engine) as s:
    t = find_tenant(s, "default")
    if not t:
        raise SystemExit("Tenant 'default' not found")
    if hasattr(t, "qbo_access_token"):       t.qbo_access_token = acc
    if hasattr(t, "qbo_refresh_token"):      t.qbo_refresh_token = ref
    if hasattr(t, "qbo_realm_id"):           t.qbo_realm_id = realm
    if hasattr(t, "qbo_token_expires_at"):   t.qbo_token_expires_at = exp
    s.add(t); s.commit()
    print("✅ wrote tokens for tenant:", getattr(t, "slug", "default"))
