// portal/src/components/TenantSettingsCard.jsx
import React, { useEffect, useMemo, useState } from "react";

// ---- shared styles ----
const card = {
  border: "1px solid rgba(255,255,255,0.10)",
  borderRadius: 16,
  padding: 20,
  background: "rgba(0,0,0,0.12)",
};

const sectionLabel = {
  fontSize: 11,
  fontWeight: 700,
  color: "rgba(229,231,235,0.40)",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  marginBottom: 6,
};

const inputStyle = {
  width: "100%",
  padding: "11px 14px",
  fontSize: 14,
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.12)",
  background: "rgba(255,255,255,0.07)",
  color: "#e5e7eb",
  outline: "none",
  boxSizing: "border-box",
};

const fieldWrap = { display: "grid", gap: 5 };

const divider = {
  borderTop: "1px solid rgba(255,255,255,0.07)",
  margin: "18px 0",
};

// ---- field component ----
function Field({ label, hint, children }) {
  return (
    <div style={fieldWrap}>
      <div style={sectionLabel}>{label}</div>
      {children}
      {hint && (
        <div style={{ fontSize: 11, color: "rgba(229,231,235,0.35)", marginTop: 2 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

export default function TenantSettingsCard({
  apiBase = "",
  commonHeaders,
  tenantSlug,
  onCompleteChange,
}) {
  const [form, setForm] = useState({
    business_name: "",
    booking_link: "",
    office_sms_to: "",
    office_email_to: "",
    review_google_url: "",
    email: "",
    phone: "",
    vapi_can_book: false,
  });

  const isSettingsComplete = useMemo(() => {
    const { business_name, review_google_url, booking_link } = form;
    return Boolean(
      (business_name || "").trim() &&
      (review_google_url || "").trim() &&
      (booking_link || "").trim()
    );
  }, [form.business_name, form.review_google_url, form.booking_link]);

  useEffect(() => {
    onCompleteChange?.(isSettingsComplete);
  }, [isSettingsComplete, onCompleteChange]);

  const [loading, setLoading]       = useState(false);
  const [saving, setSaving]         = useState(false);
  const [error, setError]           = useState("");
  const [saveMessage, setSaveMessage] = useState("");

  const computedBookingLink = useMemo(() => {
    if (!tenantSlug || !apiBase) return "";
    return `${apiBase}/book/index.html?tenant=${encodeURIComponent(tenantSlug)}`;
  }, [tenantSlug, apiBase]);

  // ---- load ----
  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const res = await fetch(`${apiBase}/tenant/settings`, { headers: commonHeaders });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!active) return;

        const loaded = {
          business_name:    data.business_name    ?? "",
          booking_link:     data.booking_link     ?? "",
          office_sms_to:    data.office_sms_to    ?? "",
          office_email_to:  data.office_email_to  ?? "",
          review_google_url: data.review_google_url ?? "",
          email:            data.email            ?? "",
          phone:            data.phone            ?? "",
          vapi_can_book:    data.vapi_can_book    ?? false,
        };

        const raw = (loaded.booking_link || "").trim();
        const looksEmpty =
          !raw ||
          raw.endsWith("?tenant=") ||
          raw.endsWith("?") ||
          !raw.includes("tenant=");
        if (looksEmpty && computedBookingLink) loaded.booking_link = computedBookingLink;

        setForm(loaded);
      } catch (e) {
        if (active) setError("Could not load settings.");
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => { active = false; };
  }, [apiBase, commonHeaders, computedBookingLink]);

  useEffect(() => {
    if (!computedBookingLink) return;
    setForm(prev => prev.booking_link ? prev : { ...prev, booking_link: computedBookingLink });
  }, [computedBookingLink]);

  function bind(field) {
    return {
      value: form[field] ?? "",
      onChange: e => setForm(prev => ({ ...prev, [field]: e.target.value })),
    };
  }

  // ---- save ----
  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setSaveMessage("");
    const payload = { ...form, booking_link: form.booking_link || computedBookingLink || "" };
    try {
      const res = await fetch(`${apiBase}/tenant/settings`, {
        method: "POST",
        headers: { ...commonHeaders, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      setForm(payload);
      setSaveMessage("Saved");
      setTimeout(() => setSaveMessage(""), 3000);
    } catch (e) {
      setError(e.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={card}>
      <h3 style={{ margin: "0 0 18px", fontSize: 16, color: "#e5e7eb", fontWeight: 800 }}>
        Business Settings
      </h3>

      {loading && (
        <p style={{ fontSize: 13, color: "rgba(229,231,235,0.45)", margin: "0 0 14px" }}>
          Loading…
        </p>
      )}

      <form onSubmit={handleSave} style={{ display: "grid", gap: 14 }}>

        {/* Business info */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="Business Name">
            <input type="text" style={inputStyle} placeholder="ACME HVAC" {...bind("business_name")} />
          </Field>
          <Field label="Business Phone">
            <input type="tel" style={inputStyle} placeholder="+15555551234" {...bind("phone")} />
          </Field>
        </div>

        <Field label="Business Email">
          <input type="email" style={inputStyle} placeholder="office@yourhvac.com" {...bind("email")} />
        </Field>

        <div style={divider} />

        {/* Notifications */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="SMS Alerts To" hint="Gets new-lead & booking texts">
            <input type="tel" style={inputStyle} placeholder="+15555551234" {...bind("office_sms_to")} />
          </Field>
          <Field label="Email Alerts To" hint="Gets new-lead & booking emails">
            <input type="email" style={inputStyle} placeholder="you@yourhvac.com" {...bind("office_email_to")} />
          </Field>
        </div>

        <div style={divider} />

        {/* Links */}
        <Field
          label="Google Review URL"
          hint="Sent to customers after job completion"
        >
          <input type="url" style={inputStyle} placeholder="https://g.page/r/..." {...bind("review_google_url")} />
        </Field>

        <Field
          label="Booking Link"
          hint={computedBookingLink ? `Auto-generated: ${computedBookingLink}` : ""}
        >
          <input type="url" style={inputStyle} {...bind("booking_link")} />
        </Field>

        <div style={divider} />

        {/* AI Voice Assistant */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
          <div>
            <div style={{ fontSize: 14, color: "#e5e7eb", fontWeight: 600 }}>AI Can Book Appointments</div>
            <div style={{ fontSize: 12, color: "rgba(229,231,235,0.45)", marginTop: 3 }}>
              When enabled, your AI assistant can check your calendar and book directly during calls
            </div>
          </div>
          <button
            type="button"
            onClick={() => setForm(prev => ({ ...prev, vapi_can_book: !prev.vapi_can_book }))}
            style={{
              width: 44,
              height: 24,
              borderRadius: 12,
              border: "none",
              background: form.vapi_can_book ? "#f97316" : "rgba(255,255,255,0.15)",
              cursor: "pointer",
              position: "relative",
              flexShrink: 0,
              transition: "background 0.2s",
            }}
            aria-label="Toggle AI booking"
          >
            <span style={{
              position: "absolute",
              top: 3,
              left: form.vapi_can_book ? 23 : 3,
              width: 18,
              height: 18,
              borderRadius: "50%",
              background: "#fff",
              transition: "left 0.2s",
            }} />
          </button>
        </div>

        {/* Feedback */}
        {error      && <div style={{ fontSize: 13, color: "#fca5a5", fontWeight: 700 }}>{error}</div>}
        {saveMessage && <div style={{ fontSize: 13, color: "#6ee7b7", fontWeight: 700 }}>{saveMessage}</div>}

        <div>
          <button
            type="submit"
            disabled={saving}
            style={{
              padding: "11px 24px",
              fontWeight: 900,
              fontSize: 14,
              borderRadius: 10,
              border: "none",
              background: saving ? "rgba(249,115,22,0.45)" : "#f97316",
              color: "#111827",
              cursor: saving ? "not-allowed" : "pointer",
            }}
          >
            {saving ? "Saving…" : "Save Settings"}
          </button>
        </div>
      </form>
    </div>
  );
}
