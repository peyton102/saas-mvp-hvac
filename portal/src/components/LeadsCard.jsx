// FILE: portal/src/components/LeadsCard.jsx
import { useEffect, useMemo, useState, useCallback } from "react";

const BASE_FALLBACK = "/api";

// date helpers
function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
function formatDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toISOString().slice(0, 19).replace("T", " ");
}
function isThisMonthUTC(iso) {
  if (!iso) return false;
  const d = new Date(iso);
  const now = new Date();
  return d.getUTCFullYear() === now.getUTCFullYear() &&
         d.getUTCMonth() === now.getUTCMonth();
}

function StatusBadge({ value }) {
  const s = (value || "new").toLowerCase();
  const styles = {
    new:        { bg:"#dcfce7", fg:"#166534" },
    contacted:  { bg:"#e0f2fe", fg:"#075985" },
    won:        { bg:"#fef9c3", fg:"#854d0e" },
    lost:       { bg:"#fee2e2", fg:"#991b1b" },
  }[s] || { bg:"#e5e7eb", fg:"#374151" };

  return (
    <span style={{
      fontSize:12, padding:"2px 8px", borderRadius:9999,
      background: styles.bg, color: styles.fg, border:"1px solid rgba(0,0,0,0.05)"
    }}>
      {s.charAt(0).toUpperCase() + s.slice(1)}
    </span>
  );
}

export default function LeadsCard({ tenantKey, apiBase, commonHeaders }) {
  // ✅ use apiBase if provided, else fall back to /api
  const BASE = (typeof apiBase === "string" && apiBase.trim()) ? apiBase : BASE_FALLBACK;

  const [form, setForm] = useState({ name: "", phone: "", email: "", message: "" });
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  // filters
  const [range, setRange] = useState("7d"); // "today" | "7d" | "30d" | "all"
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all"); // all | new | contacted | won | lost

  // NEW: sort control
  const [sortBy, setSortBy] = useState("newest"); // newest | oldest | name | status

  // NEW: details drawer selection
  const [selected, setSelected] = useState(null);

  const headers = useMemo(
  () => ({
    ...(commonHeaders || {}),                // includes Authorization: Bearer <token>
    "ngrok-skip-browser-warning": "true",
    "Content-Type": "application/json",
  }),
  [commonHeaders]
);

  // ---- central API helper (now uses BASE + merged headers)
  async function apiFetch(path, opts = {}) {
    const res = await fetch(`${BASE}${path}`, {
      ...opts,
      headers: { ...headers, ...(opts.headers || {}) },
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(txt || `HTTP ${res.status}`);
    }
    return res.json();
  }

  const loadLeads = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch("/leads?limit=200");
      let items = data.items || [];

      // date-range filter
      const now = new Date();
      items = items.filter((r) => {
        if (!r.created_at) return false;
        const t = new Date(r.created_at);
        if (range === "today") return t.toDateString() === now.toDateString();
        if (range === "7d")   return now - t <= 7  * 24 * 60 * 60 * 1000;
        if (range === "30d")  return now - t <= 30 * 24 * 60 * 60 * 1000;
        if (range === "all")  return true;
        return true;
      });

      setRows(items);
    } catch (err) {
      console.error(err);
      alert("Could not load leads");
    } finally {
      setLoading(false);
    }
  }, [range, headers, BASE]); // ✅ include BASE like Bookings

  useEffect(() => {
    loadLeads();
  }, [tenantKey, range, BASE, loadLeads]); // ✅ re-run if BASE changes

  async function submitLead(e) {
    e.preventDefault();
    try {
      await apiFetch("/lead", {
        method: "POST",
        body: JSON.stringify({ ...form, source: "web" }),
      });
      setForm({ name: "", phone: "", email: "", message: "" });
      loadLeads();
    } catch (err) {
      alert(`Submit failed: ${err.message || err}`);
    }
  }

  function filterBySearch(list, term) {
    const q = (term || "").toLowerCase().trim();
    if (!q) return list;
    return list.filter((r) => {
      return (
        (r.name || "").toLowerCase().includes(q) ||
        (r.phone || "").toLowerCase().includes(q) ||
        (r.email || "").toLowerCase().includes(q)
      );
    });
  }

  // ----- Stats (after date range + search; independent of status quick-filter)
  const baseForStats = filterBySearch(rows, search);

  // NEW: sort the base set (before status filter), based on sortBy
  const baseSorted = useMemo(() => {
    const arr = [...baseForStats];
    const statusRank = { new: 0, contacted: 1, won: 2, lost: 3 };
    if (sortBy === "newest") {
      arr.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    } else if (sortBy === "oldest") {
      arr.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    } else if (sortBy === "name") {
      arr.sort((a, b) => (a.name || "").localeCompare(b.name || "", undefined, { sensitivity: "base" }));
    } else if (sortBy === "status") {
      arr.sort((a, b) => (statusRank[(a.status || "new").toLowerCase()] ?? 99) - (statusRank[(b.status || "new").toLowerCase()] ?? 99));
    }
    return arr;
  }, [baseForStats, sortBy]);

  const stats = useMemo(() => {
    const out = { total: baseForStats.length, new: 0, contacted: 0, won: 0, lost: 0 };
    for (const r of baseForStats) {
      const s = (r.status || "new").toLowerCase();
      if (out[s] !== undefined) out[s] += 1;
    }
    const conv = out.total ? Math.round((out.won / out.total) * 100) : 0;
    return { ...out, conversionPct: conv };
  }, [baseForStats]);

  // rows shown in table honor all filters (status filter AFTER sorting)
  const visibleRows = baseSorted.filter(r => {
    if (statusFilter === "all") return true;
    const s = (r.status || "new").toLowerCase();
    return s === statusFilter;
  });

  async function deleteLead(id) {
    if (!confirm(`Delete lead #${id}? This cannot be undone.`)) return;
    try {
      await apiFetch(`/leads/${id}`, { method: "DELETE" });
      // remove locally
      setRows((prev) => prev.filter((r) => r.id !== id));
    } catch (e) {
      alert(`Delete failed: ${e.message || e}`);
    }
  }

  async function updateStatus(id, status) {
    try {
      await apiFetch(`/leads/${id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setRows((prev) =>
        prev.map((r) => (r.id === id ? { ...r, status } : r))
      );
    } catch (e) {
      alert(`Update status failed: ${e.message || e}`);
    }
  }

  // ✅ your CSV exports preserved exactly
  function exportCsv() {
    const csv = [
      ["Created", "Name", "Phone", "Email", "Message", "Status"].join(","),
      ...visibleRows.map((r) =>
        [
          `"${r.created_at || ""}"`,
          `"${(r.name || "").replace(/"/g, '""')}"`,
          `"${(r.phone || "").replace(/"/g, '""')}"`,
          `"${(r.email || "").replace(/"/g, '""')}"`,
          `"${(r.message || "").replace(/"/g, '""')}"`,
          `"${(r.status || "new")}"`,
        ].join(",")
      ),
    ].join("\n");

    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `leads_${range}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function exportWonThisMonth() {
    const pick = visibleRows.filter(r => (r.status || "new").toLowerCase() === "won" && isThisMonthUTC(r.created_at));
    if (!pick.length) { alert("No won leads for this month in current view."); return; }
    const csv = [
      ["Created", "Name", "Phone", "Email", "Message", "Status"].join(","),
      ...pick.map((r) =>
        [
          `"${r.created_at || ""}"`,
          `"${(r.name || "").replace(/"/g, '""')}"`,
          `"${(r.phone || "").replace(/"/g, '""')}"`,
          `"${(r.email || "").replace(/"/g, '""')}"`,
          `"${(r.message || "").replace(/"/g, '""')}"`,
          `"${(r.status || "new")}"`,
        ].join(",")
      ),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `won_leads_${new Date().toISOString().slice(0,7)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function copy(text) {
    try { await navigator.clipboard.writeText(text || ""); } catch {}
  }

  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        padding: 16,
        marginTop: 16,
      }}
    >
      {/* Header & controls */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          marginBottom: 8,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ margin: 0 }}>Contact Requests</h2>

        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap:"wrap" }}>
          <select value={range} onChange={(e) => setRange(e.target.value)}>
            <option value="today">Today</option>
            <option value="7d">Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
            <option value="all">All Time</option>
          </select>

          {/* Sort control */}
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} title="Sort">
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            <option value="name">Name (A–Z)</option>
            <option value="status">Status (New→Lost)</option>
          </select>

          {/* Status quick filters */}
          <div style={{ display:"flex", gap:6, alignItems:"center", flexWrap:"wrap" }}>
            {["all","new","contacted","won","lost"].map(k => {
              const active = statusFilter === k;
              const bgMap = {
                all:"#eef2ff", new:"#dcfce7", contacted:"#e0f2fe", won:"#fef9c3", lost:"#fee2e2"
              };
              const fgMap = {
                all:"#111827", new:"#166534", contacted:"#075985", won:"#854d0e", lost:"#991b1b"
              };
              return (
                <button
                  key={k}
                  onClick={()=>setStatusFilter(k)}
                  style={{
                    padding:"4px 10px",
                    borderRadius:6,
                    border:"1px solid #e5e7eb",
                    background: active ? bgMap[k] : "white",
                    color: active ? fgMap[k] : "#111827",
                    fontWeight: active ? 700 : 500
                  }}
                >
                  {k[0].toUpperCase()+k.slice(1)}
                </button>
              );
            })}
          </div>

          <button onClick={loadLeads} disabled={loading}>Refresh</button>
          <button onClick={exportCsv} disabled={!visibleRows.length}>Export CSV</button>
          <button onClick={exportWonThisMonth} disabled={!visibleRows.length}>Export Won (This Month)</button>

          <span style={{
            marginLeft: 8, fontSize: 12, padding: "3px 8px",
            borderRadius: 9999, background: "#eef2ff", color: "#3730a3"
          }}>
            {visibleRows.length} shown
          </span>
        </div>
      </div>

      {/* Search */}
      <div style={{ marginTop: 8, marginBottom: 8 }}>
        <input
          type="text"
          placeholder="Search name, phone, or email..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            padding: "6px 10px",
            width: "100%",
            maxWidth: 320,
            border: "1px solid #ccc",
            borderRadius: 6,
          }}
        />
      </div>

      {/* lead form */}
      <form
        onSubmit={submitLead}
        style={{
          display: "grid",
          gap: 8,
          gridTemplateColumns: "repeat(2,1fr)",
          marginTop: 8,
        }}
      >
        <input
          placeholder="Name"
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          required
        />
        <input
          placeholder="Phone"
          value={form.phone}
          onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
          required
        />
        <input
          placeholder="Email"
          value={form.email}
          onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
        />
        <input
          placeholder="Message"
          value={form.message}
          onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))}
        />
        <button type="submit" style={{ gridColumn: "span 2", padding: "8px 12px" }}>
          Submit
        </button>
      </form>

      {/* Stats bar */}
      <div style={{ display:"flex", gap:12, flexWrap:"wrap", marginTop:12 }}>
        <div style={{ border:"1px solid #e5e7eb", borderRadius:10, padding:"8px 12px" }}>
          <b>Total:</b> {stats.total}
        </div>
        <div style={{ border:"1px solid #e5e7eb", borderRadius:10, padding:"8px 12px" }}>
          <b>New:</b> {stats.new}
        </div>
        <div style={{ border:"1px solid #e5e7eb", borderRadius:10, padding:"8px 12px" }}>
          <b>Contacted:</b> {stats.contacted}
        </div>
        <div style={{ border:"1px solid #e5e7eb", borderRadius:10, padding:"8px 12px" }}>
          <b>Won:</b> {stats.won}
        </div>
        <div style={{ border:"1px solid #e5e7eb", borderRadius:10, padding:"8px 12px" }}>
          <b>Lost:</b> {stats.lost}
        </div>
        <div style={{ border:"1px solid #e5e7eb", borderRadius:10, padding:"8px 12px" }}>
          <b>Win Rate:</b> {stats.conversionPct}%
        </div>
      </div>

      {/* leads table */}
      <div
        style={{
          marginTop: 12,
          maxHeight: 320,
          overflow: "auto",
          borderTop: "1px solid #f3f4f6",
        }}
      >
        <table style={{ width: "100%", fontSize: 14, borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th>Created</th>
              <th>Name</th>
              <th>Phone</th>
              <th>Email</th>
              <th>Message</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((r) => (
              // NEW: clicking a row opens details drawer
              <tr key={r.id} style={{ cursor:"pointer" }} onClick={()=>setSelected(r)}>
                <td>{formatDate(r.created_at)}</td>
                <td>{r.name || ""}</td>
                <td>
                  <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                    <a href={`tel:${r.phone || ""}`} style={{ textDecoration:"none" }}>
                      {r.phone || ""}
                    </a>
                    {!!r.phone && (
                      <button onClick={(e)=>{ e.stopPropagation(); copy(r.phone); }} title="Copy phone" style={{ padding:"2px 6px" }}>
                        Copy
                      </button>
                    )}
                  </div>
                </td>
                <td>
                  <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                    {r.email ? <a href={`mailto:${r.email}`} onClick={(e)=>e.stopPropagation()}>{r.email}</a> : ""}
                    {!!r.email && (
                      <button onClick={(e)=>{ e.stopPropagation(); copy(r.email); }} title="Copy email" style={{ padding:"2px 6px" }}>
                        Copy
                      </button>
                    )}
                  </div>
                </td>
                <td
                  style={{
                    maxWidth: 260,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                  title={r.message || ""}
                >
                  {r.message || ""}
                </td>
                <td onClick={(e)=>e.stopPropagation()}>
                  <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                    <StatusBadge value={r.status} />
                    <select
                      value={r.status || "new"}
                      onChange={(e) => updateStatus(r.id, e.target.value)}
                    >
                      <option value="new">New</option>
                      <option value="contacted">Contacted</option>
                      <option value="won">Won</option>
                      <option value="lost">Lost</option>
                    </select>
                  </div>
                </td>
                <td style={{ textAlign: "right" }} onClick={(e)=>e.stopPropagation()}>
                  <button onClick={() => deleteLead(r.id)}>Delete</button>
                </td>
              </tr>
            ))}
            {!visibleRows.length && !loading && (
              <tr>
                <td colSpan={7} style={{ padding: 8, color: "#6b7280" }}>
                  No leads match your filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Read-only Details Drawer */}
      {selected && (
        <>
          {/* backdrop */}
          <div
            onClick={()=>setSelected(null)}
            style={{
              position:"fixed", inset:0, background:"rgba(0,0,0,0.35)",
              zIndex: 40
            }}
          />
          {/* panel */}
          <div style={{
            position:"fixed", top:0, right:0, bottom:0, width:"min(420px, 92vw)",
            background:"#fff", boxShadow:"-8px 0 24px rgba(0,0,0,0.12)", zIndex: 41,
            display:"flex", flexDirection:"column"
          }}>
            <div style={{ padding:16, borderBottom:"1px solid #eee", display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <h3 style={{ margin:0 }}>Lead Details</h3>
              <button onClick={()=>setSelected(null)}>Close</button>
            </div>

            <div style={{ padding:16, display:"grid", gap:10, fontSize:14 }}>
              <div><b>Created:</b> {formatDateTime(selected.created_at)}</div>
              <div><b>Status:</b> {(selected.status || "new").toUpperCase()}</div>
              <div><b>Name:</b> {selected.name || "-"}</div>
              <div><b>Phone:</b> {selected.phone || "-"}</div>
              <div><b>Email:</b> {selected.email || "-"}</div>
              <div><b>Message:</b><br/>{selected.message || "-"}</div>
              <div><b>Tenant:</b> {selected.tenant_id || "-"}</div>
              <div><b>ID:</b> {selected.id}</div>
            </div>

            <div style={{ marginTop:"auto", padding:16, borderTop:"1px solid #eee", display:"flex", gap:8 }}>
              <button onClick={exportCsv} disabled={!visibleRows.length}>Export CSV</button>
              <button onClick={exportWonThisMonth} disabled={!visibleRows.length}>Export Won (This Month)</button>
              <button onClick={()=>setSelected(null)} style={{ marginLeft:"auto" }}>Done</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
