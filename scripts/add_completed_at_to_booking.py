# scripts/add_completed_at_to_booking.py

from app.db import engine

def main():
    # Simple one-time migration for local dev:
    # add completed_at column to booking table if it doesn't exist.
    sql = """
    ALTER TABLE booking
    ADD COLUMN completed_at DATETIME
    """
    with engine.connect() as conn:
        try:
            conn.exec_driver_sql(sql)
            print("✅ Added completed_at column to booking table.")
        except Exception as e:
            print(f"⚠️ Migration error (maybe column already exists?): {e}")

if __name__ == "__main__":
    main()
