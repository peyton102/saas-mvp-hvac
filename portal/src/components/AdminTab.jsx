import { useEffect, useState, useCallback } from "react";

// ---- status config ----
const STATUS = {
  pending:   { label: "Pending",    color: "#fbbf24", bg: "rgba(251,191,36,0.12)"  },
  signed_up: { label: "Signed Up",  color: "#34d399", bg: "rgba(52,211,153,0.12)"  },
  expired:   { label: "Expired",    color: "#9ca3af", bg: "rgba(156,163,175,0.12)" },
};

const inputStyle = {
  padding: "12px 16px",
  fontSize: 15,
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.15)",
  background: "rgba(255,255,255,0.07)",
  color: "#e5e7eb",
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

const btnOrange = {
  padding: "12px 24px",
  fontWeight: 900,
  fontSize: 14,
  borderRadius: 10,
  border: "none",
  background: "#f97316",
  color: "#111827",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const btnGhost = {
  padding: "7px 14px",
  fontWeight: 700,
  fontSize: 12,
  borderRadius: 8,
  border: "1px solid rgba(249,115,22,0.45)",
  background: "rgba(249,115,22,0.10)",
  color: "#f97316",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short", day: "numeric", year: "numeric",
    });
  } catch {
    return iso;
  }
}

function StatusBadge({ status }) {
  const s = STATUS[status] || STATUS.pending;
  return (
    <span style={{
      padding: "3px 10px",
      borderRadius: 6,
      fontSize: 11,
      fontWeight: 800,
      color: s.color,
      background: s.bg,
      display: "inline-block",
      whiteSpace: "nowrap",
    }}>
      {s.label}
    </span>
  );
}

export default function AdminTab({ apiBase, commonHeaders }) {
  const [email, setEmail]         = useState("");
  const [daysValid, setDaysValid] = useState(7);
  const [sending, setSending]     = useState(false);
  const [sendErr, setSendErr]     = useState("");
  const [sendOk, setSendOk]       = useState("");

  const [invites, setInvites]     = useState([]);
  const [loading, setLoading]     = useState(false);
  const [listErr, setListErr]     = useState("");

  const [resendingCode, setResendingCode] = useState(null);

  const loadInvites = useCallback(async () => {
    setLoading(true);
    setListErr("");
    try {
      const res = await fetch(`${apiBase}/admin/invites`, { headers: commonHeaders });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      setInvites(await res.json());
    } catch (e) {
      setListErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [apiBase, commonHeaders]);

  useEffect(() => { loadInvites(); }, [loadInvites]);

  async function sendInvite(e) {
    e.preventDefault();
    setSendErr("");
    setSendOk("");
    if (!email.trim()) return setSendErr("Email is required.");

    setSending(true);
    try {
      const res = await fetch(`${apiBase}/admin/invites/send`, {
        method: "POST",
        headers: commonHeaders,
        body: JSON.stringify({ email: email.trim(), days_valid: daysValid }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setSendOk(`Invite sent to ${email.trim()}`);
      setEmail("");
      loadInvites();
    } catch (e) {
      setSendErr(String(e.message || e));
    } finally {
      setSending(false);
    }
  }

  async function resend(code) {
    setResendingCode(code);
    try {
      const res = await fetch(`${apiBase}/admin/invites/${code}/resend`, {
        method: "POST",
        headers: commonHeaders,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      loadInvites();
    } catch (e) {
      alert(`Resend failed: ${e.message}`);
    } finally {
      setResendingCode(null);
    }
  }

  // counts
  const counts = invites.reduce((acc, inv) => {
    acc[inv.status] = (acc[inv.status] || 0) + 1;
    return acc;
  }, {});

  return (
    <div style={{ display: "grid", gap: 24 }}>

      {/* Header */}
      <div>
        <h2 style={{ margin: "0 0 4px", fontSize: 22, color: "#e5e7eb" }}>Admin — Invite Management</h2>
        <p style={{ margin: 0, fontSize: 14, color: "rgba(229,231,235,0.55)" }}>
          Send customers a pre-filled signup link by email.
        </p>
      </div>

      {/* Send invite form */}
      <div style={{
        padding: 20,
        borderRadius: 14,
        border: "1px solid rgba(255,255,255,0.10)",
        background: "rgba(255,255,255,0.03)",
      }}>
        <h3 style={{ margin: "0 0 14px", fontSize: 15, color: "#e5e7eb" }}>Send Invite</h3>
        <form onSubmit={sendInvite} style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 260px" }}>
            <label style={{ display: "block", fontSize: 12, color: "rgba(229,231,235,0.55)", marginBottom: 6 }}>
              Customer Email
            </label>
            <input
              type="email"
              placeholder="customer@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={inputStyle}
              autoComplete="off"
            />
          </div>
          <div style={{ width: 110 }}>
            <label style={{ display: "block", fontSize: 12, color: "rgba(229,231,235,0.55)", marginBottom: 6 }}>
              Expires (days)
            </label>
            <input
              type="number"
              min={1}
              max={60}
              value={daysValid}
              onChange={(e) => setDaysValid(Number(e.target.value))}
              style={{ ...inputStyle, width: "100%" }}
            />
          </div>
          <button
            type="submit"
            disabled={sending}
            style={{ ...btnOrange, opacity: sending ? 0.7 : 1 }}
          >
            {sending ? "Sending…" : "Send Invite"}
          </button>
        </form>

        {sendErr && (
          <div style={{ marginTop: 10, fontSize: 13, color: "#fca5a5", fontWeight: 700 }}>{sendErr}</div>
        )}
        {sendOk && (
          <div style={{ marginTop: 10, fontSize: 13, color: "#6ee7b7", fontWeight: 700 }}>{sendOk}</div>
        )}
      </div>

      {/* Invite list */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: "#e5e7eb" }}>
              Invites ({invites.length})
            </span>
            {Object.entries(counts).map(([status, n]) => (
              <span key={status} style={{ fontSize: 12, color: (STATUS[status] || STATUS.pending).color }}>
                {n} {(STATUS[status] || STATUS.pending).label.toLowerCase()}
              </span>
            ))}
          </div>
          <button onClick={loadInvites} disabled={loading} style={btnGhost}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>

        {listErr && (
          <div style={{ fontSize: 13, color: "#fca5a5", marginBottom: 10 }}>{listErr}</div>
        )}

        {!loading && invites.length === 0 && (
          <div style={{ padding: "32px 0", textAlign: "center", color: "rgba(229,231,235,0.35)", fontSize: 14 }}>
            No invites sent yet.
          </div>
        )}

        {invites.length > 0 && (
          <div style={{ display: "grid", gap: 6 }}>
            {/* Header row */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "1fr 90px 100px 100px auto",
              gap: 12,
              padding: "6px 14px",
              fontSize: 11,
              fontWeight: 700,
              color: "rgba(229,231,235,0.4)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}>
              <span>Email</span>
              <span>Status</span>
              <span>Sent</span>
              <span>Expires</span>
              <span></span>
            </div>

            {invites.map((inv) => (
              <div
                key={inv.code}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 90px 100px 100px auto",
                  gap: 12,
                  alignItems: "center",
                  padding: "12px 14px",
                  borderRadius: 10,
                  border: "1px solid rgba(255,255,255,0.07)",
                  background: "rgba(255,255,255,0.03)",
                }}
              >
                <div>
                  <div style={{ fontSize: 14, color: "#e5e7eb", fontWeight: 600 }}>
                    {inv.invited_email || <span style={{ color: "rgba(229,231,235,0.35)" }}>—</span>}
                  </div>
                  <div style={{ fontSize: 11, color: "rgba(229,231,235,0.35)", marginTop: 2, fontFamily: "monospace" }}>
                    {inv.code}
                  </div>
                </div>

                <StatusBadge status={inv.status} />

                <span style={{ fontSize: 12, color: "rgba(229,231,235,0.5)" }}>
                  {fmtDate(inv.sent_at || inv.created_at)}
                </span>

                <span style={{ fontSize: 12, color: "rgba(229,231,235,0.5)" }}>
                  {fmtDate(inv.expires_at)}
                </span>

                <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                  {inv.status !== "signed_up" && (
                    <button
                      onClick={() => resend(inv.code)}
                      disabled={resendingCode === inv.code}
                      style={{ ...btnGhost, opacity: resendingCode === inv.code ? 0.6 : 1 }}
                    >
                      {resendingCode === inv.code ? "Sending…" : "Resend"}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
