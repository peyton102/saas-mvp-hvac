import { useEffect, useMemo, useState } from "react";
const BASE = "/api";

export default function NumbersCallsCard({ tenantKey }) {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [provisioning, setProvisioning] = useState(false);
  const headers = useMemo(() => ({
    "Content-Type": "application/json",
    "X-API-Key": tenantKey,
  }), [tenantKey]);

  async function apiFetch(path, opts = {}) {
    const res = await fetch(`${BASE}${path}`, { ...opts, headers: { ...headers, ...(opts.headers||{}) } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function load() {
    setLoading(true);
    try {
      // Assumes your backend exposes current config here:
      // e.g. { phone_number:"+1xxx", phone_sid:"PN...", messaging_service_sid:"MG...", tf_verification_status:"unsubmitted" }
      const data = await apiFetch("/settings/numbers");
      setInfo(data);
    } catch (e) {
      setInfo(null);
    } finally {
      setLoading(false);
    }
  }

  async function provision() {
    if (!confirm("Provision a Toll-Free number and wire webhooks now?")) return;
    setProvisioning(true);
    try {
      await apiFetch("/onboarding/tollfree", { method: "POST", body: JSON.stringify({}) });
      await load();
      alert("Number assigned.");
    } catch (e) {
      console.error(e);
      alert("Provisioning failed. Check API logs.");
    } finally {
      setProvisioning(false);
    }
  }

  useEffect(() => { load(); }, []);

  return (
    <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginBottom:16 }}>
      <h2 style={{ margin:0 }}>Settings ▸ Numbers & Calls</h2>
      {loading ? (
        <div style={{ marginTop:8 }}>Loading…</div>
      ) : (
        <>
          {info ? (
            <div style={{ marginTop:8, display:"grid", gap:6 }}>
              <div><strong>Assigned Number:</strong> {info.phone_number || "(none)"}{info.phone_number ? "" : ""}</div>
              <div><strong>Messaging Service SID:</strong> {info.messaging_service_sid || "(none)"}</div>
              <div><strong>Phone SID:</strong> {info.phone_sid || "(none)"}</div>
              <div><strong>TF Verification Status:</strong> {info.tf_verification_status || "unsubmitted"}</div>
            </div>
          ) : (
            <div style={{ marginTop:8 }}>
              <div style={{ marginBottom:8, color:"#6b7280" }}>
                No texting line yet. Click below to assign a Toll-Free number and wire webhooks.
              </div>
              <button onClick={provision} disabled={provisioning}>
                {provisioning ? "Provisioning…" : "Get My Texting Line"}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
