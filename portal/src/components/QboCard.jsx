import React, { useEffect, useState } from "react";

export default function QBOCard({ baseUrl, tenantKey, commonHeaders }) {
  const [status, setStatus] = useState({
    connected: false,
    minutes_left: null,
    realmId: "",
    scopes: "",
    env: "",
    tenant: "", // server may return this
  });
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState("");

  // Simple date range (defaults: this month -> today)
  const todayISO = () => new Date().toISOString().slice(0, 10);
  const monthStartISO = () => {
    const d = new Date();
    d.setDate(1);
    return d.toISOString().slice(0, 10);
  };
  const [start, setStart] = useState(monthStartISO());
  const [end, setEnd] = useState(todayISO());

  async function fetchStatus() {
    try {
      const r = await fetch(
        `${baseUrl}/qbo/status?tenant=${encodeURIComponent(tenantKey)}`,
        { headers: commonHeaders }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setStatus(j);
      setNote("");
    } catch (e) {
      setNote(`Status error: ${String(e)}`);
    }
  }

  useEffect(() => { fetchStatus(); /* eslint-disable-next-line */ }, []);

  // ---- Connect flow (opens Intuit login) ----
  function startConnect() {
  // Try the path your server actually has
  const u = `${baseUrl}/qbo/connect?tenant=${encodeURIComponent("default")}&ngrok-skip-browser-warning=1`;
  window.location.href = u;
}


  async function disconnect() {
    setLoading(true);
    try {
      const r = await fetch(
        `${baseUrl}/qbo/disconnect?tenant=${encodeURIComponent(tenantKey)}`,
        { method: "POST", headers: commonHeaders }
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await fetchStatus();
    } catch (e) {
      setNote(`Disconnect error: ${String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  async function manualRefresh() {
    setLoading(true);
    try {
      await fetch(
        `${baseUrl}/qbo/refresh?tenant=${encodeURIComponent(tenantKey)}`,
        { method: "POST", headers: commonHeaders }
      );
      await fetchStatus();
    } catch (e) {
      setNote(`Refresh error: ${String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  // ---- One-click export to QBO ----
  async function exportToQBO() {
    setLoading(true);
    setNote("");
    try {
      const url = `${baseUrl}/finance/qbo/export/commit?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
      const res = await fetch(url, { method: "POST", headers: commonHeaders });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j?.detail || `HTTP ${res.status}`);
      alert(`✅ Exported ${j.committed?.revenues_exported ?? 0} revenues & ${j.committed?.costs_exported ?? 0} costs to QuickBooks.`);
    } catch (e) {
      setNote(`Export error: ${String(e)}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginBottom:16 }}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
        <h2 style={{ margin:0 }}>QuickBooks Online</h2>
        <span style={{ fontSize:12, color:"#6b7280" }}>{status.env || ""}</span>
      </div>

      <div style={{ marginTop:8, fontSize:14 }}>
        <div><strong>Status:</strong> {status.connected ? "Connected" : "Not connected"}</div>
        {!!status.tenant && <div><strong>Tenant:</strong> {status.tenant}</div>}
        {status.connected && (
          <>
            <div><strong>RealmId:</strong> {status.realmId}</div>
            <div><strong>Minutes left:</strong> {status.minutes_left ?? "-"}</div>
            <div><strong>Scopes:</strong> {status.scopes}</div>
          </>
        )}
      </div>

      {!!note && <div style={{ marginTop:8, color:"#b91c1c", fontSize:13 }}>{note}</div>}

      <div style={{ marginTop:12, display:"flex", gap:8, flexWrap:"wrap" }}>
        {!status.connected ? (
          <button onClick={startConnect} disabled={loading}>Connect QuickBooks</button>
        ) : (
          <>
            <button onClick={manualRefresh} disabled={loading}>Refresh Token</button>
            <button onClick={disconnect} disabled={loading}>Disconnect</button>
          </>
        )}
        <button onClick={fetchStatus} disabled={loading}>Check Status</button>
      </div>

      {/* Export controls */}
      <div style={{ marginTop:16, paddingTop:12, borderTop:"1px solid #eee" }}>
        <div style={{ fontWeight:600, marginBottom:8 }}>Export Finance Data to QuickBooks</div>
        <div style={{ display:"flex", gap:8, alignItems:"center", flexWrap:"wrap" }}>
          <label>Start</label>
          <input type="date" value={start} onChange={e=>setStart(e.target.value)} />
          <label>End</label>
          <input type="date" value={end} onChange={e=>setEnd(e.target.value)} />
          <button onClick={exportToQBO} disabled={!status.connected || loading}>
            Export to QuickBooks
          </button>
        </div>
        <div style={{ marginTop:6, fontSize:12, color:"#6b7280" }}>
          Uses <code>/finance/qbo/export/commit</code> on your API for the selected range.
        </div>
      </div>

      <div style={{ marginTop:8, fontSize:12, color:"#6b7280" }}>
        Auto-refresh also runs on the server at <code>/qbo/refresh-if-needed</code>.
      </div>
    </div>
  );
}
