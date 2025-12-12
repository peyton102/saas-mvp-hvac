// portal/src/components/TenantSettingsCard.jsx
import React, { useEffect, useMemo, useState } from "react";

export default function TenantSettingsCard({
  apiBase,
  commonHeaders,
  tenantSlug, // <-- REQUIRED: pass tenant_slug from /auth/login
}) {
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

  // Base URL for the portal (Render in prod, localhost in dev)
  const frontendBase =
    import.meta?.env?.VITE_APP_BASE_URL ||
    "https://saas-mvp-hvac-1.onrender.com";

  // Computed booking link for THIS tenant (multi-tenant safe)
  const computedBookingLink = useMemo(() => {
    if (!tenantSlug) return "";
    return `${frontendBase}/book/index.html?tenant=${encodeURIComponent(
      tenantSlug
    )}`;
  }, [tenantSlug, frontendBase]);

  // ---- Load current settings from backend (GET /tenant/settings) ----
  useEffect(() => {
    let isMounted = true;

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

        if (!isMounted) return;

        const loaded = {
          business_name: data.business_name ?? "",
          booking_link: data.booking_link ?? "",
          office_sms_to: data.office_sms_to ?? "",
          office_email_to: data.office_email_to ?? "",
          review_google_url: data.review_google_url ?? "",
          email: data.email ?? "",
          phone: data.phone ?? "",
        };

        // If booking_link is empty in DB, auto-fill it using tenantSlug + portal base
        // This does NOT overwrite if the backend already has a value.
       const raw = (loaded.booking_link || "").trim();

// treat prefix-only values as invalid (needs tenant slug)
const looksLikePrefixOnly =
  raw === `${frontendBase}/book/index.html?tenant=` ||
  raw.endsWith("/book/index.html?tenant=") ||
  raw.endsWith("/book/index.html?") ||
  raw.endsWith("?") ||
  !raw.includes("tenant=");

if ((!raw || looksLikePrefixOnly) && computedBookingLink) {
  loaded.booking_link = computedBookingLink;
}


        setForm(loaded);
      } catch (e) {
        console.error(e);
        if (isMounted) setError("Could not load settings");
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    loadSettings();

    return () => {
      isMounted = false;
    };
  }, [apiBase, commonHeaders, computedBookingLink]);

  // If tenantSlug arrives AFTER settings load (race), and booking_link is still blank,
  // fill it once. This won't overwrite an existing value.
  useEffect(() => {
    if (!computedBookingLink) return;
    setForm((prev) => {
      if (prev.booking_link) return prev;
      return { ...prev, booking_link: computedBookingLink };
    });
  }, [computedBookingLink]);

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

    // Guard: if they somehow blanked it, force the correct computed link
    const payload = {
      ...form,
      booking_link: form.booking_link || computedBookingLink || "",
    };

    try {
      const res = await fetch(`${apiBase}/tenant/settings`, {
        method: "POST",
        headers: {
          ...commonHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
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

      // Keep current values, just show success
      setForm(payload);
      setSaveMessage("Saved ✓");

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
            placeholder="Auto-filled from your tenant"
            {...bind("booking_link")}
          />
          <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>
            {tenantSlug ? (
              <>
                Expected:{" "}
                <span style={{ fontFamily: "monospace" }}>
                  {computedBookingLink}
                </span>
              </>
            ) : (
              <>Login must provide tenant_slug to auto-fill this.</>
            )}
          </div>
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
