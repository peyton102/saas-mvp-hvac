from sqlmodel import Session, select
from sqlalchemy import text
from app.db import engine
from app.models import Tenant

with Session(engine) as s:
    t = s.exec(select(Tenant).where(Tenant.id == "default")).first()
    if not t:
        s.exec(text("INSERT OR IGNORE INTO tenant (id) VALUES ('default')"))
        s.commit()
print("tenant ok")
