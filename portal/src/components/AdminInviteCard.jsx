import { useState, useCallback } from "react";

const cardStyle = {
  border: "1px solid rgba(255,255,255,0.10)",
  borderRadius: 16,
  padding: 20,
  background: "rgba(0,0,0,0.12)",
  marginTop: 16,
};

const inputStyle = {
  padding: "10px 14px",
  fontSize: 15,
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.15)",
  background: "rgba(255,255,255,0.07)",
  color: "#e5e7eb",
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

const btnPrimary = {
  padding: "10px 20px",
  fontWeight: 900,
  fontSize: 14,
  borderRadius: 10,
  border: "none",
  background: "#f97316",
  color: "#111827",
  cursor: "pointer",
};

const btnSecondary = {
  padding: "8px 14px",
  fontWeight: 700,
  fontSize: 13,
  borderRadius: 8,
  border: "1px solid rgba(249,115,22,0.5)",
  background: "rgba(249,115,22,0.12)",
  color: "#f97316",
  cursor: "pointer",
};

const STATUS_COLORS = {
  used: "#6b7280",
  expired: "#ef4444",
  valid: "#10b981",
};

function statusLabel(invite) {
  if (invite.used) return { label: "Used", color: STATUS_COLORS.used };
  if (invite.expired) return { label: "Expired", color: STATUS_COLORS.expired };
  return { label: "Valid", color: STATUS_COLORS.valid };
}

export default function AdminInviteCard({ apiBase, commonHeaders }) {
  const [adminKey, setAdminKey] = useState(
    () => sessionStorage.getItem("admin_invite_key") || ""
  );
  const [adminKeyInput, setAdminKeyInput] = useState("");
  const [keyUnlocked, setKeyUnlocked] = useState(
    () => !!sessionStorage.getItem("admin_invite_key")
  );

  const [daysValid, setDaysValid] = useState(7);
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [newCode, setNewCode] = useState(null);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState("");

  const [invites, setInvites] = useState([]);
  const [loadingList, setLoadingList] = useState(false);
  const [listErr, setListErr] = useState("");

  function unlockKey() {
    const k = adminKeyInput.trim();
    if (!k) return;
    sessionStorage.setItem("admin_invite_key", k);
    setAdminKey(k);
    setKeyUnlocked(true);
    setAdminKeyInput("");
    loadInvites(k);
  }

  const loadInvites = useCallback(async (key) => {
    const k = key || adminKey;
    if (!k) return;
    setLoadingList(true);
    setListErr("");
    try {
      const res = await fetch(`${apiBase}/auth/invite/list`, {
        headers: { ...commonHeaders, "X-Admin-Key": k },
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setInvites(data.invites || []);
    } catch (e) {
      setListErr(String(e.message || e));
    } finally {
      setLoadingList(false);
    }
  }, [apiBase, commonHeaders, adminKey]);

  async function createInvite(e) {
    e.preventDefault();
    setErr("");
    setNewCode(null);
    setCreating(true);
    try {
      const params = new URLSearchParams({ days_valid: daysValid });
      if (note.trim()) params.append("note", note.trim());
      const res = await fetch(`${apiBase}/auth/invite/create?${params}`, {
        method: "POST",
        headers: { ...commonHeaders, "X-Admin-Key": adminKey },
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setNewCode(data.code);
      setNote("");
      loadInvites();
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setCreating(false);
    }
  }

  function copyCode(code) {
    const signupUrl = `${window.location.origin}${window.location.pathname}?invite=${code}`;
    navigator.clipboard.writeText(signupUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  if (!keyUnlocked) {
    return (
      <div style={cardStyle}>
        <h3 style={{ margin: "0 0 12px", fontSize: 16, color: "#e5e7eb" }}>
          Invite Management
        </h3>
        <p style={{ margin: "0 0 10px", color: "rgba(229,231,235,0.65)", fontSize: 14 }}>
          Enter your admin key to manage invite codes.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="password"
            placeholder="Admin key"
            value={adminKeyInput}
            onChange={(e) => setAdminKeyInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && unlockKey()}
            style={{ ...inputStyle, flex: 1 }}
          />
          <button onClick={unlockKey} style={btnPrimary}>Unlock</button>
        </div>
      </div>
    );
  }

  return (
    <div style={cardStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 16, color: "#e5e7eb" }}>Invite Management</h3>
        <button
          style={{ ...btnSecondary, fontSize: 12 }}
          onClick={() => {
            sessionStorage.removeItem("admin_invite_key");
            setAdminKey("");
            setKeyUnlocked(false);
            setInvites([]);
            setNewCode(null);
          }}
        >
          Lock
        </button>
      </div>

      {/* Create invite */}
      <form onSubmit={createInvite} style={{ display: "grid", gap: 10, marginBottom: 18 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label style={{ color: "rgba(229,231,235,0.75)", fontSize: 13, whiteSpace: "nowrap" }}>
            Valid for
          </label>
          <input
            type="number"
            min={1}
            max={60}
            value={daysValid}
            onChange={(e) => setDaysValid(Number(e.target.value))}
            style={{ ...inputStyle, width: 70 }}
          />
          <span style={{ color: "rgba(229,231,235,0.65)", fontSize: 13 }}>days</span>
          <input
            placeholder="Note (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            style={{ ...inputStyle, flex: 1 }}
          />
          <button type="submit" disabled={creating} style={btnPrimary}>
            {creating ? "Creating…" : "Create Invite"}
          </button>
        </div>
        {err && (
          <div style={{ fontSize: 13, color: "#fca5a5" }}>{err}</div>
        )}
      </form>

      {/* New code banner */}
      {newCode && (
        <div style={{
          marginBottom: 16,
          padding: "14px 16px",
          borderRadius: 12,
          background: "rgba(16,185,129,0.10)",
          border: "1px solid rgba(16,185,129,0.30)",
          display: "flex",
          gap: 12,
          alignItems: "center",
          justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontSize: 12, color: "#6ee7b7", marginBottom: 4 }}>New invite code created</div>
            <code style={{ fontSize: 15, color: "#e5e7eb", letterSpacing: 1 }}>{newCode}</code>
          </div>
          <button onClick={() => copyCode(newCode)} style={btnSecondary}>
            {copied ? "Copied!" : "Copy signup link"}
          </button>
        </div>
      )}

      {/* Invite list */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: "rgba(229,231,235,0.65)" }}>
          {invites.length} invite{invites.length !== 1 ? "s" : ""}
        </span>
        <button onClick={() => loadInvites()} style={btnSecondary} disabled={loadingList}>
          {loadingList ? "Loading…" : "Refresh"}
        </button>
      </div>

      {listErr && (
        <div style={{ fontSize: 13, color: "#fca5a5", marginBottom: 8 }}>{listErr}</div>
      )}

      {invites.length === 0 && !loadingList ? (
        <div style={{ fontSize: 13, color: "rgba(229,231,235,0.4)", padding: "12px 0" }}>
          No invites yet.
        </div>
      ) : (
        <div style={{ display: "grid", gap: 6 }}>
          {invites.map((inv) => {
            const { label, color } = statusLabel(inv);
            return (
              <div
                key={inv.code}
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  padding: "10px 14px",
                  borderRadius: 10,
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.07)",
                }}
              >
                <span style={{ color, fontSize: 11, fontWeight: 900, minWidth: 48 }}>{label}</span>
                <code style={{ fontSize: 13, color: "#e5e7eb", flex: 1 }}>{inv.code}</code>
                <span style={{ fontSize: 12, color: "rgba(229,231,235,0.5)" }}>
                  {inv.note || ""}
                </span>
                <span style={{ fontSize: 11, color: "rgba(229,231,235,0.4)", whiteSpace: "nowrap" }}>
                  exp {inv.expires_at ? new Date(inv.expires_at).toLocaleDateString() : "—"}
                </span>
                {label === "Valid" && (
                  <button
                    onClick={() => copyCode(inv.code)}
                    style={{ ...btnSecondary, fontSize: 11, padding: "5px 10px" }}
                  >
                    Copy link
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
