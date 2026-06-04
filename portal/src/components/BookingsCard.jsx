// FILE: portal/src/components/BookingsCard.jsx
import { useCallback, useEffect, useMemo, useState } from "react";

// ── colour tokens — matches LeadsCard exactly ──────────────────────────────
const C = {
  bg:       "transparent",
  border:   "1px solid rgba(255,255,255,0.08)",
  text:     "#e5e7eb",
  muted:    "rgba(229,231,235,0.5)",
  accent:   "#f97316",
  rowEven:  "rgba(255,255,255,0.02)",
  rowHover: "rgba(249,115,22,0.06)",
  inputBg:  "rgba(255,255,255,0.06)",
  green:    "#4ade80",
  greenBg:  "rgba(74,222,128,0.12)",
  blue:     "#60a5fa",
  blueBg:   "rgba(59,130,246,0.12)",
};

// ── helpers ─────────────────────────────────────────────────────────────────

function parseISO(iso) {
  if (!iso) return null;
  const s = /[zZ]$|[+\-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(s);
  return isNaN(d) ? null : d;
}

function formatBookingTime(iso) {
  if (!iso) return "—";
  const d = parseISO(iso);
  if (!d) return String(iso);
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    month:    "short",
    day:      "numeric",
    hour:     "numeric",
    minute:   "2-digit",
    hour12:   true,
  }).format(d);
}

function normalizeRow(r, i) {
  return {
    id:         r.id ?? `row-${i}`,
    name:       r.name       || "",
    email:      r.email      || "",
    phone:      r.phone      || "",
    notes:      r.notes || r.note || "",
    source:     r.source     || "",
    starts_at:  r.start || r.starts_at || r.starts_at_iso || null,
    created_at: r.created_at || null,
    completed:  Boolean(r.completed_at || r.completed),
  };
}

// ── sub-components ───────────────────────────────────────────────────────────

function SortIcon({ dir }) {
  if (!dir) return <span style={{ color: C.muted, fontSize: 10 }}>↕</span>;
  return <span style={{ color: C.accent, fontSize: 10 }}>{dir === "asc" ? "↑" : "↓"}</span>;
}

function SourceBadge({ source }) {
  const s = (source || "").toLowerCase();

  if (s === "google_calendar") {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 600,
        background: C.blueBg, color: C.blue, whiteSpace: "nowrap",
      }}>
        📅 Google Cal
      </span>
    );
  }

  if (s === "vapi" || s === "missed_call") {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 600,
        background: "rgba(249,115,22,0.15)", color: "#fb923c", whiteSpace: "nowrap",
      }}>
        📞 {s === "vapi" ? "Vapi" : "Missed Call"}
      </span>
    );
  }

  if (s === "calendly") {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 600,
        background: "rgba(139,92,246,0.15)", color: "#a78bfa", whiteSpace: "nowrap",
      }}>
        🗓 Calendly
      </span>
    );
  }

  return (
    <span style={{
      padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 600,
      background: "rgba(255,255,255,0.08)", color: C.muted, whiteSpace: "nowrap",
    }}>
      Manual
    </span>
  );
}

function StatusBadge({ row }) {
  if (row.completed) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 600,
        background: C.greenBg, color: C.green,
      }}>
        ✓ Done
      </span>
    );
  }
  const isPast = row.starts_at && parseISO(row.starts_at) < new Date();
  if (isPast) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 600,
        background: "rgba(255,255,255,0.05)", color: "rgba(229,231,235,0.35)",
      }}>
        Past
      </span>
    );
  }
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 9999, fontSize: 11, fontWeight: 600,
      background: C.blueBg, color: C.blue,
    }}>
      Upcoming
    </span>
  );
}

// ── Add Booking form ─────────────────────────────────────────────────────────

function todayLocal() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function nextHourTime() {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return `${String(d.getHours()).padStart(2, "0")}:00`;
}

function AddBookingForm({ onSave, onCancel }) {
  const [name,     setName]     = useState("");
  const [phone,    setPhone]    = useState("");
  const [email,    setEmail]    = useState("");
  const [date,     setDate]     = useState(todayLocal());
  const [time,     setTime]     = useState(nextHourTime());
  const [duration, setDuration] = useState("60");
  const [notes,    setNotes]    = useState("");
  const [saving,   setSaving]   = useState(false);
  const [err,      setErr]      = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim()) { setErr("Name is required."); return; }
    if (!date || !time) { setErr("Date and time are required."); return; }

    // Build start/end ISO strings (naive — backend applies tenant TZ)
    const start = `${date}T${time}:00`;
    const startMs = new Date(`${date}T${time}:00`).getTime();
    const endMs = startMs + parseInt(duration, 10) * 60 * 1000;
    const endDate = new Date(endMs);
    const pad = n => String(n).padStart(2, "0");
    const end = `${endDate.getFullYear()}-${pad(endDate.getMonth()+1)}-${pad(endDate.getDate())}T${pad(endDate.getHours())}:${pad(endDate.getMinutes())}:00`;

    setSaving(true);
    setErr("");
    try {
      await onSave({ name: name.trim(), phone: phone.trim() || null, email: email.trim() || null, notes: notes.trim() || null, start, end });
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  const field = {
    padding: "9px 12px", fontSize: 14, borderRadius: 8,
    border: `1px solid rgba(255,255,255,0.12)`, background: C.inputBg,
    color: C.text, outline: "none", width: "100%",
  };

  return (
    <form onSubmit={handleSubmit} style={{
      padding: "16px", marginBottom: 16, borderRadius: 12,
      border: "1px solid rgba(249,115,22,0.25)", background: "rgba(249,115,22,0.04)",
      display: "grid", gap: 10,
    }}>
      <div style={{ fontSize: 14, fontWeight: 800, color: C.text, marginBottom: 2 }}>Add Booking</div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <input placeholder="Name *" value={name} onChange={e => setName(e.target.value)} style={field} required />
        <input placeholder="Phone (optional)" value={phone} onChange={e => setPhone(e.target.value)} style={field} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <input placeholder="Email (optional)" type="email" value={email} onChange={e => setEmail(e.target.value)} style={field} />
        <select value={duration} onChange={e => setDuration(e.target.value)} style={{ ...field, cursor: "pointer" }}>
          <option value="30">30 min</option>
          <option value="60">1 hour</option>
          <option value="90">1.5 hours</option>
          <option value="120">2 hours</option>
        </select>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <input type="date" value={date} onChange={e => setDate(e.target.value)} style={{ ...field, colorScheme: "dark" }} required />
        <input type="time" value={time} onChange={e => setTime(e.target.value)} style={{ ...field, colorScheme: "dark" }} required />
      </div>

      <input placeholder="Notes (optional)" value={notes} onChange={e => setNotes(e.target.value)} style={field} />

      {err && <div style={{ fontSize: 12, color: "#fca5a5" }}>{err}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button type="submit" disabled={saving} style={{
          padding: "9px 20px", borderRadius: 8, border: "none", fontWeight: 800, fontSize: 13,
          background: C.accent, color: "#111", cursor: saving ? "not-allowed" : "pointer", opacity: saving ? 0.6 : 1,
        }}>
          {saving ? "Saving…" : "Add Booking"}
        </button>
        <button type="button" onClick={onCancel} style={{
          padding: "9px 16px", borderRadius: 8, fontWeight: 700, fontSize: 13,
          border: `1px solid rgba(255,255,255,0.12)`, background: "transparent", color: C.muted, cursor: "pointer",
        }}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── main component ───────────────────────────────────────────────────────────

export default function BookingsCard({ tenantKey, apiBase, commonHeaders }) {
  const BASE = (typeof apiBase === "string" && apiBase.trim())
    ? apiBase
    : (import.meta?.env?.VITE_API_BASE || "");

  const [rows,        setRows]        = useState([]);
  const [loading,     setLoading]     = useState(false);
  const [search,      setSearch]      = useState("");
  const [sort,        setSort]        = useState({ col: "starts_at", dir: "asc" });
  const [showAll,     setShowAll]     = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);

  const headers = useMemo(() => ({
    ...(commonHeaders || {}),
    "Content-Type":              "application/json",
    "ngrok-skip-browser-warning": "true",
  }), [commonHeaders]);

  async function apiFetch(path, opts = {}) {
    const res = await fetch(`${BASE}${path}`, {
      ...opts,
      headers: { ...headers, ...(opts.headers || {}) },
    });
    if (res.status === 204) return null;
    const txt = await res.text().catch(() => "");
    let data = null;
    try { data = txt ? JSON.parse(txt) : null; } catch {}
    if (!res.ok) throw new Error(data?.detail || txt || `HTTP ${res.status}`);
    return data;
  }

  const loadBookings = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch("/upcoming");
      const items = Array.isArray(data) ? data
        : data?.items || data?.bookings || data?.rows || data?.data || [];
      setRows(items.map(normalizeRow));
    } catch (err) {
      console.error("[BookingsCard] load error:", err);
    } finally {
      setLoading(false);
    }
  }, [headers, BASE]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { loadBookings(); }, [tenantKey, BASE, loadBookings]);

  function toggleSort(col) {
    setSort(s =>
      s.col === col
        ? { col, dir: s.dir === "asc" ? "desc" : "asc" }
        : { col, dir: "asc" }
    );
  }

  async function addBooking(payload) {
    await apiFetch("/book", { method: "POST", body: JSON.stringify(payload) });
    setShowAddForm(false);
    setShowAll(true); // ensure the new booking is visible regardless of date
    loadBookings();
  }

  async function markDone(id) {
    try {
      await apiFetch(`/bookings/${id}/complete`, { method: "POST" });
      setRows(prev => prev.map(b => b.id === id ? { ...b, completed: true } : b));
    } catch (err) {
      console.error("[BookingsCard] markDone error:", err);
    }
  }

  async function deleteBooking(id) {
    if (!window.confirm("Delete this booking?")) return;
    try {
      await apiFetch(`/tenant/bookings/${id}`, { method: "DELETE" });
      setRows(prev => prev.filter(b => b.id !== id));
    } catch (err) {
      console.error("[BookingsCard] delete error:", err);
    }
  }

  const visible = useMemo(() => {
    const q   = search.toLowerCase().trim();
    const now = Date.now();

    let list = [...rows];

    if (q) {
      list = list.filter(r =>
        (r.name   || "").toLowerCase().includes(q) ||
        (r.phone  || "").toLowerCase().includes(q) ||
        (r.notes  || "").toLowerCase().includes(q) ||
        (r.source || "").toLowerCase().includes(q) ||
        (r.email  || "").toLowerCase().includes(q)
      );
    }

    if (!showAll) {
      list = list.filter(r => {
        if (r.completed) return false;
        const t = r.starts_at ? (parseISO(r.starts_at)?.getTime() ?? 0) : 0;
        return t >= now;
      });
    }

    list.sort((a, b) => {
      let av, bv;
      if (sort.col === "starts_at") {
        av = parseISO(a.starts_at)?.getTime() ?? 0;
        bv = parseISO(b.starts_at)?.getTime() ?? 0;
      } else if (sort.col === "name") {
        av = (a.name || "").toLowerCase();
        bv = (b.name || "").toLowerCase();
      } else if (sort.col === "status") {
        const rank = r => r.completed ? 2 : ((parseISO(r.starts_at) ?? new Date(0)) < new Date() ? 1 : 0);
        av = rank(a); bv = rank(b);
      } else {
        return 0;
      }
      if (av < bv) return sort.dir === "asc" ? -1 : 1;
      if (av > bv) return sort.dir === "asc" ?  1 : -1;
      return 0;
    });

    return list;
  }, [rows, search, sort, showAll]);

  // ── column definitions ─────────────────────────────────────────────────
  const cols = [
    { key: "starts_at", label: "Time",     w: "130px" },
    { key: "name",      label: "Customer", w: "130px" },
    { key: "phone",     label: "Phone",    w: "130px", noSort: true },
    { key: "source",    label: "Source",   w: "115px", noSort: true },
    { key: "notes",     label: "Notes",    w: "200px", noSort: true },
    { key: "status",    label: "Status",   w: "90px"  },
    { key: "actions",   label: "",         w: "110px", noSort: true },
  ];

  const thBase = {
    padding: "10px 10px",
    textAlign: "left",
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: 0.5,
    color: C.muted,
    textTransform: "uppercase",
    borderBottom: C.border,
    whiteSpace: "nowrap",
    userSelect: "none",
  };

  // ── render ─────────────────────────────────────────────────────────────
  return (
    <div style={{ color: C.text, fontFamily: "system-ui, -apple-system, sans-serif" }}>

      {/* ── header bar ── */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 14, flexWrap: "wrap", gap: 10,
      }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>Bookings</div>
          <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
            {visible.length} booking{visible.length !== 1 ? "s" : ""}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>

          {/* upcoming / all toggle */}
          <button
            onClick={() => setShowAll(v => !v)}
            style={{
              padding: "7px 14px", borderRadius: 8, fontSize: 12, fontWeight: 600,
              cursor: "pointer", border: C.border,
              background: showAll ? "rgba(255,255,255,0.08)" : "transparent",
              color: showAll ? C.text : C.muted,
              transition: "all 0.15s",
            }}
          >
            {showAll ? "All" : "Upcoming"}
          </button>

          {/* refresh */}
          <button
            onClick={loadBookings}
            disabled={loading}
            style={{
              padding: "7px 12px", borderRadius: 8, fontSize: 12, fontWeight: 600,
              cursor: "pointer", border: C.border,
              background: "transparent", color: C.muted,
              opacity: loading ? 0.5 : 1, transition: "opacity 0.15s",
            }}
          >
            {loading ? "…" : "↻"}
          </button>

          {/* search */}
          <input
            type="text"
            placeholder="Search…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              padding: "7px 14px", borderRadius: 10, fontSize: 13,
              background: C.inputBg, border: C.border, color: C.text,
              outline: "none", width: "min(200px, 100%)",
            }}
          />

          {/* add booking */}
          <button
            onClick={() => setShowAddForm(v => !v)}
            style={{
              padding: "7px 14px", borderRadius: 8, fontWeight: 800, fontSize: 13,
              border: "none", background: C.accent, color: "#111", cursor: "pointer", whiteSpace: "nowrap",
            }}
          >
            + Add Booking
          </button>
        </div>
      </div>

      {showAddForm && (
        <AddBookingForm onSave={addBooking} onCancel={() => setShowAddForm(false)} />
      )}

      {/* ── table ── */}
      <div className="table-scroll-wrap" style={{ overflowX: "auto", borderRadius: 12, border: C.border }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 700 }}>
          <thead>
            <tr style={{ background: "rgba(255,255,255,0.03)" }}>
              {cols.map(c => (
                <th
                  key={c.key}
                  style={{ ...thBase, width: c.w, minWidth: c.w, cursor: c.noSort ? "default" : "pointer" }}
                  onClick={() => !c.noSort && toggleSort(c.key)}
                >
                  {c.label}{" "}
                  {!c.noSort || undefined}
                  {!c.noSort && <SortIcon dir={sort.col === c.key ? sort.dir : null} />}
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} style={{ padding: 28, textAlign: "center", color: C.muted }}>
                  Loading…
                </td>
              </tr>
            )}

            {!loading && visible.length === 0 && (
              <tr>
                <td colSpan={7} style={{ padding: 28, textAlign: "center", color: C.muted }}>
                  {showAll ? "No bookings found." : "No upcoming bookings."}
                </td>
              </tr>
            )}

            {!loading && visible.map((b, i) => (
              <tr
                key={b.id}
                style={{
                  background:   i % 2 === 0 ? "transparent" : C.rowEven,
                  borderBottom: "1px solid rgba(255,255,255,0.04)",
                  opacity:      b.completed ? 0.55 : 1,
                  transition:   "background 0.1s",
                }}
                onMouseEnter={e => e.currentTarget.style.background = C.rowHover}
                onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? "transparent" : C.rowEven}
              >
                {/* Time */}
                <td style={{ padding: "10px 10px", color: C.muted, fontSize: 12, whiteSpace: "nowrap" }}>
                  {formatBookingTime(b.starts_at)}
                </td>

                {/* Customer */}
                <td style={{ padding: "10px 10px", fontWeight: 600, whiteSpace: "nowrap" }}>
                  {b.name || "—"}
                </td>

                {/* Phone */}
                <td style={{ padding: "10px 10px", whiteSpace: "nowrap" }}>
                  {b.phone
                    ? <a href={`tel:${b.phone}`} style={{ color: C.accent, textDecoration: "none", fontWeight: 600 }}>{b.phone}</a>
                    : <span style={{ color: C.muted }}>—</span>
                  }
                </td>

                {/* Source */}
                <td style={{ padding: "10px 10px" }}>
                  <SourceBadge source={b.source} />
                </td>

                {/* Notes */}
                <td style={{ padding: "10px 10px" }}>
                  <div
                    title={b.notes || ""}
                    style={{
                      maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap", fontSize: 12,
                      color: b.notes ? C.text : C.muted,
                    }}
                  >
                    {b.notes || "—"}
                  </div>
                </td>

                {/* Status */}
                <td style={{ padding: "10px 10px" }}>
                  <StatusBadge row={b} />
                </td>

                {/* Actions */}
                <td style={{ padding: "10px 10px", whiteSpace: "nowrap" }}>
                  {!b.completed && (
                    <button
                      onClick={() => markDone(b.id)}
                      style={{
                        padding: "5px 10px", borderRadius: 8, fontSize: 11, fontWeight: 700,
                        cursor: "pointer", border: "none", marginRight: 6,
                        background: "rgba(249,115,22,0.12)", color: C.accent,
                        transition: "all 0.15s",
                      }}
                    >
                      Mark Done
                    </button>
                  )}
                  <button
                    onClick={() => deleteBooking(b.id)}
                    style={{
                      padding: "5px 8px", borderRadius: 8, fontSize: 11, fontWeight: 700,
                      cursor: "pointer", border: "none",
                      background: "rgba(239,68,68,0.1)", color: "rgba(239,68,68,0.65)",
                      transition: "all 0.15s",
                    }}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
