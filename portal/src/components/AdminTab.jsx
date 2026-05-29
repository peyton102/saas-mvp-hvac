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

const btnRed = {
  padding: "7px 14px",
  fontWeight: 700,
  fontSize: 12,
  borderRadius: 8,
  border: "1px solid rgba(239,68,68,0.45)",
  background: "rgba(239,68,68,0.10)",
  color: "#f87171",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const btnRedSolid = {
  padding: "12px 24px",
  fontWeight: 900,
  fontSize: 14,
  borderRadius: 10,
  border: "none",
  background: "#dc2626",
  color: "#fff",
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

// ---- Remove Tenant Modal ----
function RemoveTenantModal({ tenant, apiBase, commonHeaders, onClose, onDeleted }) {
  const confirmName = tenant.business_name || tenant.name || tenant.slug;
  const [typed, setTyped]         = useState("");
  const [deleting, setDeleting]   = useState(false);
  const [deleteErr, setDeleteErr] = useState("");

  async function handleDownload() {
    try {
      const res = await fetch(`${apiBase}/admin/mgmt/tenants/${tenant.slug}/export`, {
        headers: commonHeaders,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `tenant_${tenant.slug}_export.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(`Export failed: ${e.message}`);
    }
  }

  async function handleDelete() {
    if (typed !== confirmName) return;
    setDeleting(true);
    setDeleteErr("");
    try {
      const res = await fetch(`${apiBase}/admin/mgmt/tenants/${tenant.slug}`, {
        method: "DELETE",
        headers: commonHeaders,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      onDeleted(tenant.slug);
    } catch (e) {
      setDeleteErr(String(e.message || e));
      setDeleting(false);
    }
  }

  // Close on backdrop click
  function handleBackdrop(e) {
    if (e.target === e.currentTarget) onClose();
  }

  const canDelete = typed === confirmName && !deleting;

  return (
    <div
      onClick={handleBackdrop}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.70)",
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div style={{
        background: "#0f172a",
        border: "1px solid rgba(239,68,68,0.35)",
        borderRadius: 18,
        padding: 32,
        maxWidth: 520,
        width: "100%",
        display: "grid",
        gap: 20,
      }}>
        {/* Header */}
        <div>
          <div style={{ fontSize: 20, fontWeight: 900, color: "#f87171", marginBottom: 6 }}>
            Remove Tenant
          </div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#e5e7eb" }}>
            {confirmName}
          </div>
          {tenant.email && (
            <div style={{ fontSize: 12, color: "rgba(229,231,235,0.45)", marginTop: 2 }}>
              {tenant.email}
            </div>
          )}
        </div>

        {/* Warning */}
        <div style={{
          padding: "14px 16px",
          borderRadius: 10,
          background: "rgba(239,68,68,0.08)",
          border: "1px solid rgba(239,68,68,0.25)",
          fontSize: 13,
          color: "#fca5a5",
          lineHeight: 1.6,
        }}>
          <strong style={{ color: "#f87171" }}>This action is permanent and cannot be undone.</strong>{" "}
          All leads, bookings, calls, and finance entries belonging to this tenant will be hard deleted.
          Download the data below before proceeding.
        </div>

        {/* Download */}
        <div>
          <div style={{ fontSize: 12, color: "rgba(229,231,235,0.5)", marginBottom: 8 }}>
            Step 1 — Save a copy of all tenant data
          </div>
          <button onClick={handleDownload} style={btnGhost}>
            Download All Data (CSV)
          </button>
        </div>

        {/* Confirmation input */}
        <div>
          <div style={{ fontSize: 12, color: "rgba(229,231,235,0.5)", marginBottom: 8 }}>
            Step 2 — Type the business name to confirm:{" "}
            <span style={{ color: "#e5e7eb", fontWeight: 700 }}>{confirmName}</span>
          </div>
          <input
            type="text"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="Type the business name to confirm deletion"
            style={{ ...inputStyle, borderColor: typed && typed !== confirmName ? "rgba(239,68,68,0.5)" : "rgba(255,255,255,0.15)" }}
            autoComplete="off"
          />
        </div>

        {deleteErr && (
          <div style={{ fontSize: 13, color: "#fca5a5", fontWeight: 700 }}>{deleteErr}</div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={btnGhost} disabled={deleting}>
            Cancel
          </button>
          <button
            onClick={handleDelete}
            disabled={!canDelete}
            style={{
              ...btnRedSolid,
              opacity: canDelete ? 1 : 0.35,
              cursor: canDelete ? "pointer" : "not-allowed",
            }}
          >
            {deleting ? "Deleting…" : "Permanently Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminTab({ apiBase, commonHeaders }) {
  // ---- Invite state ----
  const [email, setEmail]         = useState("");
  const [daysValid, setDaysValid] = useState(7);
  const [sending, setSending]     = useState(false);
  const [sendErr, setSendErr]     = useState("");
  const [sendOk, setSendOk]       = useState("");

  const [invites, setInvites]     = useState([]);
  const [loading, setLoading]     = useState(false);
  const [listErr, setListErr]     = useState("");

  const [resendingCode, setResendingCode] = useState(null);

  // ---- Tenant management state ----
  const [tenants, setTenants]         = useState([]);
  const [tenantsLoading, setTenantsLoading] = useState(false);
  const [tenantsErr, setTenantsErr]   = useState("");
  const [removingTenant, setRemovingTenant] = useState(null); // tenant object for modal

  // ---- VAPI number assignment ----
  const [editingVapiSlug, setEditingVapiSlug] = useState(null);
  const [vapiInput, setVapiInput]             = useState("");
  const [vapiSaving, setVapiSaving]           = useState(false);
  const [vapiErr, setVapiErr]                 = useState("");

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

  const loadTenants = useCallback(async () => {
    setTenantsLoading(true);
    setTenantsErr("");
    try {
      const res = await fetch(`${apiBase}/admin/mgmt/tenants`, { headers: commonHeaders });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      setTenants(await res.json());
    } catch (e) {
      setTenantsErr(String(e.message || e));
    } finally {
      setTenantsLoading(false);
    }
  }, [apiBase, commonHeaders]);

  useEffect(() => {
    loadInvites();
    loadTenants();
  }, [loadInvites, loadTenants]);

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

  async function saveVapiNumber(slug, value) {
    setVapiSaving(true);
    setVapiErr("");
    try {
      const res = await fetch(`${apiBase}/admin/mgmt/tenants/${slug}/vapi-number`, {
        method: "PATCH",
        headers: { ...commonHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ vapi_phone_number_id: value }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setTenants((prev) =>
        prev.map((t) => t.slug === slug ? { ...t, twilio_number: data.twilio_number } : t)
      );
      setEditingVapiSlug(null);
      setVapiInput("");
    } catch (e) {
      setVapiErr(String(e.message || e));
    } finally {
      setVapiSaving(false);
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
    <div style={{ display: "grid", gap: 32 }}>

      {/* Remove Tenant Modal */}
      {removingTenant && (
        <RemoveTenantModal
          tenant={removingTenant}
          apiBase={apiBase}
          commonHeaders={commonHeaders}
          onClose={() => setRemovingTenant(null)}
          onDeleted={(slug) => {
            setRemovingTenant(null);
            setTenants((prev) => prev.filter((t) => t.slug !== slug));
          }}
        />
      )}

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

      {/* ---- Tenant Management ---- */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div>
            <h2 style={{ margin: "0 0 4px", fontSize: 22, color: "#e5e7eb" }}>Tenant Management</h2>
            <p style={{ margin: 0, fontSize: 14, color: "rgba(229,231,235,0.55)" }}>
              View and remove tenants. Deletion is permanent and cannot be undone.
            </p>
          </div>
          <button onClick={loadTenants} disabled={tenantsLoading} style={btnGhost}>
            {tenantsLoading ? "Loading…" : "Refresh"}
          </button>
        </div>

        {tenantsErr && (
          <div style={{ fontSize: 13, color: "#fca5a5", marginBottom: 10 }}>{tenantsErr}</div>
        )}

        {!tenantsLoading && tenants.length === 0 && !tenantsErr && (
          <div style={{ padding: "32px 0", textAlign: "center", color: "rgba(229,231,235,0.35)", fontSize: 14 }}>
            No tenants found.
          </div>
        )}

        {vapiErr && (
          <div style={{ fontSize: 13, color: "#fca5a5", marginBottom: 10 }}>{vapiErr}</div>
        )}

        {tenants.length > 0 && (
          <div style={{ display: "grid", gap: 6 }}>
            {/* Header */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 110px 80px 1fr auto",
              gap: 12,
              padding: "6px 14px",
              fontSize: 11,
              fontWeight: 700,
              color: "rgba(229,231,235,0.4)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}>
              <span>Business</span>
              <span>Email</span>
              <span>Slug</span>
              <span>Joined</span>
              <span>VAPI Number</span>
              <span></span>
            </div>

            {tenants.map((t) => (
              <div
                key={t.slug}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr 110px 80px 1fr auto",
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
                    {t.business_name || t.name || <span style={{ color: "rgba(229,231,235,0.35)" }}>—</span>}
                  </div>
                  {t.is_admin && (
                    <span style={{
                      fontSize: 10,
                      fontWeight: 800,
                      color: "#a78bfa",
                      background: "rgba(167,139,250,0.12)",
                      padding: "2px 6px",
                      borderRadius: 4,
                      display: "inline-block",
                      marginTop: 2,
                    }}>
                      ADMIN
                    </span>
                  )}
                </div>

                <span style={{ fontSize: 13, color: "rgba(229,231,235,0.65)" }}>
                  {t.email || <span style={{ color: "rgba(229,231,235,0.25)" }}>—</span>}
                </span>

                <span style={{ fontSize: 11, color: "rgba(229,231,235,0.4)", fontFamily: "monospace" }}>
                  {t.slug}
                </span>

                <span style={{ fontSize: 12, color: "rgba(229,231,235,0.5)" }}>
                  {fmtDate(t.created_at)}
                </span>

                {/* VAPI number cell */}
                <div>
                  {editingVapiSlug === t.slug ? (
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <input
                        type="text"
                        value={vapiInput}
                        onChange={(e) => setVapiInput(e.target.value)}
                        placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                        style={{ ...inputStyle, fontSize: 12, padding: "6px 10px" }}
                        autoFocus
                      />
                      <button
                        onClick={() => saveVapiNumber(t.slug, vapiInput)}
                        disabled={vapiSaving}
                        style={{ ...btnGhost, fontSize: 12 }}
                      >
                        {vapiSaving ? "…" : "Save"}
                      </button>
                      <button
                        onClick={() => { setEditingVapiSlug(null); setVapiInput(""); setVapiErr(""); }}
                        style={{ ...btnGhost, fontSize: 12 }}
                      >
                        ✕
                      </button>
                    </div>
                  ) : (
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      {t.twilio_number ? (
                        <span style={{ fontSize: 11, color: "#6ee7b7", fontFamily: "monospace" }}>
                          {t.twilio_number.slice(0, 8)}…
                        </span>
                      ) : (
                        <span style={{ fontSize: 11, color: "rgba(229,231,235,0.25)" }}>Not assigned</span>
                      )}
                      <button
                        onClick={() => { setEditingVapiSlug(t.slug); setVapiInput(t.twilio_number || ""); setVapiErr(""); }}
                        style={{ ...btnGhost, fontSize: 11, padding: "4px 10px" }}
                      >
                        {t.twilio_number ? "Edit" : "Assign"}
                      </button>
                      {t.twilio_number && (
                        <button
                          onClick={() => saveVapiNumber(t.slug, "")}
                          style={{ ...btnRed, fontSize: 11, padding: "4px 10px" }}
                        >
                          Clear
                        </button>
                      )}
                    </div>
                  )}
                </div>

                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <button
                    onClick={() => setRemovingTenant(t)}
                    style={btnRed}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
