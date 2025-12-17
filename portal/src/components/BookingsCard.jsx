// FILE: portal/src/components/BookingsCard.jsx
import { useEffect, useMemo, useState, useCallback } from "react";

// ✅ Use the multi-tenant booking API route
const LIST_PATH   = "/upcoming"; // GET upcoming bookings for this tenant (JWT → tenant)
const CREATE_PATH = "/book";     // POST create booking (tenant from JWT)
const TENANT_SLUG_FALLBACK = "default";

// --- small helpers ---
function formatDateAny(v) {
  if (!v) return "";

  try {
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return String(v);

    const parts = new Intl.DateTimeFormat("en-US", {
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZone: "America/New_York",
    }).formatToParts(d);

    let month, day, hour, minute, dayPeriod;

    for (const p of parts) {
      if (p.type === "month") month = p.value;
      else if (p.type === "day") day = p.value;
      else if (p.type === "hour") hour = p.value;
      else if (p.type === "minute") minute = p.value;
      else if (p.type === "dayPeriod") dayPeriod = p.value.toLowerCase();
    }

    return `${month}-${day} ${hour}:${minute}${dayPeriod}`;
  } catch {
    return String(v);
  }
}

function normalizeRow(r, i) {
  const startsAt =
    r.starts_at ||
    r.start ||
    r.starts_at_iso ||
    r.start_iso ||
    r.when ||
    null;

  const createdAt =
    r.created_at ||
    r.created ||
    r.created_at_iso ||
    r.createdAt ||
    null;

  const note =
    r.note ||
    r.notes ||
    [r.service, r.address].filter(Boolean).join(" | ") ||
    "";

  return {
    id:
      r.id ??
      r.booking_id ??
      r.pk ??
      `${r.name || "row"}-${startsAt || i}`,
    name: r.name || "",
    email: r.email || "",
    phone: r.phone || "",
    note,
    starts_at: startsAt,
    created_at: createdAt,
    completed: Boolean(r.completed || r.completed_at),
    tenant_id: r.tenant_id || r.tenant || null,
  };
}

export default function BookingsCard({
  tenantKey,
  tenantSlug,
  apiBase,
  commonHeaders,
}) {
  const API_BASE_FALLBACK =
    import.meta?.env?.VITE_API_BASE ||
    "https://unreproached-physiocratic-madisyn.ngrok-free.dev";

  const BASE =
    typeof apiBase === "string" && apiBase.trim()
      ? apiBase
      : API_BASE_FALLBACK;

  const TENANT_SLUG =
    typeof tenantSlug === "string" && tenantSlug.trim()
      ? tenantSlug.trim()
      : TENANT_SLUG_FALLBACK;

  // ---- state ----
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  const [range, setRange] = useState("7d");
  const [search, setSearch] = useState("");
  const [hidePast, setHidePast] = useState(true);
  const [sortBy, setSortBy] = useState("upcoming");
  const [showCompletedOnly, setShowCompletedOnly] = useState(false);
  const [showIncompleteOnly, setShowIncompleteOnly] = useState(false);

  const [form, setForm] = useState({
    name: "",
    email: "",
    phone: "",
    startsAt: "",
    note: "",
  });

  const [adding, setAdding] = useState(false);

  // ✅ IMPORTANT: do NOT send x-tenant-id here.
  const headers = useMemo(
    () => ({
      ...(commonHeaders || {}), // should already include Authorization: Bearer <token>
      "Content-Type": "application/json",
      "ngrok-skip-browser-warning": "true",
    }),
    [commonHeaders]
  );

  // ---- api helpers ----
  async function apiGet(path) {
    return fetch(`${BASE}${path}`, { headers });
  }

  async function apiJson(path, opts = {}) {
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

  function localWallToZonedIso(localWall) {
  // localWall: "YYYY-MM-DDTHH:mm" or "YYYY-MM-DDTHH:mm:ss"
  const wall = localWall.length === 16 ? `${localWall}:00` : localWall;
  const d = new Date(wall);

  // getTimezoneOffset() = minutes behind UTC (NY winter = 300)
  const offMin = d.getTimezoneOffset();
  const sign = offMin > 0 ? "-" : "+";
  const abs = Math.abs(offMin);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");

  return `${wall}${sign}${hh}:${mm}`;
}


  // ---- load list ----
  const loadBookings = useCallback(
    async () => {
      setLoading(true);
      try {
        const res = await apiGet(LIST_PATH);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();

        let items;
        if (Array.isArray(data)) {
          items = data;
        } else if (data && typeof data === "object") {
          items = data.items || data.bookings || data.rows || data.data || [];
          if (!items.length) {
            const firstArray = Object.values(data).find((v) =>
              Array.isArray(v)
            );
            items = firstArray || [];
          }
        } else {
          items = [];
        }

        setRows(items.map((r, i) => normalizeRow(r, i)));
      } catch (e) {
        console.error(e);
        alert("Could not load bookings");
        setRows([]);
      } finally {
        setLoading(false);
      }
    },
    [headers, BASE]
  );

  useEffect(() => {
    loadBookings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantKey, TENANT_SLUG, BASE]);

  // ---- create ----
  async function handleAdd() {
    if (!form.name || !form.startsAt) {
      alert("Name and time required");
      return;
    }
    setAdding(true);
    try {
const startWall =
  form.startsAt.length === 16 ? `${form.startsAt}:00` : form.startsAt;

const startDate = new Date(startWall);
const endDate = new Date(startDate.getTime() + 60 * 60 * 1000);

const toWall = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}T` +
  `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;

const startIso = localWallToZonedIso(startWall);
const endIso = localWallToZonedIso(toWall(endDate));

      // POST to /book (tenant comes from JWT)
      await apiJson(CREATE_PATH, {
        method: "POST",
        body: JSON.stringify({
          start: startIso,
          end: endIso,
          name: form.name,
          email: form.email || null,
          phone: form.phone || null,
          notes: form.note || null,
        }),
      });

      setForm({
        name: "",
        email: "",
        phone: "",
        startsAt: "",
        note: "",
      });
      await loadBookings();
    } catch (err) {
      alert(`Create failed: ${err.message || err}`);
    } finally {
      setAdding(false);
    }
  }

  // ---- complete ----
  async function completeBooking(id) {
    if (!confirm(`Mark booking #${id} as completed and send review SMS?`)) return;

    try {
      const res = await fetch(
        `${BASE}/bookings/${id}/complete`,
        {
          method: "POST",
          headers,
        }
      );

      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(txt || `HTTP ${res.status}`);
      }

      setRows((prev) =>
        prev.map((b) =>
          b.id === id ? { ...b, completed: true } : b
        )
      );
    } catch (err) {
      alert(`Complete failed: ${err.message || err}`);
    }
  }

  // ---- delete ----
  async function deleteBooking(id) {
    if (!window.confirm(`Delete booking #${id}?`)) return;

    try {
      const res = await fetch(
        `${BASE}/tenant/bookings/${id}`,
        {
          method: "DELETE",
          headers,
        }
      );

      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(txt || `HTTP ${res.status}`);
      }
      setRows((prev) => prev.filter((r) => r.id !== id));
    } catch (err) {
      alert(`Delete failed: ${err.message || err}`);
    }
  }

  // ---- search + sort + hide past + completed/incomplete filter ----
  function filterBySearch(list, term) {
    const q = (term || "").toLowerCase().trim();
    if (!q) return list;
    return list.filter(
      (r) =>
        (r.name || "").toLowerCase().includes(q) ||
        (r.phone || "").toLowerCase().includes(q) ||
        (r.email || "").toLowerCase().includes(q) ||
        (r.note || "").toLowerCase().includes(q)
    );
  }

  const filtered = (() => {
    const now = Date.now();
    let base = [...rows];

    base = filterBySearch(base, search);

    if (hidePast) {
      base = base.filter((b) => {
        const t = new Date(b.starts_at).getTime();
        return !isNaN(t) && t >= now;
      });
    }

    if (showCompletedOnly) {
      base = base.filter((b) => b.completed);
    } else if (showIncompleteOnly) {
      base = base.filter((b) => !b.completed);
    }

    return base;
  })();

  const sorted = (() => {
    const arr = [...filtered];

    if (sortBy === "upcoming") {
      return arr.sort(
        (a, b) => new Date(a.starts_at) - new Date(b.starts_at)
      );
    }
    if (sortBy === "created") {
      return arr.sort(
        (a, b) =>
          new Date(b.created_at || b.starts_at) -
          new Date(a.created_at || a.starts_at)
      );
    }
    return arr;
  })();

  // ---- UI ----
  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        padding: 16,
        marginTop: 16,
      }}
    >
      <h2 style={{ margin: 0 }}>Bookings</h2>

      {/* Controls */}
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
          marginTop: 8,
        }}
      >
        <select value={range} onChange={(e) => setRange(e.target.value)}>
          <option value="today">Today</option>
          <option value="7d">Next 7 Days</option>
          <option value="30d">Next 30 Days</option>
          <option value="all">All</option>
        </select>

        <label
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <input
            type="checkbox"
            checked={hidePast}
            onChange={(e) => setHidePast(e.target.checked)}
          />
          Hide past
        </label>

        <label
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <input
            type="checkbox"
            checked={showCompletedOnly}
            onChange={(e) => {
              const checked = e.target.checked;
              setShowCompletedOnly(checked);
              if (checked) setShowIncompleteOnly(false);
            }}
          />
          Completed only
        </label>

        <label
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <input
            type="checkbox"
            checked={showIncompleteOnly}
            onChange={(e) => {
              const checked = e.target.checked;
              setShowIncompleteOnly(checked);
              if (checked) setShowCompletedOnly(false);
            }}
          />
          Incomplete only
        </label>

        <div style={{ display: "inline-flex", gap: 6 }}>
          <button
            onClick={() => setSortBy("upcoming")}
            disabled={sortBy === "upcoming"}
            title="Date: Oldest → Newest"
          >
            Date (Oldest→Newest)
          </button>
          <button
            onClick={() => setSortBy("created")}
            disabled={sortBy === "created"}
            title="Newest first"
          >
            Newest
          </button>
        </div>

        <button onClick={loadBookings} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>

        <span
          style={{
            marginLeft: 8,
            fontSize: 12,
            padding: "3px 8px",
            borderRadius: 9999,
            background: "#eef2ff",
            color: "#3730a3",
          }}
        >
          {sorted.length} shown
        </span>
      </div>

      {/* Search */}
      <div style={{ marginTop: 8, marginBottom: 8 }}>
        <input
          type="text"
          placeholder="Search name, phone, email, or note..."
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

      {/* Add Booking */}
      <form
        onSubmit={(e) => e.preventDefault()}
        style={{
          display: "grid",
          gap: 8,
          gridTemplateColumns: "repeat(2,1fr)",
          marginTop: 4,
        }}
      >
        <input
          placeholder="Name"
          value={form.name}
          onChange={(e) =>
            setForm((f) => ({ ...f, name: e.target.value }))
          }
          required
        />
        <input
          type="datetime-local"
          value={form.startsAt}
          onChange={(e) =>
            setForm((f) => ({ ...f, startsAt: e.target.value }))
          }
          required
        />
        <input
          type="email"
          placeholder="Email"
          value={form.email}
          onChange={(e) =>
            setForm((f) => ({ ...f, email: e.target.value }))
          }
        />
        <input
          placeholder="Phone"
          value={form.phone}
          onChange={(e) =>
            setForm((f) => ({ ...f, phone: e.target.value }))
          }
        />
        <input
          placeholder="Note"
          value={form.note}
          onChange={(e) =>
            setForm((f) => ({ ...f, note: e.target.value }))
          }
        />
        <button
          type="button"
          onClick={handleAdd}
          disabled={adding}
          style={{ gridColumn: "span 2" }}
        >
          {adding ? "Adding…" : "Add Booking"}
        </button>
      </form>

      {/* Table */}
      <div
        style={{
          marginTop: 12,
          maxHeight: 320,
          overflow: "auto",
          borderTop: "1px solid #f3f4f6",
        }}
      >
        <table
          style={{ width: "100%", fontSize: 14, borderCollapse: "collapse" }}
        >
          <thead>
            <tr>
              <th>Time</th>
              <th>Name</th>
              <th>Phone</th>
              <th>Email</th>
              <th>Note</th>
              <th>Tenant</th>
              <th style={{ textAlign: "right" }}>Actions</th>
            </tr>
          </thead>

          <tbody>
            {sorted.map((b) => (
              <tr key={b.id}>
                <td>{formatDateAny(b.starts_at)}</td>
                <td>
                  {b.name}{" "}
                  {b.completed && (
                    <span
                      style={{
                        marginLeft: 6,
                        fontSize: 11,
                        padding: "2px 6px",
                        borderRadius: 9999,
                        background: "#dcfce7",
                        color: "#166534",
                      }}
                    >
                      Completed
                    </span>
                  )}
                </td>
                <td>
                  {b.phone ? (
                    <a href={`tel:${b.phone}`}>{b.phone}</a>
                  ) : (
                    ""
                  )}
                </td>
                <td>
                  {b.email ? (
                    <a href={`mailto:${b.email}`}>{b.email}</a>
                  ) : (
                    ""
                  )}
                </td>
                <td>{b.note}</td>
                <td>{b.tenant_id || "(none)"}</td>
                <td style={{ textAlign: "right" }}>
                  {!b.completed && (
                    <button
                      type="button"
                      onClick={() => completeBooking(b.id)}
                      style={{ marginRight: 6 }}
                    >
                      Complete
                    </button>
                  )}
                  <button type="button" onClick={() => deleteBooking(b.id)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {!sorted.length && !loading && (
              <tr>
                <td colSpan={7} style={{ padding: 8, color: "#6b7280" }}>
                  No bookings found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
