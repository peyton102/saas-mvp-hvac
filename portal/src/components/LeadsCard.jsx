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

function WonCell({ lead, onSave }) {
  const [entering, setEntering] = useState(false);
  const [val, setVal] = useState("");
  const inputRef = useRef();

  useEffect(() => { if (entering && inputRef.current) inputRef.current.focus(); }, [entering]);

  if (lead.job_won) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
        <span style={{ fontSize: 12, fontWeight: 800, color: C.green }}>
          Won {lead.job_value != null ? `$${Number(lead.job_value).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}` : ""}
        </span>
        <button
          onClick={() => onSave(lead.id, false, null)}
          style={{ fontSize: 10, color: C.muted, background: "none", border: "none", cursor: "pointer", padding: "2px 4px", borderRadius: 4 }}
        >
          undo
        </button>
      </div>
    );
  }

  if (entering) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span style={{ fontSize: 12, color: C.muted }}>$</span>
        <input
          ref={inputRef}
          type="number"
          min="0"
          step="any"
          placeholder="0"
          value={val}
          onChange={e => setVal(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter") { onSave(lead.id, true, val); setEntering(false); setVal(""); }
            if (e.key === "Escape") { setEntering(false); setVal(""); }
          }}
          style={{
            width: 70, padding: "4px 6px", fontSize: 12,
            background: C.inputBg, border: `1px solid ${C.green}`,
            borderRadius: 6, color: C.text, outline: "none",
          }}
        />
        <button
          onClick={() => { onSave(lead.id, true, val); setEntering(false); setVal(""); }}
          style={{ fontSize: 11, fontWeight: 700, padding: "4px 8px", borderRadius: 6, border: "none", background: C.greenBg, color: C.green, cursor: "pointer" }}
        >
          Save
        </button>
        <button
          onClick={() => { setEntering(false); setVal(""); }}
          style={{ fontSize: 11, padding: "4px 6px", borderRadius: 6, border: "none", background: "transparent", color: C.muted, cursor: "pointer" }}
        >
          ✕
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => setEntering(true)}
      style={{
        padding: "5px 10px", borderRadius: 8, fontSize: 11, fontWeight: 700,
        cursor: "pointer", border: "none", whiteSpace: "nowrap",
        background: "rgba(74,222,128,0.08)", color: "rgba(74,222,128,0.55)",
        transition: "all 0.15s",
      }}
      onMouseEnter={e => { e.currentTarget.style.background = C.greenBg; e.currentTarget.style.color = C.green; }}
      onMouseLeave={e => { e.currentTarget.style.background = "rgba(74,222,128,0.08)"; e.currentTarget.style.color = "rgba(74,222,128,0.55)"; }}
    >
      Mark Won
    </button>
  );
}

function nextHourTime() {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return `${String(d.getHours()).padStart(2, "0")}:00`;
}

function todayLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function ConvertToBookingModal({ lead, onSave, onClose }) {
  const [date,     setDate]     = useState(todayLocal());
  const [time,     setTime]     = useState(nextHourTime());
  const [duration, setDuration] = useState("60");
  const [notes,    setNotes]    = useState("");
  const [saving,   setSaving]   = useState(false);
  const [err,      setErr]      = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    setErr("");
    const startMs = new Date(`${date}T${time}:00`).getTime();
    const endMs   = startMs + parseInt(duration, 10) * 60 * 1000;
    const endDate = new Date(endMs);
    const pad = n => String(n).padStart(2, "0");
    const start = `${date}T${time}:00`;
    const end   = `${endDate.getFullYear()}-${pad(endDate.getMonth()+1)}-${pad(endDate.getDate())}T${pad(endDate.getHours())}:${pad(endDate.getMinutes())}:00`;
    try {
      await onSave({ name: lead.name, phone: lead.phone, email: lead.email || null, notes: notes.trim() || null, start, end });
    } catch (e) {
      setErr(String(e.message || e));
      setSaving(false);
    }
  }

  const field = {
    padding: "9px 12px", fontSize: 14, borderRadius: 8,
    border: "1px solid rgba(255,255,255,0.12)", background: C.inputBg,
    color: C.text, outline: "none", width: "100%",
  };

  return (
    <div
      onClick={e => e.target === e.currentTarget && onClose()}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.65)",
        zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
      }}
    >
      <div style={{
        background: "#0f172a", border: "1px solid rgba(249,115,22,0.3)", borderRadius: 18,
        padding: 28, maxWidth: 480, width: "100%", display: "grid", gap: 14,
      }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 900, color: C.text, marginBottom: 4 }}>Convert to Booking</div>
          <div style={{ fontSize: 13, color: C.muted }}>
            {lead.name || "—"} · {lead.phone}
            {lead.message ? <span> · <em>{lead.message}</em></span> : null}
          </div>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <input type="date" value={date} onChange={e => setDate(e.target.value)} style={{ ...field, colorScheme: "dark" }} required />
            <input type="time" value={time} onChange={e => setTime(e.target.value)} style={{ ...field, colorScheme: "dark" }} required />
          </div>
          <select value={duration} onChange={e => setDuration(e.target.value)} style={{ ...field, cursor: "pointer" }}>
            <option value="30">30 min</option>
            <option value="60">1 hour</option>
            <option value="90">1.5 hours</option>
            <option value="120">2 hours</option>
          </select>
          <input placeholder="Notes (optional)" value={notes} onChange={e => setNotes(e.target.value)} style={field} />

          {err && <div style={{ fontSize: 12, color: "#fca5a5" }}>{err}</div>}

          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" onClick={onClose} style={{
              padding: "9px 16px", borderRadius: 8, fontWeight: 700, fontSize: 13,
              border: "1px solid rgba(255,255,255,0.12)", background: "transparent", color: C.muted, cursor: "pointer",
            }}>
              Cancel
            </button>
            <button type="submit" disabled={saving} style={{
              padding: "9px 22px", borderRadius: 8, border: "none", fontWeight: 800, fontSize: 13,
              background: C.accent, color: "#111", cursor: saving ? "not-allowed" : "pointer", opacity: saving ? 0.6 : 1,
            }}>
              {saving ? "Booking…" : "Book It"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function AddLeadForm({ onSave, onCancel }) {
  const [name, setName]       = useState("");
  const [phone, setPhone]     = useState("");
  const [message, setMessage] = useState("");
  const [autoReply, setAutoReply] = useState(false);
  const [saving, setSaving]   = useState(false);
  const [err, setErr]         = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!phone.trim()) { setErr("Phone is required."); return; }
    setSaving(true);
    setErr("");
    try {
      await onSave({ name: name.trim(), phone: phone.trim(), message: message.trim(), send_auto_reply: autoReply, manual_entry: true });
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  const field = {
    padding: "9px 12px", fontSize: 14, borderRadius: 8,
    border: "1px solid rgba(255,255,255,0.12)", background: C.inputBg,
    color: C.text, outline: "none", width: "100%",
  };

  return (
    <form onSubmit={handleSubmit} style={{
      padding: "16px", marginBottom: 16, borderRadius: 12,
      border: "1px solid rgba(249,115,22,0.25)", background: "rgba(249,115,22,0.04)",
      display: "grid", gap: 10,
    }}>
      <div style={{ fontSize: 14, fontWeight: 800, color: C.text, marginBottom: 2 }}>Add Lead</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <input placeholder="Name (optional)" value={name} onChange={e => setName(e.target.value)} style={field} />
        <input placeholder="Phone *" value={phone} onChange={e => setPhone(e.target.value)} style={field} required />
      </div>
      <input placeholder="Issue / message (optional)" value={message} onChange={e => setMessage(e.target.value)} style={field} />
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: C.muted, cursor: "pointer" }}>
        <input type="checkbox" checked={autoReply} onChange={e => setAutoReply(e.target.checked)} style={{ accentColor: C.accent }} />
        Send auto-reply SMS to customer
      </label>
      {err && <div style={{ fontSize: 12, color: "#fca5a5" }}>{err}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button type="submit" disabled={saving} style={{
          padding: "9px 20px", borderRadius: 8, border: "none", fontWeight: 800, fontSize: 13,
          background: C.accent, color: "#111", cursor: saving ? "not-allowed" : "pointer", opacity: saving ? 0.6 : 1,
        }}>
          {saving ? "Saving…" : "Add Lead"}
        </button>
        <button type="button" onClick={onCancel} style={{
          padding: "9px 16px", borderRadius: 8, fontWeight: 700, fontSize: 13,
          border: "1px solid rgba(255,255,255,0.12)", background: "transparent", color: C.muted, cursor: "pointer",
        }}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function LeadsCard({ tenantKey, apiBase, commonHeaders }) {
  const BASE = (typeof apiBase === "string" && apiBase.trim()) ? apiBase : BASE_FALLBACK;

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState({ col: "created_at", dir: "desc" });
  const [showAll, setShowAll] = useState(false);
  const [showAddForm, setShowAddForm]     = useState(false);
  const [convertingLead, setConvertingLead] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

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

  async function convertToBooking(lead, bookingPayload) {
    await apiFetch("/book", { method: "POST", body: JSON.stringify(bookingPayload) });
    // mark lead as contacted so it dims in the list
    await apiFetch(`/leads/${lead.id}/status`, { method: "PATCH", body: JSON.stringify({ status: "contacted" }) });
    setRows(prev => prev.map(r => r.id === lead.id ? { ...r, status: "contacted" } : r));
    setConvertingLead(null);
  }

  async function addLead(payload) {
    await apiFetch("/lead", { method: "POST", body: JSON.stringify(payload) });
    setShowAddForm(false);
    loadLeads();
  }

  async function saveWon(id, won, value) {
    try {
      const body = { job_won: won, job_value: won && value !== "" && value != null ? parseFloat(value) : null };
      await apiFetch(`/leads/${id}/won`, { method: "PATCH", body: JSON.stringify(body) });
      setRows(prev => prev.map(r => r.id === id ? { ...r, job_won: won, job_value: body.job_value } : r));
    } catch (e) { console.error(e); }
  }

  async function saveNotes(id, notes) {
    try {
      await apiFetch(`/leads/${id}/notes`, { method: "PATCH", body: JSON.stringify({ notes }) });
      setRows(prev => prev.map(r => r.id === id ? { ...r, notes } : r));
    } catch (e) { console.error(e); }
  }

  async function deleteLead(id) {
    setDeletingId(id);
    try {
      await apiFetch(`/leads/${id}`, { method: "DELETE" });
      setRows(prev => prev.filter(r => r.id !== id));
    } catch (e) { console.error(e); } finally {
      setDeletingId(null);
    }
  }

  const cutoff = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return d;
  }, []);

  const visible = useMemo(() => {
    const q = search.toLowerCase().trim();
    let list = showAll ? [...rows] : rows.filter(r => {
      const d = parseISO(r.created_at);
      return d && d >= cutoff;
    });
    if (q) list = list.filter(r =>
      (r.name || "").toLowerCase().includes(q) ||
      (r.phone || "").toLowerCase().includes(q) ||
      (r.email || "").toLowerCase().includes(q) ||
      (r.message || "").toLowerCase().includes(q) ||
      (r.service_address || "").toLowerCase().includes(q) ||
      (r.notes || "").toLowerCase().includes(q)
    );

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
  }, [rows, search, sort, showAll, cutoff]);

  const cols = [
    { key: "created_at", label: "Time Received", w: "120px" },
    { key: "name",       label: "Name",          w: "130px" },
    { key: "phone",      label: "Phone",          w: "120px" },
    { key: "email",      label: "Email",          w: "160px" },
    { key: "message",         label: "Issue",          w: "180px" },
    { key: "service_address", label: "Address",        w: "150px" },
    { key: "service_urgency", label: "Preferred Day",  w: "110px" },
    { key: "notes",      label: "Notes",          w: "160px" },
    { key: "status",     label: "Contacted",      w: "90px"  },
    { key: "job_won",    label: "Won",            w: "120px" },
    { key: "_delete",    label: "",               w: "40px", noSort: true },
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

      {convertingLead && (
        <ConvertToBookingModal
          lead={convertingLead}
          onSave={(payload) => convertToBooking(convertingLead, payload)}
          onClose={() => setConvertingLead(null)}
        />
      )}

      {/* Header row */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 10 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>Leads</div>
          <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
            {visible.length} lead{visible.length !== 1 ? "s" : ""}
            {!showAll && rows.length > visible.length && (
              <span style={{ marginLeft: 6 }}>
                · <button onClick={() => setShowAll(true)} style={{ background: "none", border: "none", color: C.accent, cursor: "pointer", fontSize: 12, padding: 0 }}>
                  +{rows.length - visible.length} older
                </button>
              </span>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            type="text"
            placeholder="Search name, phone, issue, notes…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              padding: "9px 14px", borderRadius: 10, fontSize: 13,
              background: C.inputBg, border: C.border, color: C.text,
              outline: "none", width: "min(240px, 100%)",
            }}
          />
          <button
            onClick={() => setShowAll(v => !v)}
            style={{
              padding: "9px 14px", borderRadius: 10, fontWeight: 700, fontSize: 13,
              border: C.border, background: showAll ? "rgba(249,115,22,0.12)" : C.inputBg,
              color: showAll ? C.accent : C.muted, cursor: "pointer", whiteSpace: "nowrap",
            }}
          >
            {showAll ? "Last 7 days" : "All time"}
          </button>
          <button
            onClick={() => setShowAddForm(v => !v)}
            style={{
              padding: "9px 16px", borderRadius: 10, fontWeight: 800, fontSize: 13,
              border: "none", background: C.accent, color: "#111", cursor: "pointer", whiteSpace: "nowrap",
            }}
          >
            + Add Lead
          </button>
        </div>
      </div>

      {showAddForm && (
        <AddLeadForm onSave={addLead} onCancel={() => setShowAddForm(false)} />
      )}

      {/* Table — max-height keeps the scrollbar in view without scrolling the whole page */}
      <div className="table-scroll-wrap" style={{ overflowX: "auto", overflowY: "auto", maxHeight: "65vh", borderRadius: 12, border: C.border }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 640 }}>
          <thead>
            <tr style={{ background: "rgba(255,255,255,0.03)" }}>
              {cols.map(c => (
                <th
                  key={c.key}
                  style={{ ...thStyle(c.key), width: c.w, minWidth: c.w }}
                  onClick={() => !c.noSort && c.key !== "notes" && toggleSort(c.key)}
                >
                  {c.label}{" "}
                  {!c.noSort && c.key !== "notes" && <SortIcon dir={sort.col === c.key ? sort.dir : null} />}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={11} style={{ padding: 24, textAlign: "center", color: C.muted }}>Loading…</td></tr>
            )}
            {!loading && visible.length === 0 && (
              <tr><td colSpan={11} style={{ padding: 24, textAlign: "center", color: C.muted }}>No leads found.</td></tr>
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
                  <td style={{ padding: "10px 10px", fontWeight: 600 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
                      <span style={{ whiteSpace: "nowrap" }}>{r.name || "—"}</span>
                      {r.needs_verification && (
                        <span title="Unconfirmed — caller hung up before confirming" style={{ fontSize: 12, color: "#fbbf24" }}>⚠</span>
                      )}
                      {r.customer_type && (
                        <span style={{
                          fontSize: 10, fontWeight: 700, padding: "1px 5px", borderRadius: 4,
                          background: r.customer_type === "new" ? "rgba(96,165,250,0.15)" : "rgba(167,139,250,0.15)",
                          color: r.customer_type === "new" ? "#60a5fa" : "#a78bfa",
                          whiteSpace: "nowrap",
                        }}>{r.customer_type}</span>
                      )}
                      {r.property_type && (
                        <span style={{
                          fontSize: 10, fontWeight: 700, padding: "1px 5px", borderRadius: 4,
                          background: r.property_type === "residential" ? "rgba(52,211,153,0.15)" : "rgba(251,191,36,0.15)",
                          color: r.property_type === "residential" ? "#34d399" : "#fbbf24",
                          whiteSpace: "nowrap",
                        }}>{r.property_type}</span>
                      )}
                    </div>
                  </td>

                  {/* Phone */}
                  <td style={{ padding: "10px 10px", whiteSpace: "nowrap" }}>
                    <a href={`tel:${r.phone}`} style={{ color: C.accent, textDecoration: "none", fontWeight: 600 }}>
                      {r.phone || "—"}
                    </a>
                  </td>

                  {/* Email */}
                  <td style={{ padding: "10px 10px", fontSize: 12 }}>
                    <div style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.email || ""}>
                      {r.email
                        ? <a href={`mailto:${r.email}`} style={{ color: C.muted, textDecoration: "none" }}>{r.email}</a>
                        : <span style={{ color: C.muted }}>—</span>
                      }
                    </div>
                  </td>

                  {/* Issue */}
                  <td style={{ padding: "10px 10px", color: C.text }}>
                    <div style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.message || ""}>
                      {r.message || "—"}
                    </div>
                  </td>

                  {/* Address */}
                  <td style={{ padding: "10px 10px", color: C.text, fontSize: 12 }}>
                    <div style={{ maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.service_address || ""}>
                      {r.service_address || "—"}
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

                  {/* Contacted + Book */}
                  <td style={{ padding: "10px 10px", textAlign: "center" }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 5, alignItems: "center" }}>
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
                      <button
                        onClick={() => setConvertingLead(r)}
                        style={{
                          padding: "4px 10px", borderRadius: 8, fontSize: 11, fontWeight: 700,
                          cursor: "pointer", border: "none", whiteSpace: "nowrap",
                          background: "rgba(96,165,250,0.12)", color: "#60a5fa",
                        }}
                      >
                        Book
                      </button>
                    </div>
                  </td>

                  {/* Won toggle */}
                  <td style={{ padding: "10px 10px" }}>
                    <WonCell lead={r} onSave={saveWon} />
                  </td>

                  {/* Delete */}
                  <td style={{ padding: "10px 6px", textAlign: "center" }}>
                    <button
                      onClick={() => deletingId !== r.id && deleteLead(r.id)}
                      title="Delete lead"
                      style={{
                        background: "none", border: "none", cursor: deletingId === r.id ? "not-allowed" : "pointer",
                        color: deletingId === r.id ? C.muted : "rgba(239,68,68,0.5)",
                        fontSize: 14, lineHeight: 1, padding: "4px 6px", borderRadius: 6,
                        transition: "color 0.15s",
                      }}
                      onMouseEnter={e => { if (deletingId !== r.id) e.currentTarget.style.color = "#ef4444"; }}
                      onMouseLeave={e => { e.currentTarget.style.color = deletingId === r.id ? C.muted : "rgba(239,68,68,0.5)"; }}
                    >
                      {deletingId === r.id ? "…" : "✕"}
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
