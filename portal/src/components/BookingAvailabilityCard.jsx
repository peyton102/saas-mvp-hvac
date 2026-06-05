import { useEffect, useState } from "react";
import QRCode from "qrcode";

const DAYS = [
  { slug: "mon", label: "Mon" },
  { slug: "tue", label: "Tue" },
  { slug: "wed", label: "Wed" },
  { slug: "thu", label: "Thu" },
  { slug: "fri", label: "Fri" },
  { slug: "sat", label: "Sat" },
  { slug: "sun", label: "Sun" },
];

const SLOT_OPTIONS = [
  { val: 30,  label: "30 min" },
  { val: 60,  label: "1 hr" },
  { val: 90,  label: "1.5 hr" },
  { val: 120, label: "2 hr" },
];

function timeOptions(startH, endH) {
  const opts = [];
  for (let h = startH; h <= endH; h++) {
    for (const m of [0, 30]) {
      if (h === endH && m > 0) break;
      const hh = String(h).padStart(2, "0");
      const mm = String(m).padStart(2, "0");
      const val = `${hh}:${mm}`;
      const label = new Date(`1970-01-01T${val}:00`).toLocaleTimeString("en-US", {
        hour: "numeric", minute: "2-digit",
      });
      opts.push({ val, label });
    }
  }
  return opts;
}

const START_OPTIONS = timeOptions(0, 23);
const END_OPTIONS   = timeOptions(0, 23);

const card = {
  border: "1px solid rgba(255,255,255,0.10)",
  borderRadius: 16,
  padding: 20,
  background: "rgba(0,0,0,0.12)",
  marginTop: 16,
};

const sectionLabel = {
  fontSize: 12,
  fontWeight: 700,
  color: "rgba(229,231,235,0.45)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  marginBottom: 10,
};

const selectStyle = {
  width: "100%",
  padding: "12px 14px",
  fontSize: 14,
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.12)",
  background: "#1f2937",
  color: "#e5e7eb",
  outline: "none",
  cursor: "pointer",
  boxSizing: "border-box",
};

const codeBox = {
  fontFamily: "monospace",
  fontSize: 12,
  background: "rgba(0,0,0,0.35)",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: 8,
  padding: "10px 12px",
  color: "rgba(229,231,235,0.75)",
  wordBreak: "break-all",
  userSelect: "all",
};

export default function BookingAvailabilityCard({ apiBase, commonHeaders, tenantSlug }) {
  const [days,        setDays]        = useState(["mon","tue","wed","thu","fri"]);
  const [startTime,   setStartTime]   = useState("08:00");
  const [endTime,     setEndTime]     = useState("17:00");
  const [slotMinutes, setSlotMinutes] = useState(60);

  const [loading,   setLoading]   = useState(true);
  const [saving,    setSaving]    = useState(false);
  const [msg,       setMsg]       = useState("");
  const [err,       setErr]       = useState("");
  const [copied,    setCopied]    = useState("");
  const [qrDataUrl, setQrDataUrl] = useState("");

  // ---- Load current config ----
  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const res = await fetch(`${apiBase}/tenant/booking-config`, { headers: commonHeaders });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const d = await res.json();
        if (d.booking_days?.length)  setDays(d.booking_days);
        if (d.booking_start)         setStartTime(d.booking_start);
        if (d.booking_end)           setEndTime(d.booking_end);
        if (d.slot_minutes)          setSlotMinutes(d.slot_minutes);
      } catch (e) {
        setErr("Could not load availability settings.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [apiBase, commonHeaders]);

  function toggleDay(slug) {
    setDays(prev =>
      prev.includes(slug) ? prev.filter(d => d !== slug) : [...prev, slug]
    );
  }

  async function save(e) {
    e.preventDefault();
    setMsg(""); setErr("");
    if (days.length === 0) return setErr("Select at least one day.");
    if (startTime >= endTime) return setErr("End time must be after start time.");

    setSaving(true);
    try {
      const res = await fetch(`${apiBase}/tenant/booking-config`, {
        method: "POST",
        headers: { ...commonHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ booking_days: days, booking_start: startTime, booking_end: endTime, slot_minutes: slotMinutes }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setMsg("Saved");
      setTimeout(() => setMsg(""), 3000);
    } catch (e) {
      setErr(e.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  // ---- Embed code ----
  const bookingUrl = tenantSlug && apiBase
    ? `${apiBase}/book/index.html?tenant=${encodeURIComponent(tenantSlug)}`
    : "";
  const iframeCode = bookingUrl
    ? `<iframe src="${bookingUrl}" width="100%" height="620" style="border:none;border-radius:12px;" title="Book an appointment"></iframe>`
    : "";

  function copyToClipboard(text, key) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(""), 2500);
    });
  }

  useEffect(() => {
    if (!bookingUrl) return;
    QRCode.toDataURL(bookingUrl, { width: 280, margin: 2, color: { dark: "#111827", light: "#ffffff" } })
      .then(setQrDataUrl)
      .catch(() => {});
  }, [bookingUrl]);

  const dayActive = (slug) => days.includes(slug);

  if (loading) {
    return (
      <div style={card}>
        <p style={{ color: "rgba(229,231,235,0.45)", fontSize: 14, margin: 0 }}>
          Loading availability settings…
        </p>
      </div>
    );
  }

  return (
    <div style={card}>
      <h3 style={{ margin: "0 0 18px", fontSize: 16, color: "#e5e7eb", fontWeight: 800 }}>
        Booking Availability
      </h3>

      <form onSubmit={save} style={{ display: "grid", gap: 20 }}>

        {/* Days */}
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div style={sectionLabel}>Available Days</div>
            <button
              type="button"
              onClick={() => {
                setDays(["sun","mon","tue","wed","thu","fri","sat"]);
                setStartTime("00:00");
                setEndTime("23:30");
              }}
              style={{
                padding: "5px 12px",
                borderRadius: 8,
                border: days.length === 7 && startTime === "00:00" && endTime === "23:30"
                  ? "1px solid rgba(249,115,22,0.6)"
                  : "1px solid rgba(255,255,255,0.15)",
                background: days.length === 7 && startTime === "00:00" && endTime === "23:30"
                  ? "rgba(249,115,22,0.15)"
                  : "rgba(255,255,255,0.06)",
                color: days.length === 7 && startTime === "00:00" && endTime === "23:30"
                  ? "#f97316"
                  : "rgba(229,231,235,0.55)",
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              24 / 7
            </button>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {DAYS.map(({ slug, label }) => (
              <button
                key={slug}
                type="button"
                onClick={() => toggleDay(slug)}
                style={{
                  padding: "9px 14px",
                  borderRadius: 10,
                  border: dayActive(slug)
                    ? "1px solid rgba(249,115,22,0.6)"
                    : "1px solid rgba(255,255,255,0.10)",
                  background: dayActive(slug)
                    ? "rgba(249,115,22,0.15)"
                    : "rgba(255,255,255,0.04)",
                  color: dayActive(slug) ? "#f97316" : "rgba(229,231,235,0.45)",
                  fontSize: 13,
                  fontWeight: dayActive(slug) ? 800 : 500,
                  cursor: "pointer",
                  transition: "all 0.15s",
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Hours */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div>
            <div style={sectionLabel}>Start Time</div>
            <select value={startTime} onChange={e => setStartTime(e.target.value)} style={selectStyle}>
              {START_OPTIONS.map(({ val, label }) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>
          <div>
            <div style={sectionLabel}>End Time</div>
            <select value={endTime} onChange={e => setEndTime(e.target.value)} style={selectStyle}>
              {END_OPTIONS.map(({ val, label }) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Slot length */}
        <div>
          <div style={sectionLabel}>Appointment Length</div>
          <div style={{ display: "flex", gap: 8 }}>
            {SLOT_OPTIONS.map(({ val, label }) => (
              <button
                key={val}
                type="button"
                onClick={() => setSlotMinutes(val)}
                style={{
                  flex: 1,
                  padding: "10px 8px",
                  borderRadius: 10,
                  border: slotMinutes === val
                    ? "1px solid rgba(249,115,22,0.6)"
                    : "1px solid rgba(255,255,255,0.10)",
                  background: slotMinutes === val
                    ? "rgba(249,115,22,0.15)"
                    : "rgba(255,255,255,0.04)",
                  color: slotMinutes === val ? "#f97316" : "rgba(229,231,235,0.45)",
                  fontSize: 13,
                  fontWeight: slotMinutes === val ? 800 : 500,
                  cursor: "pointer",
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Feedback */}
        {err && <div style={{ fontSize: 13, color: "#fca5a5", fontWeight: 700 }}>{err}</div>}
        {msg && <div style={{ fontSize: 13, color: "#6ee7b7", fontWeight: 700 }}>{msg}</div>}

        <button
          type="submit"
          disabled={saving}
          style={{
            padding: "11px 20px",
            fontWeight: 900,
            fontSize: 14,
            borderRadius: 10,
            border: "none",
            background: saving ? "rgba(249,115,22,0.45)" : "#f97316",
            color: "#111827",
            cursor: saving ? "not-allowed" : "pointer",
            alignSelf: "start",
          }}
        >
          {saving ? "Saving…" : "Save Availability"}
        </button>
      </form>

      {/* Share section */}
      {bookingUrl && (
        <div style={{ marginTop: 24 }}>
          <div style={{ borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 18, display: "grid", gap: 18 }}>
            <div style={{ ...sectionLabel, marginBottom: 0 }}>Share Your Booking Page</div>

            {/* Direct link */}
            <div>
              <div style={{ fontSize: 12, color: "rgba(229,231,235,0.45)", marginBottom: 6 }}>
                Direct link — paste into emails, texts, or your Google Business Profile
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div style={{ ...codeBox, flex: 1 }}>{bookingUrl}</div>
                <button
                  type="button"
                  onClick={() => copyToClipboard(bookingUrl, "link")}
                  style={{
                    padding: "8px 14px",
                    borderRadius: 8,
                    border: "1px solid rgba(249,115,22,0.5)",
                    background: "rgba(249,115,22,0.12)",
                    color: "#f97316",
                    fontSize: 12,
                    fontWeight: 800,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  {copied === "link" ? "Copied!" : "Copy"}
                </button>
              </div>
              <div style={{ fontSize: 11, color: "rgba(249,115,22,0.7)", marginTop: 6 }}>
                Tip: Add this to your Google Business Profile under "Booking" → instantly get a Book Online button on Google Maps and Search.
              </div>
            </div>

            {/* QR Code */}
            {qrDataUrl && (
              <div>
                <div style={{ fontSize: 12, color: "rgba(229,231,235,0.45)", marginBottom: 10 }}>
                  QR code — print on business cards, invoices, truck magnets, or door hangers
                </div>
                <div style={{ display: "flex", gap: 16, alignItems: "flex-end" }}>
                  <img
                    src={qrDataUrl}
                    alt="Booking QR code"
                    style={{ width: 110, height: 110, borderRadius: 10, border: "1px solid rgba(255,255,255,0.10)" }}
                  />
                  <div style={{ display: "grid", gap: 8 }}>
                    <a
                      href={qrDataUrl}
                      download="booking-qr.png"
                      style={{
                        display: "inline-block",
                        padding: "10px 18px",
                        borderRadius: 8,
                        border: "1px solid rgba(249,115,22,0.5)",
                        background: "rgba(249,115,22,0.12)",
                        color: "#f97316",
                        fontSize: 13,
                        fontWeight: 800,
                        cursor: "pointer",
                        textDecoration: "none",
                        textAlign: "center",
                      }}
                    >
                      Download PNG
                    </a>
                    <div style={{ fontSize: 11, color: "rgba(229,231,235,0.35)", maxWidth: 200 }}>
                      Customers scan with their phone camera — no app needed
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* iframe embed */}
            <div>
              <div style={{ fontSize: 12, color: "rgba(229,231,235,0.45)", marginBottom: 6 }}>
                Website embed — paste into Wix, Squarespace, WordPress, etc.
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <div style={{ ...codeBox, flex: 1 }}>{iframeCode}</div>
                <button
                  type="button"
                  onClick={() => copyToClipboard(iframeCode, "iframe")}
                  style={{
                    padding: "8px 14px",
                    borderRadius: 8,
                    border: "1px solid rgba(249,115,22,0.5)",
                    background: "rgba(249,115,22,0.12)",
                    color: "#f97316",
                    fontSize: 12,
                    fontWeight: 800,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                    marginTop: 2,
                  }}
                >
                  {copied === "iframe" ? "Copied!" : "Copy"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
