# scripts/create_apikey_table.py

import sys
from pathlib import Path

from sqlmodel import SQLModel

# --- Make sure project root is on sys.path ---
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import engine  # now this should work
from app.models import ApiKey  # importing registers the model with metadata


def main() -> None:
    # This will create any missing tables (including ApiKey) and will NOT
    # drop or modify existing data.
    SQLModel.metadata.create_all(engine)
    print("Ensured all tables exist (including ApiKey).")


if __name__ == "__main__":
    main()
