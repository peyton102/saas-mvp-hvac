import React, { useState } from "react";

const API_BASE =
  (import.meta.env.VITE_API_BASE || "").trim() ||
  "https://saas-mvp-hvac.onrender.com";

const inputStyle = {
  width: "100%",
  padding: "18px 20px",
  fontSize: 20,
  borderRadius: 14,
  border: "none",
  background: "rgba(255,255,255,0.92)",
  color: "#111827",
  outline: "none",
  boxSizing: "border-box",
};

const primaryBtn = {
  width: "100%",
  padding: "18px 20px",
  fontSize: 22,
  fontWeight: 900,
  borderRadius: 14,
  border: "none",
  background: "#f97316",
  color: "#111827",
  cursor: "pointer",
};

const backBtn = {
  padding: "10px 14px",
  fontWeight: 900,
  borderRadius: 12,
  border: "1px solid rgba(249,115,22,0.65)",
  background: "rgba(249,115,22,0.18)",
  color: "#f97316",
  cursor: "pointer",
};

export default function InviteSignupPage({ onSignedUp, onBack }) {
  const [inviteCode, setInviteCode] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [phone, setPhone] = useState("");
  const [reviewLink, setReviewLink] = useState("");

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  async function onSubmit(e) {
    e.preventDefault();
    setErr("");

    if (!inviteCode.trim()) return setErr("Invite code is required.");
    if (!businessName.trim()) return setErr("Business name is required.");
    if (!email.trim()) return setErr("Email is required.");
    if (!password.trim()) return setErr("Password is required.");

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          invite_code: inviteCode.trim(),
          business_name: businessName.trim(),
          email: email.trim(),
          password,
          phone: phone.trim() || undefined,
          review_link: reviewLink.trim() || undefined,
        }),
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        setErr(data?.detail || "Signup failed.");
        return;
      }

      // Hand control back to App.jsx so it stores token/api_key correctly and loads /auth/me
      onSignedUp?.(data);
    } catch {
      setErr("Network error. Is the API reachable?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        width: "100%",
        display: "grid",
        placeItems: "center",
        padding: 24,
        boxSizing: "border-box",
        background:
          "radial-gradient(900px 520px at 50% 0%, rgba(249,115,22,0.16), rgba(0,0,0,0) 65%), linear-gradient(180deg, #0b1220 0%, #05070d 100%)",
      }}
    >
      <div style={{ width: "min(720px, 92vw)", display: "grid", gap: 14 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 4,
          }}
        >
          <h1 style={{ fontSize: 46, margin: 0, color: "#e5e7eb", fontWeight: 900 }}>
            Create Account
          </h1>

          <button type="button" onClick={onBack} style={backBtn}>
            Back to login
          </button>
        </div>

        <p style={{ marginBottom: 6, color: "rgba(229,231,235,0.75)" }}>
          Enter your invite code to create an account.
        </p>

        <form onSubmit={onSubmit} style={{ display: "grid", gap: 12 }}>
          <input
            placeholder="Invite Code"
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
            autoComplete="off"
            style={inputStyle}
          />
          <input
            placeholder="Business Name"
            value={businessName}
            onChange={(e) => setBusinessName(e.target.value)}
            autoComplete="organization"
            style={inputStyle}
          />
          <input
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            style={inputStyle}
          />
          <input
            placeholder="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            style={inputStyle}
          />

          <input
            placeholder="Phone (optional)"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="tel"
            style={inputStyle}
          />
          <input
            placeholder="Google Review Link (optional)"
            value={reviewLink}
            onChange={(e) => setReviewLink(e.target.value)}
            autoComplete="off"
            style={inputStyle}
          />

          {err ? (
            <div style={{ textAlign: "center", fontSize: 14, color: "#fecaca", fontWeight: 800 }}>
              {err}
            </div>
          ) : null}

          <button
            disabled={loading}
            style={{
              ...primaryBtn,
              opacity: loading ? 0.75 : 1,
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "Creating..." : "Create Account"}
          </button>
        </form>
      </div>
    </div>
  );
}
