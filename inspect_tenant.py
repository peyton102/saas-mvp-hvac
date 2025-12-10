import sqlite3, json
db = "data/app.db"
con = sqlite3.connect(db)
cur = con.cursor()

print("== create SQL ==")
row = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tenant'").fetchone()
print(row[0] if row else "tenant table not found")

print("\n== columns ==")
cols = cur.execute("PRAGMA table_info(tenant)").fetchall()
# each: (cid, name, type, notnull, dflt_value, pk)
for c in cols:
    print(c)

print("\n== current rows (first 5) ==")
rows = cur.execute("SELECT * FROM tenant LIMIT 5").fetchall()
print(rows)

con.close()
