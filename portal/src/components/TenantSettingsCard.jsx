// portal/src/components/TenantSettingsCard.jsx
import React, { useEffect, useState } from "react";

export default function TenantSettingsCard({ apiBase, commonHeaders }) {
  const [form, setForm] = useState({
    business_name: "",
    booking_link: "",
    office_sms_to: "",
    office_email_to: "",
    review_google_url: "",
    email: "",
    phone: "",
  });

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");

  // ---- Load current settings from backend (GET /tenant/settings) ----
  useEffect(() => {
    async function loadSettings() {
      setLoading(true);
      setError("");
      setSaveMessage("");

      try {
        const res = await fetch(`${apiBase}/tenant/settings`, {
          method: "GET",
          headers: commonHeaders,
        });
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();

        setForm({
          business_name: data.business_name ?? "",
          booking_link: data.booking_link ?? "",
          office_sms_to: data.office_sms_to ?? "",
          office_email_to: data.office_email_to ?? "",
          review_google_url: data.review_google_url ?? "",
          email: data.email ?? "",
          phone: data.phone ?? "",
        });
      } catch (e) {
        console.error(e);
        setError("Could not load settings");
      } finally {
        setLoading(false);
      }
    }

    loadSettings();
  }, [apiBase, commonHeaders]);

  function bind(field) {
    return {
      value: form[field] ?? "",
      onChange: (e) =>
        setForm((prev) => ({
          ...prev,
          [field]: e.target.value,
        })),
    };
  }

  // ---- Save settings to backend (POST /tenant/settings) ----
  async function handleSave() {
    setSaving(true);
    setError("");
    setSaveMessage("");

    try {
      const res = await fetch(`${apiBase}/tenant/settings`, {
        method: "POST",
        headers: {
          ...commonHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(form),
      });

      if (!res.ok) {
        let detail = "";
        try {
          const errData = await res.json();
          detail = errData.detail || "";
        } catch {
          // ignore JSON parse issues
        }
        throw new Error(detail || `Save failed (HTTP ${res.status})`);
      }

      // PREMIUM UX: keep current form values as-is, just show success
      setSaveMessage("Saved ✓");

      // Optionally clear the message after a few seconds
      setTimeout(() => {
        setSaveMessage("");
      }, 3000);
    } catch (e) {
      console.error(e);
      setError(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        border: "1px solid #e5e7eb",
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
        maxWidth: 520,
      }}
    >
      <h2 style={{ marginTop: 0, marginBottom: 8 }}>
        Business & Notification Settings
      </h2>

      {loading && (
        <p style={{ fontSize: 13, marginTop: 4, marginBottom: 8 }}>
          Loading settings…
        </p>
      )}

      {error && (
        <p
          style={{
            color: "red",
            fontSize: 13,
            marginTop: 4,
            marginBottom: 8,
          }}
        >
          {error}
        </p>
      )}

      {saveMessage && !error && (
        <p
          style={{
            color: "green",
            fontSize: 13,
            marginTop: 4,
            marginBottom: 8,
          }}
        >
          {saveMessage}
        </p>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSave();
        }}
        style={{ display: "grid", gap: 8 }}
      >
        <label style={{ fontSize: 13 }}>
          Business Name
          <input
            type="text"
            style={{ width: "100%", marginTop: 4 }}
            {...bind("business_name")}
          />
        </label>

        <label style={{ fontSize: 13 }}>
          Public Booking Link
          <input
            type="url"
            style={{ width: "100%", marginTop: 4 }}
            placeholder="https://your-booking-link.com"
            {...bind("booking_link")}
          />
        </label>

        <label style={{ fontSize: 13 }}>
          Google Review URL
          <input
            type="url"
            style={{ width: "100%", marginTop: 4 }}
            placeholder="https://g.page/r/..."
            {...bind("review_google_url")}
          />
        </label>

        <label style={{ fontSize: 13 }}>
          Office SMS Number (gets new-lead texts)
          <input
            type="tel"
            style={{ width: "100%", marginTop: 4 }}
            placeholder="15555551234"
            {...bind("office_sms_to")}
          />
        </label>

        <label style={{ fontSize: 13 }}>
          Office Email (gets new-lead emails)
          <input
            type="email"
            style={{ width: "100%", marginTop: 4 }}
            placeholder="office@example.com"
            {...bind("office_email_to")}
          />
        </label>

        <label style={{ fontSize: 13 }}>
          Business Email
          <input
            type="email"
            style={{ width: "100%", marginTop: 4 }}
            {...bind("email")}
          />
        </label>

        <label style={{ fontSize: 13 }}>
          Business Phone
          <input
            type="tel"
            style={{ width: "100%", marginTop: 4 }}
            {...bind("phone")}
          />
        </label>

        <div style={{ marginTop: 8 }}>
          <button
            type="submit"
            disabled={saving}
            style={{
              padding: "6px 14px",
              borderRadius: 6,
              border: "1px solid #2563EB",
              background: saving ? "#93C5FD" : "#3B82F6",
              color: "white",
              fontSize: 14,
              cursor: saving ? "wait" : "pointer",
            }}
          >
            {saving ? "Saving…" : "Save Settings"}
          </button>
        </div>
      </form>
    </div>
  );
}
