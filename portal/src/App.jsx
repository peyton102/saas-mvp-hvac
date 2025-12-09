import React, { useEffect, useMemo, useState } from "react";
import LeadsCard from "./components/LeadsCard.jsx";
import NumbersCallsCard from "./components/NumbersCallsCard.jsx";
import BookingBlank from "./components/BookingsCard.jsx";
import LoginPage from "./LoginPage";
import TenantSettingsCard from "./components/TenantSettingsCard.jsx";
import { getToken, setToken, clearToken } from "./auth";

// ====== CONFIG ======
const API_BASE =
  import.meta?.env?.VITE_API_BASE ||
  "https://saas-mvp-hvac.onrender.com";   // 👈 fallback to Render backend

const BASE = API_BASE;

const params = new URLSearchParams(window.location.search || "");
const TENANT_KEY = params.get("tenant") || "default";   // 👈 read from ?tenant=
const NGROK_HEADER = { "ngrok-skip-browser-warning": "true" };
// use same base for auth for now



// ====== HELPERS ======
function fmtMoney(n) {
  if (n === null || n === undefined) return "0";
  const num = Number(n);
  return isNaN(num) ? n : num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtNum(n) {
  const num = Number(n ?? 0);
  return isNaN(num) ? "0.00" : num.toFixed(2);
}
function todayISO() { return new Date().toISOString().slice(0, 10); }
function startOfMonthISO() { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); }

function PortalApp({ me }) {
  const [tab, setTab] = useState("home");
  const [apiHealth, setApiHealth] = useState("checking…");
  const [includeRevenue, setIncludeRevenue] = useState(true);
  const [includeCost, setIncludeCost] = useState(true);
  const needsSetup = me?.needs_setup;
  const token = getToken();

  function handleLogout() {
    clearToken();
    window.location.href = "/"; // force full reload to login screen
  }
  function computeCsvDates() {
  if (rangeKey === "today") {
    const d = todayISO();
    return { start: d, end: d };
  }
  if (rangeKey === "month") {
    return { start: startOfMonthISO(), end: todayISO() };
  }
  // custom
  return { start: customStart, end: customEnd };
}

async function exportFinanceCsv() {
  const { start, end } = computeCsvDates();

  const url =
    `${BASE}/finance/export/csv` +
    `?start=${encodeURIComponent(start)}` +
    `&end=${encodeURIComponent(end)}` +
    `&include_revenue=${includeRevenue}` +
    `&include_cost=${includeCost}`;

  try {
    const res = await fetch(url, {
      headers: {
        ...headers,                // 👈 includes Authorization: Bearer <token>
        Accept: "text/csv",
      },
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const blob = await res.blob();
    const downloadUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `finance_export_${start}_${end}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(downloadUrl);
  } catch (e) {
    console.error("CSV export failed", e);
    alert("Could not export CSV. Please try again.");
  }
}


  // ====== API health ping (hits BASE directly) ======
  useEffect(() => {
    async function ping() {
      try {
        const r = await fetch(`${BASE}/health`, { headers: NGROK_HEADER });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        setApiHealth(`OK (env=${j.env})`);
      } catch (e) {
        setApiHealth(`ERROR: ${String(e)}`);
      }
    }
    ping();
  }, []);

  // ====== Finance state ======
  const [rangeKey, setRangeKey] = useState("month");
  const [customStart, setCustomStart] = useState(todayISO());
  const [customEnd, setCustomEnd] = useState(todayISO());
  const [summary, setSummary] = useState(null);
  const [partsRows, setPartsRows] = useState([]);
  const [recent, setRecent] = useState({ revenue: [], costs: [] });
  const [loading, setLoading] = useState(false);

  // optional columns
  const [showHours, setShowHours] = useState(false);
  const [showLaborCost, setShowLaborCost] = useState(false);

const headers = useMemo(() => {
  const h = {
    ...NGROK_HEADER,
    "Content-Type": "application/json",
  };

  // ✅ Always send API key fallback for tenant auth
  const apiKey = localStorage.getItem("API_KEY") || "devkey";
  h["X-API-Key"] = apiKey;

  // ✅ If user is logged in, ALSO send bearer
  if (token) {
    h["Authorization"] = `Bearer ${token}`;
  }

  return h;
}, [token]);




  // Central API fetch that always talks to ngrok + carries headers
  async function apiFetch(path, opts = {}) {
    const res = await fetch(`${BASE}${path}`, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
    if (!res.ok) {
      const msg = `HTTP ${res.status} for ${path}`;
      console.error(msg);
      throw new Error(msg);
    }
    return res.json();
  }

  // ====== Finance data loaders ======
  async function loadSummary() {
    if (rangeKey === "custom") { setSummary(null); return; }
    const data = await apiFetch(`/finance/summary?range=${rangeKey}`);
    setSummary(data);
  }

  function computeDates() {
    if (rangeKey === "today") {
      const d = todayISO();
      return { start: `${d}T00:00:00`, end: `${d}T23:59:59` };
    }
    if (rangeKey === "month") {
      const s = startOfMonthISO();
      const e = todayISO();
      return { start: `${s}T00:00:00`, end: `${e}T23:59:59` };
    }
    // custom
    return { start: `${customStart}T00:00:00+00:00`, end: `${customEnd}T23:59:59+00:00` };
  }

  async function loadParts() {
    const { start, end } = computeDates();
    const data = await apiFetch(`/finance/parts_summary?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
    setPartsRows(data.rows || []);
  }

  async function loadRecent() {
    const data = await apiFetch(`/debug/finance/recent?limit=50`);
    setRecent({ revenue: data.revenue || [], costs: data.costs || [] });
  }

  async function refreshAll() {
    setLoading(true);
    try {
      await Promise.all([loadSummary(), loadParts(), loadRecent()]);
    } catch (e) {
      console.error(e);
      alert("API not reachable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refreshAll(); /* eslint-disable-next-line */ }, [rangeKey]);
  useEffect(() => { if (rangeKey === "custom") refreshAll(); /* eslint-disable-next-line */ }, [customStart, customEnd]);

  // ====== Finance forms ======
  const [revForm, setRevForm] = useState({ amount: "", source: "", part_code: "", job_type: "", notes: "" });
  const [costForm, setCostForm] = useState({
    amount: "", category: "", vendor: "",
    part_code: "", job_type: "", notes: "",
    hours: "", hourly_rate: ""
  });

  async function submitRevenue(e) {
    e.preventDefault();
    await apiFetch(`/finance/revenue`, { method: "POST", body: JSON.stringify(revForm) });
    setRevForm({ amount: "", category: "", vendor: "", part_code: "", job_type: "", notes: "" });
    refreshAll();
  }
  async function submitCost(e) {
    e.preventDefault();
    await apiFetch(`/finance/cost`, { method: "POST", body: JSON.stringify(costForm) });
    setCostForm({ amount: "", category: "", vendor: "", part_code: "", job_type: "", notes: "", hours: "", hourly_rate: "" });
    refreshAll();
  }

  async function deleteRev(id) {
    if (!confirm(`Delete revenue #${id}?`)) return;
    await apiFetch(`/debug/finance/revenue/${id}`, { method: "DELETE" });
    refreshAll();
  }
  async function deleteCost(id) {
    if (!confirm(`Delete cost #${id}?`)) return;
    await apiFetch(`/debug/finance/cost/${id}`, { method: "DELETE" });
    refreshAll();
  }

  // ====== QBO export (added) ======
  const [qboStart, setQboStart] = useState(startOfMonthISO());
  const [qboEnd, setQboEnd] = useState(todayISO());
  const [qboNote, setQboNote] = useState("");

  async function qboPlan() {
    setQboNote("Planning…");
    try {
      const j = await apiFetch(`/finance/qbo/export/plan?start=${qboStart}&end=${qboEnd}`, { method: "POST" });
      setQboNote(`Preview: ${j.plan.counts.revenues} revenues, ${j.plan.counts.costs} costs. Gross Profit: $${fmtMoney(j.plan.totals.gross_profit)}`);
    } catch (e) {
      setQboNote(`Plan error: ${String(e)}`);
    }
  }

  async function qboCommit() {
    setQboNote("Exporting…");
    try {
      const j = await apiFetch(`/finance/qbo/export/commit?start=${qboStart}&end=${qboEnd}`, { method: "POST" });
      setQboNote(`Exported ${j.committed.revenues_exported} revenues & ${j.committed.costs_exported} costs to QBO.`);
    } catch (e) {
      setQboNote(`Export error: ${String(e)}`);
    }
  }

      return (
    <div style={{ padding: 16, fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Arial" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h1 style={{ margin: 0 }}>Welcome to Torevez</h1>
        <button
          onClick={handleLogout}
          style={{
            padding: "4px 10px",
             color: "#111827",
            fontSize: 13,
            borderRadius: 6,
            border: "1px solid #9CA3AF",
            background: "#E5E7EB",
            cursor: "pointer",
          }}
        >
          Log out
        </button>
      </div>


      {needsSetup && (
        <div
          style={{
            marginBottom: 12,
            padding: 12,
            borderRadius: 8,
            background: "#FEF3C7",
            border: "1px solid #FBBF24",
            color: "#92400E",
            fontSize: 14,
          }}
        >
          <strong>Finish your setup:</strong>{" "}
          Fill out your business phone, email, and review link in the Settings card below so reminders and messages go
          to the right place.
          <button
  type="button"
  onClick={() => {
    setTab("settings");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }}
  style={{
    marginLeft: 8,
    padding: "4px 10px",
    borderRadius: 6,
    border: "1px solid #92400E",
    background: "#FCD34D",
    cursor: "pointer",
    fontSize: 13,
  }}
>
  Go to settings
</button>

        </div>
      )}

      {/* Settings card */}
      <div id="tenant-settings">
        <NumbersCallsCard tenantKey={TENANT_KEY} />
      </div>


      <div style={{ display:"flex", gap:8, margin:"8px 0 16px" }}>
        <button onClick={()=>setTab("home")}    disabled={tab==="home"}>Home</button>
        <button onClick={()=>setTab("finance")} disabled={tab==="finance"}>Finance</button>
        <button onClick={()=>setTab("leads")}   disabled={tab==="leads"}>Leads</button>
        <button onClick={()=>setTab("bookings")} disabled={tab==="bookings"}>Bookings</button>
         <button onClick={()=>setTab("settings")} disabled={tab==="settings"}>Settings</button>
      </div>

      {tab==="bookings" && (
        <BookingBlank
          tenantKey={TENANT_KEY}
          tenantSlug={TENANT_KEY}   // 👈 match the URL tenant
          apiBase={API_BASE}
          commonHeaders={headers}
        />
      )}

      {tab==="home" && (
        <div style={{ display:"grid", gap:12 }}>
          <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16 }}>
            <h2 style={{ margin:0 }}>Welcome</h2>
            <p style={{ marginTop:8 }}>Choose a section above to get started.</p>
          </div>
        </div>
      )}
{tab === "settings" && (
  <TenantSettingsCard apiBase={BASE} commonHeaders={headers} />
)}

      {tab==="finance" && (
        <>
          {/* Totals range */}
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
            <label>Totals View:</label>
            <select value={rangeKey} onChange={(e)=>setRangeKey(e.target.value)}>
              <option value="today">Today</option>
              <option value="month">Month</option>
              <option value="custom">Custom</option>
            </select>
            {rangeKey === "custom" && (
              <>
                <label>Start</label>
                <input type="date" value={customStart} onChange={(e)=>setCustomStart(e.target.value)} />
                <label>End</label>
                <input type="date" value={customEnd} onChange={(e)=>setCustomEnd(e.target.value)} />
              </>
            )}
          </div>

          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 12, marginBottom: 16 }}>
            <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16 }}>
              <div style={{ color:"#6b7280", fontSize:12 }}>Revenue</div>
              <div style={{ fontSize:24, fontWeight:600 }}>${fmtMoney(summary?.revenue_total||"0")}</div>
            </div>
            <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16 }}>
              <div style={{ color:"#6b7280", fontSize:12 }}>Costs</div>
              <div style={{ fontSize:24, fontWeight:600 }}>${fmtMoney(summary?.cost_total||"0")}</div>
            </div>
            <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16 }}>
              <div style={{ color:"#6b7280", fontSize:12 }}>Profit / Margin</div>
              <div style={{ fontSize:24, fontWeight:600 }}>
                ${fmtMoney(summary?.gross_profit||"0")} • {summary?.margin_pct ?? "0"}%
              </div>
            </div>
          </div>

          {/* labor totals */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12, marginBottom: 16 }}>
            <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16 }}>
              <div style={{ color:"#6b7280", fontSize:12 }}>Labor (This View)</div>
              <div style={{ fontSize:18, fontWeight:600 }}>
                Hours: {fmtNum(summary?.labor_hours)} &nbsp;•&nbsp; Cost: ${fmtMoney(summary?.labor_total)}
              </div>
            </div>
          </div>

          {/* CSV Export controls */}
          <div style={{ display:"flex", gap:12, alignItems:"center", margin:"8px 0 12px" }}>
            <label style={{ display:"flex", gap:6, alignItems:"center" }}>
              <input
                type="checkbox"
                checked={includeRevenue}
                onChange={e=>setIncludeRevenue(e.target.checked)}
              />
              Include Revenue
            </label>
            <label style={{ display:"flex", gap:6, alignItems:"center" }}>
              <input
                type="checkbox"
                checked={includeCost}
                onChange={e=>setIncludeCost(e.target.checked)}
              />
              Include Costs
            </label>

            <button onClick={exportFinanceCsv}>Export CSV</button>
          </div>

          {/* add revenue / cost */}
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12, marginBottom:16 }}>
            <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16 }}>
              <h2 style={{ margin:0 }}>Add Revenue</h2>
              <form onSubmit={submitRevenue} style={{ display:"grid", gap:8, marginTop:8 }}>
                <input placeholder="Amount" value={revForm.amount} onChange={e=>setRevForm(f=>({...f,amount:e.target.value}))}/>
                <input placeholder="Source" value={revForm.source} onChange={e=>setRevForm(f=>({...f,source:e.target.value}))}/>
                <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8 }}>
                  <input placeholder="Part Code" value={revForm.part_code} onChange={e=>setRevForm(f=>({...f,part_code:e.target.value}))}/>
                  <input placeholder="Job Type" value={revForm.job_type} onChange={e=>setRevForm(f=>({...f,job_type:e.target.value}))}/>
                </div>
                <input placeholder="Notes" value={revForm.notes} onChange={e=>setRevForm(f=>({...f,notes:e.target.value}))}/>
                <button type="submit">Save Revenue</button>
              </form>
            </div>

            <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16 }}>
              <h2 style={{ margin:0 }}>Add Cost</h2>
              <form onSubmit={submitCost} style={{ display:"grid", gap:8, marginTop:8 }}>
                <input placeholder="Amount" value={costForm.amount} onChange={e=>setCostForm(f=>({...f,amount:e.target.value}))}/>
                <input placeholder="Category" value={costForm.category} onChange={e=>setCostForm(f=>({...f,category:e.target.value}))}/>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  <input placeholder="Hours (e.g. 3.5)" value={costForm.hours} onChange={e=>setCostForm(f=>({...f, hours: e.target.value}))} />
                  <input placeholder="Hourly Rate (e.g. 45)" value={costForm.hourly_rate} onChange={e=>setCostForm(f=>({...f, hourly_rate: e.target.value}))} />
                </div>
                <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8 }}>
                  <input placeholder="Part Code" value={costForm.part_code} onChange={e=>setCostForm(f=>({...f,part_code:e.target.value}))}/>
                  <input placeholder="Job Type" value={costForm.job_type} onChange={e=>setCostForm(f=>({...f,job_type:e.target.value}))}/>
                </div>
                <input placeholder="Vendor (optional)" value={costForm.vendor} onChange={e=>setCostForm(f=>({...f,vendor:e.target.value}))}/>
                <input placeholder="Notes" value={costForm.notes} onChange={e=>setCostForm(f=>({...f,notes:e.target.value}))}/>
                <button type="submit">Save Cost</button>
              </form>
            </div>
          </div>

          {/* recent entries */}
          <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginBottom:16 }}>
            <h2 style={{ margin:"0 0 8px" }}>Recent Entries</h2>
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
              <div>
                <h3 style={{ margin:"0 0 6px", fontSize:14 }}>Revenue</h3>
                <div style={{ maxHeight:240, overflow:"auto", borderTop:"1px solid #f3f4f6" }}>
                  <table style={{ width:"100%", fontSize:14, borderCollapse:"collapse" }}>
                    <thead><tr><th>ID</th><th>Amt</th><th>Source</th><th>Part/Job</th><th></th></tr></thead>
                    <tbody>
                      {recent.revenue.map(r=>(
                        <tr key={r.id}><td>{r.id}</td><td>${fmtMoney(r.amount)}</td><td>{r.source}</td>
                        <td>{r.part_code}/{r.job_type}</td>
                        <td><button onClick={()=>deleteRev(r.id)}>Delete</button></td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div>
                <h3 style={{ margin:"0 0 6px", fontSize:14 }}>Costs</h3>
                <div style={{ maxHeight:240, overflow:"auto", borderTop:"1px solid #f3f4f6" }}>
                  <table style={{ width:"100%", fontSize:14, borderCollapse:"collapse" }}>
                    <thead><tr><th>ID</th><th>Amt</th><th>Category</th><th>Part/Job</th><th></th></tr></thead>
                    <tbody>
                      {recent.costs.map(c=>(
                        <tr key={c.id}><td>{c.id}</td><td>${fmtMoney(c.amount)}</td><td>{c.category}</td>
                        <td>{c.part_code}/{c.job_type}</td>
                        <td><button onClick={()=>deleteCost(c.id)}>Delete</button></td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          {/* parts summary */}
          <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginBottom:24 }}>
            <h2 style={{ margin:"0 0 8px" }}>Parts Performance</h2>

            <div style={{ display:"flex", gap:12, alignItems:"center", marginBottom:8 }}>
              <label style={{ display:"flex", gap:6, alignItems:"center" }}>
                <input type="checkbox" checked={showHours} onChange={e=>setShowHours(e.target.checked)} />
                Show Hours
              </label>
              <label style={{ display:"flex", gap:6, alignItems:"center" }}>
                <input type="checkbox" checked={showLaborCost} onChange={e=>setShowLaborCost(e.target.checked)} />
                Show Labor Cost
              </label>
            </div>

            <div style={{ overflow:"auto", borderTop:"1px solid #f3f4f6" }}>
              <table style={{ width:"100%", fontSize:14, borderCollapse:"collapse" }}>
                <thead>
                  <tr>
                    <th>Part</th>
                    <th>Job</th>
                    {showHours && <th>Hours</th>}
                    {showLaborCost && <th>Labor Cost</th>}
                    <th>Revenue</th>
                    <th>Cost</th>
                    <th>Profit</th>
                    <th>Margin %</th>
                  </tr>
                </thead>
                <tbody>
                  {partsRows.map((r,i)=>(
                    <tr key={i}>
                      <td>{r.part_code}</td>
                      <td>{r.job_type}</td>
                      {showHours && <td>{fmtNum(r.hours_total)}</td>}
                      {showLaborCost && <td>${fmtMoney(r.labor_cost_total)}</td>}
                      <td>${fmtMoney(r.revenue_total)}</td>
                      <td>${fmtMoney(r.cost_total)}</td>
                      <td>${fmtMoney(r.profit)}</td>
                      <td>{r.margin_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {tab==="leads" && (
        <LeadsCard
          tenantKey={TENANT_KEY}
          apiBase={BASE}
          commonHeaders={headers}
        />
      )}
    </div>
  );
}

// ---------- Auth wrapper ----------

function App() {
  const [me, setMe] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

  async function fetchMe(token) {
    try {
      const resp = await fetch(`${API_BASE}/auth/me`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!resp.ok) {
        throw new Error("Not authenticated");
      }

      const data = await resp.json(); // { email, tenant_slug, needs_setup, ... }
      setMe(data);
    } catch (err) {
      console.error("auth/me error", err);
      clearToken();
      setMe(null);
    } finally {
      setAuthLoading(false);
    }
  }

  useEffect(() => {
    const token = getToken();
    if (token) {
      fetchMe(token);
    } else {
      setAuthLoading(false);
    }
  }, []);

  function handleLoggedIn(loginData) {
    // loginData: { access_token, tenant_slug, api_key }
    fetchMe(loginData.access_token);
  }

  if (authLoading) {
    return <div style={{ padding: 16 }}>Loading…</div>;
  }

  const token = getToken();
  if (!token || !me) {
    return <LoginPage onLoggedIn={handleLoggedIn} />;
  }

  // Logged-in: show the real portal
    // Logged-in: show the real portal
  return <PortalApp me={me} />;
}

export default App;
