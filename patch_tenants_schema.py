# patch_tenants_schema.py
from app.db import engine

def main():
    with engine.begin() as conn:
        # See what columns already exist
        rows = conn.exec_driver_sql("PRAGMA table_info(tenants)").all()
        existing_cols = {row[1] for row in rows}
        print("Existing columns on tenants:", existing_cols)

        # Columns we need
        needed = {
            "business_name": "TEXT",
            "phone": "TEXT",
            "review_link": "TEXT",
        }

        for col, col_type in needed.items():
            if col in existing_cols:
                print(f"Column {col} already exists, skipping.")
                continue

            stmt = f"ALTER TABLE tenants ADD COLUMN {col} {col_type}"
            print(f"Adding column: {stmt}")
            conn.exec_driver_sql(stmt)

    print("Done patching tenants table.")

if __name__ == "__main__":
    main()
