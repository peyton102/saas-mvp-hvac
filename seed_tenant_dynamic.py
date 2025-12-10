import sqlite3, re, time
db = "data/app.db"
con = sqlite3.connect(db)
cur = con.cursor()

cols = cur.execute("PRAGMA table_info(tenant)").fetchall()
if not cols:
    raise SystemExit("tenant table not found")

# Build an insert dict with safe defaults
values = {}
text_like = {"TEXT", "VARCHAR", "NVARCHAR", "CHAR", "CLOB"}
num_like  = {"INTEGER", "INT", "BIGINT", "REAL", "FLOAT", "NUMERIC", "DECIMAL"}

# Prefer a human key field to carry 'default'
identifier_fields = ["id", "slug", "tenant_id"]
identifier_assigned = False

for cid, name, coltype, notnull, dflt, pk in cols:
    t = (coltype or "").upper()
    base_t = re.split(r"\W+", t)[0] if t else ""  # strip sizes like VARCHAR(64) -> VARCHAR

    # Choose value
    if name in identifier_fields and (base_t in text_like or base_t == ""):
        values[name] = "default"
        identifier_assigned = True
    elif dflt is not None:
        values[name] = dflt
    else:
        if base_t in text_like or base_t == "":
            values[name] = ""
        elif base_t in num_like:
            values[name] = 0
        else:
            values[name] = None  # hope it's nullable

# If no text identifier field existed, try to stuff 'default' into first TEXT column
if not identifier_assigned:
    for cid, name, coltype, notnull, dflt, pk in cols:
        base_t = re.split(r"\W+", (coltype or "").upper())[0] if coltype else ""
        if base_t in text_like:
            values[name] = "default"
            identifier_assigned = True
            break

# Build SQL
names = ",".join(values.keys())
qs = ",".join([":" + k for k in values.keys()])
sql = f"INSERT INTO tenant ({names}) VALUES ({qs})"

try:
    cur.execute(sql, values)
    con.commit()
    print("seeded tenant row with:", values)
except Exception as e:
    print("insert failed:", e)
finally:
    con.close()
