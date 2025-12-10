import { useEffect, useState } from "react";

const BASE_URL = "/api";        // Vite proxy -> FastAPI
const TENANT_KEY = "devkey";    // switch to "acmekey" to see that tenant

export default function App() {
  // form state
  const [revAmount, setRevAmount] = useState("");
  const [revSource, setRevSource] = useState("");
  const [revNotes,  setRevNotes ] = useState("");

  const [costAmount,   setCostAmount]   = useState("");
  const [costCategory, setCostCategory] = useState("");
  const [costVendor,   setCostVendor]   = useState("");
  const [costNotes,    setCostNotes]    = useState("");

  // view & data
  const [view, setView] = useState("month"); // "today" | "month"
  const [summary, setSummary] = useState(null);
  const [recent,  setRecent]  = useState({ revenue: [], costs: [] });

  const [loading, setLoading]   = useState("");
  const [lastResult, setLastResult] = useState(null);

  // helpers
  function headers(json=false) {
    const h = { "x-api-key": TENANT_KEY };
    if (json) h["Content-Type"] = "application/json";
    return h;
  }
  async function postJSON(path, body) {
    const res = await fetch(`${BASE_URL}${path}`, { method: "POST", headers: headers(true), body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }
  async function getJSON(path) {
    const res = await fetch(`${BASE_URL}${path}`, { headers: headers() });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }
  async function delJSON(path) {
    const res = await fetch(`${BASE_URL}${path}`, { method: "DELETE", headers: headers() });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  // actions
  const addRevenue = async () => {
    try {
      if (!revAmount) return alert("Enter revenue amount");
      setLoading("Adding revenue…");
      const out = await postJSON("/finance/revenue", {
        amount: Number(revAmount),
        source: revSource || "unspecified",
        notes:  revNotes  || "",
      });
      setLastResult(out);
      setRevAmount(""); setRevSource(""); setRevNotes("");
      await refreshAll();
    } catch (e) { setLastResult({ error: String(e) }); }
    finally { setLoading(""); }
  };

  const addCost = async () => {
    try {
      if (!costAmount) return alert("Enter cost amount");
      setLoading("Adding cost…");
      const out = await postJSON("/finance/cost", {
        amount: Number(costAmount),
        category: costCategory || "unspecified",
        vendor:   costVendor   || "",
        notes:    costNotes    || "",
      });
      setLastResult(out);
      setCostAmount(""); setCostCategory(""); setCostVendor(""); setCostNotes("");
      await refreshAll();
    } catch (e) { setLastResult({ error: String(e) }); }
    finally { setLoading(""); }
  };

  const loadTotals = async () => {
    setLoading("Loading totals…");
    try {
      if (view === "today") {
        const d = new Date().toISOString().slice(0,10);
        const out = await getJSON(`/finance/pnl_day?date=${d}`);
        setSummary({
          revenue_total: out.revenue_total ?? out.revenue ?? "0",
          cost_total:    out.cost_total    ?? out.costs   ?? "0",
          gross_profit:  out.gross_profit  ?? out.profit  ?? "0",
          margin_pct:    out.margin_pct    ?? "0",
          label: `Today (${d})`,
        });
      } else {
        const out = await getJSON("/finance/summary?range=month");
        setSummary({ ...out, label: "This month" });
      }
    } catch (e) {
      setSummary(null); setLastResult({ error: String(e) });
    } finally { setLoading(""); }
  };

  const loadRecent = async () => {
    try {
      const res = await fetch(`${BASE_URL}/debug/finance/recent`, { headers: headers() });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      setRecent(await res.json());
    } catch (e) {
      setLastResult({ error: String(e) });
    }
  };

  const deleteRev  = async (id) => { try { await delJSON(`/debug/finance/revenue/${id}`); await refreshAll(); } catch (e) { setLastResult({ error: String(e) }); } };
  const deleteCost = async (id) => { try { await delJSON(`/debug/finance/cost/${id}`);     await refreshAll(); } catch (e) { setLastResult({ error: String(e) }); } };

  const refreshAll = async () => { await Promise.all([loadTotals(), loadRecent()]); };

  useEffect(() => { refreshAll(); }, [view]);
  useEffect(() => { refreshAll(); }, []);

  return (
    <div style={{maxWidth: 940, margin: "0 auto", padding: 16, fontFamily: "system-ui, sans-serif"}}>
      <h1 style={{fontSize: 24, fontWeight: 700, marginBottom: 12}}>TEST MARK 123 — Customer Portal</h1>

      {/* Totals View */}
      <section style={{border:"1px solid #ddd", borderRadius:8, padding:12, marginBottom:16}}>
        <h2 style={{margin:0, marginBottom:8}}>Totals View</h2>
        <label style={{marginRight:12}}>
          <input type="radio" checked={view==="today"} onChange={()=>setView("today")} /> Today
        </label>
        <label>
          <input type="radio" checked={view==="month"} onChange={()=>setView("month")} /> Month
        </label>
        <div style={{marginTop:10}}>
          {summary && (
            <div>
              <div style={{opacity:0.7}}>{summary.label || ""}</div>
              <div>Revenue: <b>{summary.revenue_total}</b></div>
              <div>Costs: <b>{summary.cost_total}</b></div>
              <div>Profit: <b>{summary.gross_profit}</b></div>
              <div>Margin: <b>{summary.margin_pct}%</b></div>
            </div>
          )}
        </div>
      </section>

      {/* Add Revenue */}
      <section style={{border:"1px solid #ddd", borderRadius:8, padding:12, marginBottom:16}}>
        <h2 style={{margin:0, marginBottom:8}}>Add Revenue</h2>
        <div style={{display:"grid", gap:8, maxWidth:420}}>
          <input value={revAmount} onChange={e=>setRevAmount(e.target.value)} placeholder="Amount" />
          <input value={revSource} onChange={e=>setRevSource(e.target.value)} placeholder="Source (install, service…)" />
          <input value={revNotes}  onChange={e=>setRevNotes(e.target.value)}  placeholder="Notes" />
          <button onClick={addRevenue}>Save Revenue</button>
        </div>
      </section>

      {/* Add Cost */}
      <section style={{border:"1px solid #ddd", borderRadius:8, padding:12, marginBottom:16}}>
        <h2 style={{margin:0, marginBottom:8}}>Add Cost</h2>
        <div style={{display:"grid", gap:8, maxWidth:420}}>
          <input value={costAmount} onChange={e=>setCostAmount(e.target.value)} placeholder="Amount" />
          <input value={costCategory} onChange={e=>setCostCategory(e.target.value)} placeholder="Category (parts, labor…)" />
          <input value={costVendor} onChange={e=>setCostVendor(e.target.value)} placeholder="Vendor" />
          <input value={costNotes}  onChange={e=>setCostNotes(e.target.value)}  placeholder="Notes" />
          <button onClick={addCost}>Save Cost</button>
        </div>
      </section>

      {/* Recent Entries (Undo) */}
      <section style={{border:"1px solid #ddd", borderRadius:8, padding:12, marginBottom:16}}>
        <h2 style={{margin:0, marginBottom:8}}>Recent Entries (click Delete to undo mistakes)</h2>
        <div style={{display:"grid", gap:8}}>
          {recent.revenue.map(r => (
            <div key={`rev-${r.id}`} style={{display:"flex", gap:8, alignItems:"center", flexWrap:"wrap"}}>
              <span style={{minWidth:60, fontWeight:600}}>Rev</span>
              <span>#{r.id}</span>
              <span>${r.amount}</span>
              <span>{r.source || ""}</span>
              <span style={{opacity:0.7}}>{r.notes || ""}</span>
              <button onClick={()=>deleteRev(r.id)}>Delete</button>
            </div>
          ))}
          {recent.costs.map(c => (
            <div key={`cost-${c.id}`} style={{display:"flex", gap:8, alignItems:"center", flexWrap:"wrap"}}>
              <span style={{minWidth:60, fontWeight:600}}>Cost</span>
              <span>#{c.id}</span>
              <span>${c.amount}</span>
              <span>{c.category || ""}</span>
              <span style={{opacity:0.7}}>{c.vendor || ""}</span>
              <button onClick={()=>deleteCost(c.id)}>Delete</button>
            </div>
          ))}
        </div>
      </section>

      {loading && <div style={{marginBottom:8}}>{loading}</div>}
      {lastResult && (
        <pre style={{background:"#111", color:"#fff", padding:12, borderRadius:8, overflow:"auto"}}>
{JSON.stringify(lastResult, null, 2)}
        </pre>
      )}
    </div>
  );
}
