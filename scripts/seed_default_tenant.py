import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select
from app.db import engine
from app.models import Tenant

with Session(engine) as s:
    t = s.exec(select(Tenant).where(Tenant.slug=="default")).first()
    if not t:
        s.add(Tenant(name="Default", slug="default", is_active=True))
        s.commit()
        print("✅ created tenant: default")
    else:
        print("✅ tenant exists:", t.slug)
