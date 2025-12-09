import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from app.db import engine

with engine.connect() as conn:
    conn = conn.execution_options(isolation_level="AUTOCOMMIT")
    cols = [r[1] for r in conn.execute(text("PRAGMA table_info(tenant);")).fetchall()]

    if "review_google_url" not in cols:
        conn.execute(text("ALTER TABLE tenant ADD COLUMN review_google_url TEXT DEFAULT '';"))
        print("✅ Added column: review_google_url")
    else:
        print("ℹ️ Column exists: review_google_url")
