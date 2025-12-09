# migrate_tenant_columns.py

from sqlalchemy import text
from app.db import engine  # uses the SAME DB your app uses


# Columns we need on tenant for branding/contact
TARGET_COLUMNS = {
    "email": "TEXT",
    "phone": "TEXT",
    "booking_link": "TEXT",
    "office_sms_to": "TEXT",
    "office_email_to": "TEXT",
}


def get_existing_columns() -> set[str]:
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(tenant);"))
        cols = [row[1] for row in result.fetchall()]  # row[1] = column name
    return set(cols)


def add_missing_columns():
    existing = get_existing_columns()
    print("[INFO] Existing tenant columns:", existing)

    with engine.connect() as conn:
        for col_name, col_type in TARGET_COLUMNS.items():
            if col_name in existing:
                print(f"[SKIP] Column '{col_name}' already exists.")
                continue

            ddl = f"ALTER TABLE tenant ADD COLUMN {col_name} {col_type};"
            print(f"[ADD] {ddl}")
            conn.execute(text(ddl))

        conn.commit()

    print("[DONE] Tenant table aligned for branding/contact columns.")


if __name__ == "__main__":
    add_missing_columns()
