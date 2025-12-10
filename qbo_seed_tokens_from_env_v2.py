from sqlmodel import Session, select
from app.db import engine
from app.models import Tenant
from dotenv import dotenv_values
import time, sys

cfg = dotenv_values(".env")  # read tokens from the .env file (not process env)

AT    = (cfg.get("QBO_ACCESS_TOKEN")  or "").strip()
RT    = (cfg.get("QBO_REFRESH_TOKEN") or "").strip()
REALM = (cfg.get("QBO_REALM_ID")      or "").strip()

if not (AT and RT and REALM):
    sys.exit("Missing QBO_ACCESS_TOKEN / QBO_REFRESH_TOKEN / QBO_REALM_ID in .env")

def find_tenant(session, key):
    t = session.exec(select(Tenant).where(Tenant.id == key)).first()
    if not t and hasattr(Tenant, "slug"):
        t = session.exec(select(Tenant).where(Tenant.slug == key)).first()
    if not t and hasattr(Tenant, "tenant_id"):
        t = session.exec(select(Tenant).where(Tenant.tenant_id == key)).first()
    return t

with Session(engine) as s:
    t = find_tenant(s, "default")
    if not t:
        sys.exit("Tenant 'default' not found — create it first")
    if hasattr(t, "qbo_access_token"):     t.qbo_access_token = AT
    if hasattr(t, "qbo_refresh_token"):    t.qbo_refresh_token = RT
    if hasattr(t, "qbo_realm_id"):         t.qbo_realm_id = REALM
    if hasattr(t, "qbo_token_expires_at"): t.qbo_token_expires_at = int(time.time()) + 3500
    s.add(t); s.commit()
    print("✅ wrote tokens for tenant:", getattr(t, "slug", getattr(t, "id", "default")))
