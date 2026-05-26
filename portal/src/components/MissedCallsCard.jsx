import { useEffect, useState } from "react";

const STATUSES = ["new", "contacted", "won", "lost"];

const STATUS_STYLES = {
  new: { color: "#fbbf24", bg: "rgba(251,191,36,0.12)" },
  contacted: { color: "#60a5fa", bg: "rgba(96,165,250,0.12)" },
  won: { color: "#34d399", bg: "rgba(52,211,153,0.12)" },
  lost: { color: "#9ca3af", bg: "rgba(156,163,175,0.12)" },
};

function fmt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function MissedCallsCard({ apiBase, commonHeaders }) {
  const [calls, setCalls] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [updatingId, setUpdatingId] = useState(null);

  async function load() {
    setLoading(true);
    setErr("");
    try {
      const res = await fetch(`${apiBase}/calls`, { headers: commonHeaders });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setCalls(data.items || []);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function updateStatus(id, newStatus) {
    setUpdatingId(id);
    try {
      const res = await fetch(`${apiBase}/leads/${id}/status`, {
        method: "PATCH",
        headers: commonHeaders,
        body: JSON.stringify({ status: newStatus }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setCalls((prev) =>
        prev.map((c) => (c.id === id ? { ...c, status: newStatus } : c))
      );
    } catch (e) {
      alert(`Failed to update status: ${e.message}`);
    } finally {
      setUpdatingId(null);
    }
  }

  useEffect(() => { load(); }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <h2 style={{ margin: 0, fontSize: 22, color: "#e5e7eb" }}>Missed Calls</h2>
        <button
          onClick={load}
          disabled={loading}
          style={{
            padding: "8px 14px",
            fontWeight: 700,
            fontSize: 13,
            borderRadius: 8,
            border: "1px solid rgba(249,115,22,0.5)",
            background: "rgba(249,115,22,0.12)",
            color: "#f97316",
            cursor: "pointer",
          }}
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {err && (
        <div style={{ fontSize: 13, color: "#fca5a5", marginBottom: 10 }}>{err}</div>
      )}

      {!loading && calls.length === 0 && (
        <div style={{
          padding: "40px 0",
          textAlign: "center",
          color: "rgba(229,231,235,0.4)",
          fontSize: 15,
        }}>
          No inbound calls recorded yet.
        </div>
      )}

      {calls.length > 0 && (
        <div style={{ display: "grid", gap: 8 }}>
          {calls.map((call) => {
            const st = STATUS_STYLES[call.status] || STATUS_STYLES.new;
            return (
              <div
                key={call.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr 1fr auto",
                  alignItems: "center",
                  gap: 12,
                  padding: "12px 16px",
                  borderRadius: 12,
                  border: "1px solid rgba(255,255,255,0.08)",
                  background: "rgba(255,255,255,0.03)",
                }}
              >
                {/* Phone */}
                <div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: "#e5e7eb" }}>
                    {call.phone}
                  </div>
                  {call.name && (
                    <div style={{ fontSize: 12, color: "rgba(229,231,235,0.55)", marginTop: 2 }}>
                      {call.name}
                    </div>
                  )}
                </div>

                {/* Time */}
                <div style={{ fontSize: 13, color: "rgba(229,231,235,0.6)" }}>
                  {fmt(call.created_at)}
                </div>

                {/* Status badge */}
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    padding: "4px 10px",
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 800,
                    color: st.color,
                    background: st.bg,
                    width: "fit-content",
                  }}
                >
                  {call.status}
                </div>

                {/* Actions */}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <a
                    href={`tel:${call.phone}`}
                    style={{
                      padding: "6px 10px",
                      fontSize: 12,
                      fontWeight: 700,
                      borderRadius: 7,
                      border: "1px solid rgba(96,165,250,0.4)",
                      background: "rgba(96,165,250,0.10)",
                      color: "#60a5fa",
                      textDecoration: "none",
                    }}
                  >
                    Call back
                  </a>
                  <select
                    value={call.status}
                    disabled={updatingId === call.id}
                    onChange={(e) => updateStatus(call.id, e.target.value)}
                    style={{
                      padding: "6px 8px",
                      fontSize: 12,
                      borderRadius: 7,
                      border: "1px solid rgba(255,255,255,0.12)",
                      background: "rgba(255,255,255,0.07)",
                      color: "#e5e7eb",
                      cursor: "pointer",
                    }}
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
