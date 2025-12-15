# scripts/backup_sqlite.py
import shutil
import datetime
from pathlib import Path
from datetime import timezone
# ✅ This is your real DB
DB_RELATIVE_PATH = Path("data/app.db")

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / DB_RELATIVE_PATH
BACKUP_DIR = BASE_DIR / "backups"

def backup_sqlite():
    if not DB_PATH.exists():
        raise SystemExit(f"DB file not found at {DB_PATH}")

    BACKUP_DIR.mkdir(exist_ok=True)

    ts = datetime.datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_name = f"app_{ts}.db"
    backup_path = BACKUP_DIR / backup_name

    shutil.copy2(DB_PATH, backup_path)
    print(f"[backup] Created {backup_path}")

    # ✅ Keep only last 14 backups
    MAX_BACKUPS = 14
    backups = sorted(BACKUP_DIR.glob("app_*.db"))
    for old in backups[:-MAX_BACKUPS]:
        print(f"[backup] Deleting old backup {old}")
        old.unlink()

if __name__ == "__main__":
    backup_sqlite()
