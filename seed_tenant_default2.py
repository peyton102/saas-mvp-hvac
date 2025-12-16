import sqlite3, re, time, datetime
from datetime import timezone

db = "data/app.db"
con = sqlite3.connect(db)
cur = con.cursor()

cols = cur.execute("PRAGMA table_info(tenant)").fetchall()
if not cols:
    raise SystemExit("tenant table not found")

# helpers
def base_type(t):
    t = (t or "").upper()
    return re.split(r"\W+", t)[0] if t else ""

text_like = {"TEXT","VARCHAR","NVARCHAR","CHAR","CLOB"}
num_like  = {"INTEGER","INT","BIGINT","REAL","FLOAT","NUMERIC","DECIMAL"}

now_iso = (
    datetime.datetime.now(timezone.utc)
    .replace(microsecond=0)
    .isoformat()
    .replace("+00:00", "Z")
)

now_epoch = int(time.time())

values = {}
identifier_fields = ["id","slug","tenant_id"]
identifier_set = False

for cid, name, coltype, notnull, dflt, pk in cols:
    bt = base_type(coltype)

    # Prefer to put 'default' into a text identifier field
    if not identifier_set and name in identifier_fields and (bt in text_like or bt == ""):
        values[name] = "default"
        identifier_set = True
        continue

    # If column has a default at the DB level, skip and let DB apply it
    if dflt is not None:
        continue

    # If NOT NULL with no default, we must supply something
    if notnull:
        # special cases commonly NOT NULL
        if name in ("created_at","updated_at","createdAt","updatedAt","inserted_at"):
            # store ISO string; SQLite will accept it for TEXT or NUMERIC
            values[name] = now_iso if (bt in text_like or bt in {"NUMERIC",""}) else now_epoch
        elif name in ("business_name","website","address","review_google_url","google_place_id"):
            values[name] = ""
        elif name in ("qbo_access_token","qbo_refresh_token","qbo_realm_id"):
            values[name] = ""
        elif name in ("qbo_token_expires_at",):
            values[name] = 0
        else:
            # generic fallback by type
            values[name] = "" if (bt in text_like or bt=="") else 0

# If we never set an identifier, shove 'default' into first TEXT column
if not identifier_set:
    for cid, name, coltype, notnull, dflt, pk in cols:
        if base_type(coltype) in text_like or base_type(coltype)=="":
            values[name] = "default"
            identifier_set = True
            break

# Build the insert statement including only the columns we decided to set
names = ",".join(values.keys())
qs = ",".join([":"+k for k in values.keys()])
sql = f"INSERT INTO tenant ({names}) VALUES ({qs})"

try:
    cur.execute(sql, values)
    con.commit()
    print("✅ seeded tenant row with:", values)
except Exception as e:
    print("❌ insert failed:", e)
finally:
    con.close()
