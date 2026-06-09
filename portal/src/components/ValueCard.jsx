import React, { useEffect, useState } from "react";

const CARD = {
  border: "1px solid rgba(255,255,255,0.10)",
  borderRadius: 16,
  padding: 18,
  background: "rgba(0,0,0,0.12)",
};

function StatBox({ label, value, sub, accent = "#f97316" }) {
  return (
    <div
      style={{
        ...CARD,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div style={{ fontSize: 12, color: "rgba(229,231,235,0.55)", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 32, fontWeight: 900, color: accent, lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 12, color: "rgba(229,231,235,0.50)" }}>{sub}</div>
      )}
    </div>
  );
}

export default function ValueCard({ apiBase, commonHeaders }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function load() {
      try {
        const r = await fetch(`${apiBase}/tenant/value-summary`, { headers: commonHeaders });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        setData(await r.json());
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [apiBase]);

  if (loading) {
    return <div style={{ padding: 24, color: "rgba(229,231,235,0.5)" }}>Loading your stats…</div>;
  }

  if (error) {
    return <div style={{ padding: 24, color: "#fca5a5" }}>Failed to load stats: {error}</div>;
  }

  const fmt = (n) => n?.toLocaleString() ?? "0";
  const fmtMoney = (n) =>
    (n || 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Header */}
      <div style={CARD}>
        <div style={{ fontSize: 11, color: "rgba(229,231,235,0.45)", fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
          Monthly recap — {data.month}
        </div>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 900 }}>
          Here's what Torevez did for you
        </h2>
        <p style={{ margin: "6px 0 0", color: "rgba(229,231,235,0.60)", fontSize: 14 }}>
          A snapshot of the value Torevez delivered to your business this month.
        </p>
      </div>

      {/* Stats grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))",
          gap: 12,
        }}
      >
        <StatBox
          label="Leads captured"
          value={fmt(data.leads_captured)}
          sub="New potential customers"
          accent="#f97316"
        />
        <StatBox
          label="Bookings made"
          value={fmt(data.bookings_made)}
          sub="Appointments scheduled"
          accent="#fb923c"
        />
        <StatBox
          label="Jobs won"
          value={fmt(data.jobs_won)}
          sub="Completed with revenue"
          accent="#34d399"
        />
        <StatBox
          label="Revenue this month"
          value={fmtMoney(data.revenue_this_month)}
          sub="From completed jobs"
          accent="#34d399"
        />
        <StatBox
          label="Missed calls answered"
          value={fmt(data.missed_calls_answered)}
          sub="Leads that would've been lost"
          accent="#60a5fa"
        />
      </div>

      {/* All-time total */}
      <div
        style={{
          ...CARD,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <div style={{ fontSize: 12, color: "rgba(229,231,235,0.50)", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
            All-time revenue tracked
          </div>
          <div style={{ fontSize: 28, fontWeight: 900, color: "#34d399" }}>
            {fmtMoney(data.all_time_revenue)}
          </div>
        </div>
        <div
          style={{
            padding: "10px 16px",
            borderRadius: 12,
            background: "rgba(34,197,94,0.08)",
            border: "1px solid rgba(34,197,94,0.20)",
            fontSize: 13,
            color: "#86efac",
            maxWidth: 260,
            lineHeight: 1.5,
          }}
        >
          Every dollar above is revenue Torevez helped you close — jobs that might have gone unanswered.
        </div>
      </div>
    </div>
  );
}
