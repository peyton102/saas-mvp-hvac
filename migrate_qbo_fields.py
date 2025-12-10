import sys, sqlite3

db_path = r".\app.db"  # <-- CHANGE THIS to your .db path
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Read existing columns
cur.execute("PRAGMA table_info(tenant)")
existing = {row[1] for row in cur.fetchall()}

def add_col(name, sql_type):
    if name not in existing:
        print(f"Adding column {name} {sql_type}")
        cur.execute(f"ALTER TABLE tenant ADD COLUMN {name} {sql_type}")
    else:
        print(f"Column {name} already exists")

add_col("qbo_realm_id", "TEXT")
add_col("qbo_access_token", "TEXT")
add_col("qbo_refresh_token", "TEXT")
add_col("qbo_token_expires_at", "INTEGER")

conn.commit()
conn.close()
print("Done.")
