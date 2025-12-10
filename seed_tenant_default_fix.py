import sqlite3, re, datetime, time
db = "data/app.db"
con = sqlite3.connect(db)
cur = con.cursor()

def base_type(t):
    t = (t or "").upper()
    return re.split(r"\W+", t)[0] if t else ""

TEXT = {"TEXT","VARCHAR","NVARCHAR","CHAR","CLOB"}
NUM  = {"INTEGER","INT","BIGINT","REAL","FLOAT","NUMERIC","DECIMAL"}

# 1) Does a tenant with slug='default' already exist?
row = cur.execute("SELECT rowid,* FROM tenant WHERE slug = ?", ("default",)).fetchone()
if row:
    print("✅ tenant row already exists with slug='default' (reusing):", row[0])
    con.close()
    raise SystemExit(0)

# 2) Build a new row that satisfies NOT NULL constraints
cols = cur.execute("PRAGMA table_info(tenant)").fetchall()
if not cols:
    raise SystemExit("tenant table not found")

now_iso = datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat()
now_epoch = int(time.time())

values = {}
for cid, name, coltype, notnull, dflt, pk in cols:
    bt = base_type(coltype)
    # supply required fields with sane defaults
    if name == "slug":
        values[name] = "default"
    elif dflt is not None:
        # let DB apply its default
        pass
    elif notnull:
        if name in ("created_at","updated_at","createdAt","updatedAt","inserted_at"):
            values[name] = now_iso if (bt in TEXT or bt=="NUMERIC" or bt=="") else now_epoch
        elif bt in TEXT or bt == "":
            values[name] = ""
        elif bt in NUM:
            values[name] = 0
        else:
            values[name] = None

# Ensure at least slug is provided
if "slug" not in values:
    # find any text column to carry 'default'
    for cid, name, coltype, *_ in cols:
        if base_type(coltype) in TEXT or base_type(coltype)=="":
            values[name] = "default"
            break

# Build insert with only the columns we set
names = ",".join(values.keys())
qs    = ",".join([":"+k for k in values.keys()])
sql   = f"INSERT INTO tenant ({names}) VALUES ({qs})"

try:
    cur.execute(sql, values)
    con.commit()
    print("✅ inserted tenant with:", values)
except Exception as e:
    print("❌ insert failed:", e)
finally:
    con.close()
