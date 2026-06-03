// FILE: portal/src/components/FinanceCard.jsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// ── colour tokens — matches LeadsCard / BookingsCard exactly ─────────────────
const C = {
  bg:       "transparent",
  border:   "1px solid rgba(255,255,255,0.08)",
  text:     "#e5e7eb",
  muted:    "rgba(229,231,235,0.5)",
  accent:   "#f97316",
  rowEven:  "rgba(255,255,255,0.02)",
  rowHover: "rgba(249,115,22,0.06)",
  inputBg:  "rgba(255,255,255,0.06)",
  green:    "#4ade80",
  greenBg:  "rgba(74,222,128,0.12)",
  red:      "#f87171",
  redBg:    "rgba(248,113,113,0.12)",
  purple:   "#a78bfa",
};

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtMoney(n) {
  if (n === null || n === undefined) return "0.00";
  const num = Number(n);
  return isNaN(num)
    ? String(n)
    : num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}
function startOfMonthISO() {
  const d = new Date();
  d.setDate(1);
  return d.toISOString().slice(0, 10);
}

// RFC-4180 compliant CSV parser (handles quoted fields, commas inside quotes)
function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  if (!lines.length) return { headers: [], rows: [] };

  function parseLine(line) {
    const result = [];
    let cur = "";
    let inQuote = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (inQuote && line[i + 1] === '"') { cur += '"'; i++; }
        else inQuote = !inQuote;
      } else if (ch === "," && !inQuote) {
        result.push(cur.trim());
        cur = "";
      } else {
        cur += ch;
      }
    }
    result.push(cur.trim());
    return result;
  }

  const headers = parseLine(lines[0]);
  const rows = lines
    .slice(1)
    .filter((l) => l.trim())
    .map((l) => {
      const vals = parseLine(l);
      const obj = {};
      headers.forEach((h, i) => { obj[h] = vals[i] ?? ""; });
      return obj;
    });
  return { headers, rows };
}

// Auto-detect which header index best matches a semantic field
function autoDetect(headers, keywords) {
  const lowers = headers.map((h) => h.toLowerCase());
  const idx = lowers.findIndex((h) => keywords.some((k) => h.includes(k)));
  return idx >= 0 ? String(idx) : "";
}

// ── sub-components ────────────────────────────────────────────────────────────

function StatCard({ label, value, color }) {
  return (
    <div
      style={{
        background: "rgba(255,255,255,0.03)",
        border: C.border,
        borderRadius: 14,
        padding: "18px 20px",
      }}
    >
      <div
        style={{
          color: C.muted,
          fontSize: 11,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: 0.8,
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color }}>{value}</div>
    </div>
  );
}

// ── constants ─────────────────────────────────────────────────────────────────

const BLANK_REV  = { amount: "", source: "", part_code: "", job_type: "", notes: "" };
const BLANK_COST = { amount: "", category: "", vendor: "", part_code: "", job_type: "", notes: "", hours: "", hourly_rate: "" };

const inputStyle = {
  background: C.inputBg,
  border: C.border,
  borderRadius: 8,
  padding: "8px 12px",
  color: C.text,
  fontSize: 13,
  width: "100%",
  boxSizing: "border-box",
  outline: "none",
  fontFamily: "inherit",
};

const thStyle = {
  padding: "10px 12px",
  textAlign: "left",
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: 0.5,
  color: C.muted,
  textTransform: "uppercase",
  borderBottom: C.border,
  whiteSpace: "nowrap",
};

const tdStyle = { padding: "10px 12px", fontSize: 13 };

// ── main component ────────────────────────────────────────────────────────────

export default function FinanceCard({ apiBase, commonHeaders }) {
  const BASE = apiBase || "";

  const headers = useMemo(
    () => ({
      ...(commonHeaders || {}),
      "ngrok-skip-browser-warning": "true",
      "Content-Type": "application/json",
    }),
    [commonHeaders]
  );

  // ── date range ──
  const [rangeKey, setRangeKey]       = useState("month");
  const [customStart, setCustomStart] = useState(startOfMonthISO());
  const [customEnd, setCustomEnd]     = useState(todayISO());

  // ── data ──
  const [summary, setSummary] = useState(null);
  const [revenue, setRevenue] = useState([]);
  const [costs, setCosts]     = useState([]);
  const [loading, setLoading] = useState(false);

  // ── ui state ──
  const [activeTab, setActiveTab] = useState("revenue"); // "revenue" | "costs"
  const [addMode, setAddMode]     = useState(null);       // null | "manual_rev" | "manual_cost" | "csv"

  // ── forms ──
  const [revForm,  setRevForm]  = useState(BLANK_REV);
  const [costForm, setCostForm] = useState(BLANK_COST);

  // ── csv ──
  const [csvFile,      setCsvFile]      = useState(null);
  const [csvData,      setCsvData]      = useState(null);   // { headers, rows }
  const [csvMapping,   setCsvMapping]   = useState({});
  const [csvImporting, setCsvImporting] = useState(false);
  const [csvResult,    setCsvResult]    = useState(null);
  const fileRef = useRef();

  // ── api helper ──
  async function apiFetch(path, opts = {}) {
    const res = await fetch(`${BASE}${path}`, {
      ...opts,
      headers: { ...headers, ...(opts.headers || {}) },
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(txt || `HTTP ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  // ── date helpers ──
  function computeDates() {
    if (rangeKey === "today") {
      const d = todayISO();
      return { start: `${d}T00:00:00`, end: `${d}T23:59:59` };
    }
    if (rangeKey === "month") {
      return { start: `${startOfMonthISO()}T00:00:00`, end: `${todayISO()}T23:59:59` };
    }
    return { start: `${customStart}T00:00:00`, end: `${customEnd}T23:59:59` };
  }

  // ── data loading ──
  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [sumData, recentData] = await Promise.all([
        rangeKey !== "custom"
          ? apiFetch(`/finance/summary?range=${rangeKey}`)
          : Promise.resolve(null),
        apiFetch("/debug/finance/recent?limit=200"),
      ]);
      if (sumData) setSummary(sumData);
      setRevenue(recentData?.revenue || []);
      setCosts(recentData?.costs || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rangeKey, customStart, customEnd]);

  useEffect(() => { loadAll(); }, [rangeKey]);
  useEffect(() => { if (rangeKey === "custom") loadAll(); }, [customStart, customEnd]);

  // ── submit handlers ──
  async function submitRevenue(e) {
    e.preventDefault();
    try {
      await apiFetch("/finance/revenue", { method: "POST", body: JSON.stringify(revForm) });
      setRevForm(BLANK_REV);
      setAddMode(null);
      loadAll();
    } catch (err) { alert(`Error: ${err.message}`); }
  }

  async function submitCost(e) {
    e.preventDefault();
    try {
      await apiFetch("/finance/cost", { method: "POST", body: JSON.stringify(costForm) });
      setCostForm(BLANK_COST);
      setAddMode(null);
      loadAll();
    } catch (err) { alert(`Error: ${err.message}`); }
  }

  async function deleteRev(id) {
    if (!confirm(`Delete revenue #${id}?`)) return;
    try {
      await apiFetch(`/debug/finance/revenue/${id}`, { method: "DELETE" });
      setRevenue((prev) => prev.filter((r) => r.id !== id));
    } catch (err) { alert(`Error: ${err.message}`); }
  }

  async function deleteCost(id) {
    if (!confirm(`Delete cost #${id}?`)) return;
    try {
      await apiFetch(`/debug/finance/cost/${id}`, { method: "DELETE" });
      setCosts((prev) => prev.filter((c) => c.id !== id));
    } catch (err) { alert(`Error: ${err.message}`); }
  }

  // ── csv export ──
  async function exportCSV() {
    const { start, end } = computeDates();
    const url =
      `${BASE}/finance/export/csv` +
      `?start=${encodeURIComponent(start)}` +
      `&end=${encodeURIComponent(end)}` +
      `&include_revenue=true&include_cost=true`;
    try {
      const res = await fetch(url, { headers: { ...headers, Accept: "text/csv" } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `finance_${start}_to_${end}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) { alert(`Export failed: ${err.message}`); }
  }

  // ── csv import ──
  function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvFile(file);
    setCsvResult(null);
    const reader = new FileReader();
    reader.onload = (ev) => {
      const parsed = parseCSV(ev.target.result);
      setCsvData(parsed);
      const h = parsed.headers;
      setCsvMapping({
        amount:      autoDetect(h, ["amount", "total", "price", "subtotal", "invoice total"]),
        description: autoDetect(h, ["description", "source", "category", "item", "service", "memo"]),
        notes:       autoDetect(h, ["notes", "note", "comment", "remarks"]),
      });
    };
    reader.readAsText(file);
  }

  async function importCSV(entryType) {
    if (!csvData) return;
    setCsvImporting(true);
    setCsvResult(null);
    let ok = 0;
    let fail = 0;

    for (const row of csvData.rows) {
      try {
        const get = (idx) =>
          idx !== "" ? (row[csvData.headers[Number(idx)]] || "") : "";
        const rawAmount = get(csvMapping.amount).replace(/[$,\s]/g, "");
        const description = get(csvMapping.description);
        const notes = get(csvMapping.notes);

        if (!rawAmount || isNaN(Number(rawAmount))) { fail++; continue; }

        if (entryType === "revenue") {
          await apiFetch("/finance/revenue", {
            method: "POST",
            body: JSON.stringify({ amount: rawAmount, source: description, notes }),
          });
        } else {
          await apiFetch("/finance/cost", {
            method: "POST",
            body: JSON.stringify({ amount: rawAmount, category: description, notes }),
          });
        }
        ok++;
      } catch { fail++; }
    }

    setCsvImporting(false);
    setCsvResult({ ok, fail });
    if (ok > 0) { loadAll(); setActiveTab(entryType === "revenue" ? "revenue" : "costs"); }
  }

  // ── toggle add mode helpers ──
  function toggleManual() {
    const target = activeTab === "revenue" ? "manual_rev" : "manual_cost";
    setAddMode(addMode === target ? null : target);
  }
  function toggleCSV() {
    setAddMode(addMode === "csv" ? null : "csv");
  }

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <div
      style={{
        color: C.text,
        fontFamily: "system-ui, -apple-system, sans-serif",
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}
    >
      {/* ── Header ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>Finance</div>
          <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
            {revenue.length} revenue · {costs.length} cost entries
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <select
            value={rangeKey}
            onChange={(e) => setRangeKey(e.target.value)}
            style={{
              background: C.inputBg, border: C.border, borderRadius: 8,
              padding: "8px 12px", color: C.text, fontSize: 13, cursor: "pointer",
            }}
          >
            <option value="today">Today</option>
            <option value="month">This Month</option>
            <option value="custom">Custom Range</option>
          </select>

          {rangeKey === "custom" && (
            <>
              <input
                type="date" value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                style={{ ...inputStyle, width: "auto" }}
              />
              <span style={{ color: C.muted }}>→</span>
              <input
                type="date" value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                style={{ ...inputStyle, width: "auto" }}
              />
            </>
          )}

          <button
            onClick={exportCSV}
            style={{
              background: C.inputBg, border: C.border, borderRadius: 8,
              padding: "8px 14px", color: C.text, fontWeight: 600, fontSize: 13, cursor: "pointer",
            }}
          >
            Export CSV
          </button>
        </div>
      </div>

      {/* ── Stat cards ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
        <StatCard label="Revenue"      value={`$${fmtMoney(summary?.revenue_total)}`}  color={C.green}  />
        <StatCard label="Costs"        value={`$${fmtMoney(summary?.cost_total)}`}      color={C.red}    />
        <StatCard label="Gross Profit" value={`$${fmtMoney(summary?.gross_profit)}`}    color={C.accent} />
        <StatCard label="Margin"       value={`${summary?.margin_pct ?? 0}%`}           color={C.purple} />
      </div>

      {/* ── Tab bar + action buttons ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        {/* Revenue / Costs switcher */}
        <div
          style={{
            display: "flex", gap: 4,
            background: "rgba(255,255,255,0.04)",
            borderRadius: 10, padding: 4, border: C.border,
          }}
        >
          {[
            { key: "revenue", label: "Revenue", color: C.green,  activeBg: "rgba(74,222,128,0.15)" },
            { key: "costs",   label: "Costs",   color: C.red,    activeBg: "rgba(248,113,113,0.15)" },
          ].map(({ key, label, color, activeBg }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              style={{
                padding: "7px 18px", borderRadius: 8, border: "none",
                background: activeTab === key ? activeBg : "transparent",
                color: activeTab === key ? color : C.muted,
                fontWeight: 700, fontSize: 13, cursor: "pointer",
                transition: "all 0.15s",
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Add buttons */}
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={toggleManual}
            style={{
              padding: "8px 14px", borderRadius: 8, border: C.border,
              background: addMode === "manual_rev" || addMode === "manual_cost"
                ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.04)",
              color: C.text, fontWeight: 600, fontSize: 13, cursor: "pointer",
            }}
          >
            + Add Manual
          </button>
          <button
            onClick={toggleCSV}
            style={{
              padding: "8px 14px", borderRadius: 8, border: C.border,
              background: addMode === "csv" ? "rgba(249,115,22,0.12)" : "rgba(255,255,255,0.04)",
              color: C.accent, fontWeight: 600, fontSize: 13, cursor: "pointer",
            }}
          >
            Import CSV
          </button>
        </div>
      </div>

      {/* ── Manual Revenue Form ── */}
      {addMode === "manual_rev" && (
        <div
          style={{
            background: "rgba(74,222,128,0.04)",
            border: "1px solid rgba(74,222,128,0.20)",
            borderRadius: 14, padding: 18,
          }}
        >
          <div style={{ color: C.green, fontWeight: 700, fontSize: 14, marginBottom: 14 }}>
            Add Revenue Entry
          </div>
          <form
            onSubmit={submitRevenue}
            style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}
          >
            <input
              required placeholder="Amount *" value={revForm.amount}
              onChange={(e) => setRevForm((f) => ({ ...f, amount: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Source (e.g. Service call)" value={revForm.source}
              onChange={(e) => setRevForm((f) => ({ ...f, source: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Job Type" value={revForm.job_type}
              onChange={(e) => setRevForm((f) => ({ ...f, job_type: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Part Code" value={revForm.part_code}
              onChange={(e) => setRevForm((f) => ({ ...f, part_code: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Notes" value={revForm.notes}
              onChange={(e) => setRevForm((f) => ({ ...f, notes: e.target.value }))}
              style={{ ...inputStyle, gridColumn: "span 2" }}
            />
            <div style={{ display: "flex", gap: 8, gridColumn: "span 3" }}>
              <button
                type="submit"
                style={{
                  padding: "9px 20px", borderRadius: 9, border: "none",
                  background: C.green, color: "#000", fontWeight: 700, fontSize: 13, cursor: "pointer",
                }}
              >
                Save Revenue
              </button>
              <button
                type="button" onClick={() => setAddMode(null)}
                style={{
                  padding: "9px 16px", borderRadius: 9, border: C.border,
                  background: "transparent", color: C.muted, fontSize: 13, cursor: "pointer",
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── Manual Cost Form ── */}
      {addMode === "manual_cost" && (
        <div
          style={{
            background: "rgba(248,113,113,0.04)",
            border: "1px solid rgba(248,113,113,0.20)",
            borderRadius: 14, padding: 18,
          }}
        >
          <div style={{ color: C.red, fontWeight: 700, fontSize: 14, marginBottom: 14 }}>
            Add Cost Entry
          </div>
          <form
            onSubmit={submitCost}
            style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}
          >
            <input
              required placeholder="Amount *" value={costForm.amount}
              onChange={(e) => setCostForm((f) => ({ ...f, amount: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Category (e.g. Parts)" value={costForm.category}
              onChange={(e) => setCostForm((f) => ({ ...f, category: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Vendor" value={costForm.vendor}
              onChange={(e) => setCostForm((f) => ({ ...f, vendor: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Hours (e.g. 3.5)" value={costForm.hours}
              onChange={(e) => setCostForm((f) => ({ ...f, hours: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Hourly Rate" value={costForm.hourly_rate}
              onChange={(e) => setCostForm((f) => ({ ...f, hourly_rate: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Job Type" value={costForm.job_type}
              onChange={(e) => setCostForm((f) => ({ ...f, job_type: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Part Code" value={costForm.part_code}
              onChange={(e) => setCostForm((f) => ({ ...f, part_code: e.target.value }))}
              style={inputStyle}
            />
            <input
              placeholder="Notes" value={costForm.notes}
              onChange={(e) => setCostForm((f) => ({ ...f, notes: e.target.value }))}
              style={{ ...inputStyle, gridColumn: "span 2" }}
            />
            <div style={{ display: "flex", gap: 8, gridColumn: "span 3" }}>
              <button
                type="submit"
                style={{
                  padding: "9px 20px", borderRadius: 9, border: "none",
                  background: C.red, color: "#000", fontWeight: 700, fontSize: 13, cursor: "pointer",
                }}
              >
                Save Cost
              </button>
              <button
                type="button" onClick={() => setAddMode(null)}
                style={{
                  padding: "9px 16px", borderRadius: 9, border: C.border,
                  background: "transparent", color: C.muted, fontSize: 13, cursor: "pointer",
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── CSV Import Panel ── */}
      {addMode === "csv" && (
        <div
          style={{
            background: "rgba(249,115,22,0.04)",
            border: "1px solid rgba(249,115,22,0.20)",
            borderRadius: 14, padding: 18,
            display: "flex", flexDirection: "column", gap: 14,
          }}
        >
          <div style={{ color: C.accent, fontWeight: 700, fontSize: 14 }}>
            Import from CSV / Invoice Export
          </div>

          {/* File picker */}
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <label
              style={{
                display: "inline-block", padding: "9px 16px", borderRadius: 9,
                border: C.border, background: "rgba(255,255,255,0.06)",
                color: C.text, fontWeight: 600, fontSize: 13, cursor: "pointer",
              }}
            >
              Choose File
              <input
                ref={fileRef} type="file" accept=".csv,text/csv"
                onChange={handleFileChange}
                style={{ display: "none" }}
              />
            </label>
            {csvFile
              ? <span style={{ color: C.muted, fontSize: 13 }}>{csvFile.name} — <strong style={{ color: C.text }}>{csvData?.rows.length ?? 0}</strong> rows</span>
              : <span style={{ color: C.muted, fontSize: 13 }}>No file chosen</span>
            }
          </div>

          {!csvFile && (
            <div style={{ color: C.muted, fontSize: 13, lineHeight: 1.6 }}>
              Upload a CSV invoice or accounting export. We'll auto-detect Amount, Description, and Notes columns.
              <br />
              <span style={{ fontSize: 12, opacity: 0.7 }}>
                Supported exports: QuickBooks, Wave, FreshBooks, or any custom invoice CSV.
              </span>
            </div>
          )}

          {csvData && (
            <>
              {/* Column mapping */}
              <div>
                <div
                  style={{
                    color: C.muted, fontSize: 11, fontWeight: 700,
                    textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8,
                  }}
                >
                  Map Columns
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
                  {[
                    { key: "amount",      label: "Amount *" },
                    { key: "description", label: "Source / Category" },
                    { key: "notes",       label: "Notes" },
                  ].map(({ key, label }) => (
                    <div key={key}>
                      <div style={{ color: C.muted, fontSize: 11, marginBottom: 4 }}>{label}</div>
                      <select
                        value={csvMapping[key] ?? ""}
                        onChange={(e) => setCsvMapping((m) => ({ ...m, [key]: e.target.value }))}
                        style={{
                          background: C.inputBg, border: C.border, borderRadius: 8,
                          padding: "7px 10px", color: C.text, fontSize: 13, width: "100%",
                        }}
                      >
                        <option value="">— skip —</option>
                        {csvData.headers.map((h, i) => (
                          <option key={i} value={String(i)}>{h}</option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              </div>

              {/* Preview table */}
              <div style={{ overflowX: "auto", borderRadius: 10, border: C.border }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: "rgba(255,255,255,0.03)" }}>
                      {csvData.headers.map((h, i) => (
                        <th
                          key={i}
                          style={{
                            padding: "8px 10px", textAlign: "left",
                            color: C.muted, fontWeight: 700, fontSize: 11,
                            textTransform: "uppercase", borderBottom: C.border,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {csvData.rows.slice(0, 5).map((row, ri) => (
                      <tr
                        key={ri}
                        style={{
                          borderBottom: "1px solid rgba(255,255,255,0.04)",
                          background: ri % 2 !== 0 ? C.rowEven : "transparent",
                        }}
                      >
                        {csvData.headers.map((h, i) => (
                          <td key={i} style={{ padding: "7px 10px", color: C.text }}>{row[h] || "—"}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {csvData.rows.length > 5 && (
                  <div style={{ padding: "8px 12px", color: C.muted, fontSize: 12 }}>
                    …and {csvData.rows.length - 5} more rows
                  </div>
                )}
              </div>

              {/* Import action buttons */}
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  onClick={() => importCSV("revenue")}
                  disabled={csvImporting || !csvMapping.amount}
                  style={{
                    padding: "9px 18px", borderRadius: 9, border: "none",
                    background: C.green, color: "#000", fontWeight: 700, fontSize: 13,
                    cursor: csvImporting ? "default" : "pointer",
                    opacity: csvImporting || !csvMapping.amount ? 0.55 : 1,
                  }}
                >
                  {csvImporting ? "Importing…" : `Import as Revenue (${csvData.rows.length} rows)`}
                </button>
                <button
                  onClick={() => importCSV("cost")}
                  disabled={csvImporting || !csvMapping.amount}
                  style={{
                    padding: "9px 18px", borderRadius: 9, border: "none",
                    background: C.red, color: "#000", fontWeight: 700, fontSize: 13,
                    cursor: csvImporting ? "default" : "pointer",
                    opacity: csvImporting || !csvMapping.amount ? 0.55 : 1,
                  }}
                >
                  {csvImporting ? "Importing…" : `Import as Costs (${csvData.rows.length} rows)`}
                </button>
                <button
                  type="button" onClick={() => setAddMode(null)}
                  style={{
                    padding: "9px 16px", borderRadius: 9, border: C.border,
                    background: "transparent", color: C.muted, fontSize: 13, cursor: "pointer",
                  }}
                >
                  Cancel
                </button>
              </div>

              {/* Import result banner */}
              {csvResult && (
                <div
                  style={{
                    padding: "10px 16px", borderRadius: 9, fontSize: 13, fontWeight: 600,
                    background: csvResult.fail === 0 ? C.greenBg : "rgba(249,115,22,0.10)",
                    color: csvResult.fail === 0 ? C.green : C.accent,
                  }}
                >
                  {csvResult.ok} rows imported
                  {csvResult.fail > 0 ? `, ${csvResult.fail} skipped (missing or invalid amount)` : " successfully"}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── Entries table ── */}
      <div style={{ overflowX: "auto", borderRadius: 12, border: C.border }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 620 }}>
          <thead>
            <tr style={{ background: "rgba(255,255,255,0.03)" }}>
              {activeTab === "revenue" ? (
                <>
                  <th style={thStyle}>#</th>
                  <th style={thStyle}>Amount</th>
                  <th style={thStyle}>Source</th>
                  <th style={thStyle}>Part Code</th>
                  <th style={thStyle}>Job Type</th>
                  <th style={thStyle}>Notes</th>
                  <th style={thStyle}></th>
                </>
              ) : (
                <>
                  <th style={thStyle}>#</th>
                  <th style={thStyle}>Amount</th>
                  <th style={thStyle}>Category</th>
                  <th style={thStyle}>Vendor</th>
                  <th style={thStyle}>Part Code</th>
                  <th style={thStyle}>Job Type</th>
                  <th style={thStyle}></th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} style={{ padding: 28, textAlign: "center", color: C.muted }}>
                  Loading…
                </td>
              </tr>
            )}

            {/* Revenue rows */}
            {!loading && activeTab === "revenue" && revenue.map((r, i) => (
              <tr
                key={r.id}
                style={{
                  background: i % 2 === 0 ? "transparent" : C.rowEven,
                  borderBottom: "1px solid rgba(255,255,255,0.04)",
                  transition: "background 0.1s",
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = C.rowHover}
                onMouseLeave={(e) => e.currentTarget.style.background = i % 2 === 0 ? "transparent" : C.rowEven}
              >
                <td style={{ ...tdStyle, color: C.muted, fontSize: 11 }}>{r.id}</td>
                <td style={{ ...tdStyle, color: C.green, fontWeight: 700 }}>${fmtMoney(r.amount)}</td>
                <td style={{ ...tdStyle, color: C.text }}>{r.source || "—"}</td>
                <td style={{ ...tdStyle, color: C.muted }}>{r.part_code || "—"}</td>
                <td style={{ ...tdStyle, color: C.muted }}>{r.job_type || "—"}</td>
                <td style={{ ...tdStyle, color: C.muted, fontSize: 12 }}>{r.notes || "—"}</td>
                <td style={{ ...tdStyle }}>
                  <button
                    onClick={() => deleteRev(r.id)}
                    style={{
                      background: C.redBg, border: "1px solid rgba(248,113,113,0.25)",
                      borderRadius: 6, padding: "3px 10px", color: C.red, fontSize: 11, cursor: "pointer",
                    }}
                  >
                    Del
                  </button>
                </td>
              </tr>
            ))}
            {!loading && activeTab === "revenue" && revenue.length === 0 && (
              <tr>
                <td colSpan={7} style={{ padding: 28, textAlign: "center", color: C.muted }}>
                  No revenue entries. Add one manually or import a CSV.
                </td>
              </tr>
            )}

            {/* Cost rows */}
            {!loading && activeTab === "costs" && costs.map((c, i) => {
              const amt =
                Number(c.hours || 0) > 0 && Number(c.hourly_rate || 0) > 0
                  ? Number(c.hours) * Number(c.hourly_rate)
                  : c.amount;
              return (
                <tr
                  key={c.id}
                  style={{
                    background: i % 2 === 0 ? "transparent" : C.rowEven,
                    borderBottom: "1px solid rgba(255,255,255,0.04)",
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.background = C.rowHover}
                  onMouseLeave={(e) => e.currentTarget.style.background = i % 2 === 0 ? "transparent" : C.rowEven}
                >
                  <td style={{ ...tdStyle, color: C.muted, fontSize: 11 }}>{c.id}</td>
                  <td style={{ ...tdStyle, color: C.red, fontWeight: 700 }}>${fmtMoney(amt)}</td>
                  <td style={{ ...tdStyle, color: C.text }}>{c.category || "—"}</td>
                  <td style={{ ...tdStyle, color: C.muted }}>{c.vendor || "—"}</td>
                  <td style={{ ...tdStyle, color: C.muted }}>{c.part_code || "—"}</td>
                  <td style={{ ...tdStyle, color: C.muted }}>{c.job_type || "—"}</td>
                  <td style={{ ...tdStyle }}>
                    <button
                      onClick={() => deleteCost(c.id)}
                      style={{
                        background: C.redBg, border: "1px solid rgba(248,113,113,0.25)",
                        borderRadius: 6, padding: "3px 10px", color: C.red, fontSize: 11, cursor: "pointer",
                      }}
                    >
                      Del
                    </button>
                  </td>
                </tr>
              );
            })}
            {!loading && activeTab === "costs" && costs.length === 0 && (
              <tr>
                <td colSpan={7} style={{ padding: 28, textAlign: "center", color: C.muted }}>
                  No cost entries. Add one manually or import a CSV.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
