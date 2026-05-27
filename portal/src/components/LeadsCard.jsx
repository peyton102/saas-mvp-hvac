// FILE: portal/src/components/LeadsCard.jsx
import { useEffect, useMemo, useState, useCallback, useRef } from "react";

const BASE_FALLBACK = "/api";

function parseISO(iso) {
  if (!iso) return null;
  const s = /[zZ]$|[+\-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(s);
  return isNaN(d) ? null : d;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = parseISO(iso);
  if (!d) return iso;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

const C = {
  bg: "transparent",
  border: "1px solid rgba(255,255,255,0.08)",
  text: "#e5e7eb",
  muted: "rgba(229,231,235,0.5)",
  accent: "#f97316",
  rowEven: "rgba(255,255,255,0.02)",
  rowHover: "rgba(249,115,22,0.06)",
  inputBg: "rgba(255,255,255,0.06)",
  green: "#4ade80",
  greenBg: "rgba(74,222,128,0.12)",
};

function SortIcon({ dir }) {
  if (!dir) return <span style={{ color: C.muted, fontSize: 10 }}>↕</span>;
  return <span style={{ color: C.accent, fontSize: 10 }}>{dir === "asc" ? "↑" : "↓"}</span>;
}

function NotesCell({ lead, onSave }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(lead.notes || "");
  const ref = useRef();

  useEffect(() => { setVal(lead.notes || ""); }, [lead.notes]);

  function handleBlur() {
    setEditing(false);
    if (val !== (lead.notes || "")) onSave(lead.id, val);
  }

  if (editing) {
    return (
      <textarea
        ref={ref}
        value={val}
        onChange={e => setVal(e.target.value)}
        onBlur={handleBlur}
        autoFocus
        rows={2}
        style={{
          width: "100%", minWidth: 120,
          background: C.inputBg, color: C.text,
          border: `1px solid ${C.accent}`, borderRadius: 6,
          padding: "4px 6px", fontSize: 12, resize: "vertical",
          fontFamily: "inherit",
        }}
      />
    );
  }

  return (
    <div
      onClick={() => setEditing(true)}
      title="Click to edit"
      style={{
        minHeight: 28, padding: "4px 6px", borderRadius: 6, cursor: "text",
        border: "1px solid transparent", color: val ? C.text : C.muted,
        fontSize: 12, whiteSpace: "pre-wrap", wordBreak: "break-word",
        transition: "border-color 0.15s",
      }}
      onMouseEnter={e => e.currentTarget.style.borderColor = "rgba(249,115,22,0.4)"}
      onMouseLeave={e => e.currentTarget.style.borderColor = "transparent"}
    >
      {val || "Add note…"}
    </div>
  );
}

export default function LeadsCard({ tenantKey, apiBase, commonHeaders }) {
  const BASE = (typeof apiBase === "string" && apiBase.trim()) ? apiBase : BASE_FALLBACK;

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState({ col: "created_at", dir: "desc" });

  const headers = useMemo(() => ({
    ...(commonHeaders || {}),
    "ngrok-skip-browser-warning": "true",
    "Content-Type": "application/json",
  }), [commonHeaders]);

  async function apiFetch(path, opts = {}) {
    const res = await fetch(`${BASE}${path}`, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
    if (res.status === 204) return null;
    const txt = await res.text().catch(() => "");
    let data = null;
    try { data = txt ? JSON.parse(txt) : null; } catch {}
    if (!res.ok) throw new Error((data?.detail) || txt || `HTTP ${res.status}`);
    return data;
  }

  const loadLeads = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch("/leads?limit=200");
      setRows(data.items || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [headers, BASE]);

  useEffect(() => { loadLeads(); }, [tenantKey, BASE, loadLeads]);

  function toggleSort(col) {
    setSort(s => s.col === col
      ? { col, dir: s.dir === "desc" ? "asc" : "desc" }
      : { col, dir: col === "created_at" ? "desc" : "asc" }
    );
  }

  async function toggleContacted(id, current) {
    const next = (current || "").toLowerCase() === "contacted" ? "new" : "contacted";
    try {
      await apiFetch(`/leads/${id}/status`, { method: "PATCH", body: JSON.stringify({ status: next }) });
      setRows(prev => prev.map(r => r.id === id ? { ...r, status: next } : r));
    } catch (e) { console.error(e); }
  }

  async function saveNotes(id, notes) {
    try {
      await apiFetch(`/leads/${id}/notes`, { method: "PATCH", body: JSON.stringify({ notes }) });
      setRows(prev => prev.map(r => r.id === id ? { ...r, notes } : r));
    } catch (e) { console.error(e); }
  }

  const visible = useMemo(() => {
    const q = search.toLowerCase().trim();
    let list = q ? rows.filter(r =>
      (r.name || "").toLowerCase().includes(q) ||
      (r.phone || "").toLowerCase().includes(q) ||
      (r.message || "").toLowerCase().includes(q) ||
      (r.notes || "").toLowerCase().includes(q)
    ) : [...rows];

    list.sort((a, b) => {
      let av = a[sort.col] ?? "";
      let bv = b[sort.col] ?? "";
      if (sort.col === "created_at") {
        av = parseISO(av) || 0;
        bv = parseISO(bv) || 0;
      } else {
        av = String(av).toLowerCase();
        bv = String(bv).toLowerCase();
      }
      if (av < bv) return sort.dir === "asc" ? -1 : 1;
      if (av > bv) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });

    return list;
  }, [rows, search, sort]);

  const cols = [
    { key: "created_at", label: "Time Received", w: "120px" },
    { key: "name",       label: "Name",          w: "110px" },
    { key: "phone",      label: "Phone",          w: "120px" },
    { key: "message",    label: "Issue",          w: "180px" },
    { key: "service_urgency", label: "Preferred Day", w: "110px" },
    { key: "notes",      label: "Notes",          w: "160px" },
    { key: "status",     label: "Contacted",      w: "90px"  },
  ];

  const thStyle = (key) => ({
    padding: "10px 10px",
    textAlign: "left",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: 0.5,
    color: C.muted,
    textTransform: "uppercase",
    borderBottom: C.border,
    cursor: "pointer",
    whiteSpace: "nowrap",
    userSelect: "none",
  });

  return (
    <div style={{ color: C.text, fontFamily: "system-ui, -apple-system, sans-serif" }}>

      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>Leads</div>
          <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>{visible.length} lead{visible.length !== 1 ? "s" : ""}</div>
        </div>
        <input
          type="text"
          placeholder="Search name, phone, issue, notes…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            padding: "9px 14px", borderRadius: 10, fontSize: 13,
            background: C.inputBg, border: C.border, color: C.text,
            outline: "none", width: "min(280px, 100%)",
          }}
        />
      </div>

      {/* Table — horizontal scroll on mobile */}
      <div style={{ overflowX: "auto", borderRadius: 12, border: C.border }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 640 }}>
          <thead>
            <tr style={{ background: "rgba(255,255,255,0.03)" }}>
              {cols.map(c => (
                <th
                  key={c.key}
                  style={{ ...thStyle(c.key), width: c.w, minWidth: c.w }}
                  onClick={() => c.key !== "notes" && toggleSort(c.key)}
                >
                  {c.label}{" "}
                  {c.key !== "notes" && <SortIcon dir={sort.col === c.key ? sort.dir : null} />}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={7} style={{ padding: 24, textAlign: "center", color: C.muted }}>Loading…</td></tr>
            )}
            {!loading && visible.length === 0 && (
              <tr><td colSpan={7} style={{ padding: 24, textAlign: "center", color: C.muted }}>No leads found.</td></tr>
            )}
            {!loading && visible.map((r, i) => {
              const contacted = (r.status || "").toLowerCase() === "contacted";
              return (
                <tr
                  key={r.id}
                  style={{
                    background: i % 2 === 0 ? "transparent" : C.rowEven,
                    borderBottom: "1px solid rgba(255,255,255,0.04)",
                    opacity: contacted ? 0.65 : 1,
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = C.rowHover}
                  onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? "transparent" : C.rowEven}
                >
                  {/* Time */}
                  <td style={{ padding: "10px 10px", color: C.muted, fontSize: 12, whiteSpace: "nowrap" }}>
                    {formatDate(r.created_at)}
                  </td>

                  {/* Name */}
                  <td style={{ padding: "10px 10px", fontWeight: 600, whiteSpace: "nowrap" }}>
                    {r.name || "—"}
                  </td>

                  {/* Phone */}
                  <td style={{ padding: "10px 10px", whiteSpace: "nowrap" }}>
                    <a href={`tel:${r.phone}`} style={{ color: C.accent, textDecoration: "none", fontWeight: 600 }}>
                      {r.phone || "—"}
                    </a>
                  </td>

                  {/* Issue */}
                  <td style={{ padding: "10px 10px", color: C.text }}>
                    <div style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.message || ""}>
                      {r.message || "—"}
                    </div>
                  </td>

                  {/* Timing */}
                  <td style={{ padding: "10px 10px", color: C.muted, fontSize: 12, whiteSpace: "nowrap" }}>
                    {r.service_urgency || "—"}
                  </td>

                  {/* Notes */}
                  <td style={{ padding: "6px 10px" }}>
                    <NotesCell lead={r} onSave={saveNotes} />
                  </td>

                  {/* Contacted toggle */}
                  <td style={{ padding: "10px 10px", textAlign: "center" }}>
                    <button
                      onClick={() => toggleContacted(r.id, r.status)}
                      style={{
                        padding: "5px 10px", borderRadius: 8, fontSize: 11, fontWeight: 700,
                        cursor: "pointer", border: "none", whiteSpace: "nowrap",
                        background: contacted ? C.greenBg : "rgba(249,115,22,0.12)",
                        color: contacted ? C.green : C.accent,
                        transition: "all 0.15s",
                      }}
                    >
                      {contacted ? "✓ Done" : "Mark Done"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
