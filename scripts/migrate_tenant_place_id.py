from sqlalchemy import text
from app.db import engine

with engine.connect() as conn:
    conn = conn.execution_options(isolation_level="AUTOCOMMIT")
    cols = [r[1] for r in conn.execute(text("PRAGMA table_info(tenant);")).fetchall()]

    for col, ddl in [
        ("business_name", "TEXT DEFAULT ''"),
        ("website", "TEXT DEFAULT ''"),
        ("address", "TEXT DEFAULT ''"),
    ]:
        if col not in cols:
            conn.execute(text(f"ALTER TABLE tenant ADD COLUMN {col} {ddl};"))
            print(f"✅ Added column: {col}")
        else:
            print(f"ℹ️ Column exists: {col}")
