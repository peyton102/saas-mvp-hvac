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

const backBtn = {
  padding: "10px 14px",
  fontWeight: 900,
  borderRadius: 12,
  border: "1px solid rgba(249,115,22,0.65)",
  background: "rgba(249,115,22,0.18)",
  color: "#f97316",
  cursor: "pointer",
};

export default function ForgotPasswordPage({ onBack }) {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");

  async function onSubmit(e) {
    e.preventDefault();
    setErr("");
    if (!email.trim()) return setErr("Email is required.");

    setLoading(true);
    try {
      await fetch(`${API_BASE}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
      // Always show success — don't reveal whether email exists
      setSent(true);
    } catch {
      setErr("Network error. Please try again.");
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
      <div style={{ width: "min(520px, 92vw)", display: "grid", gap: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h1 style={{ fontSize: 36, margin: 0, color: "#e5e7eb", fontWeight: 900 }}>
            Forgot Password
          </h1>
          <button type="button" onClick={onBack} style={backBtn}>
            Back to login
          </button>
        </div>

        {sent ? (
          <div
            style={{
              background: "rgba(16,185,129,0.12)",
              border: "1px solid rgba(16,185,129,0.35)",
              borderRadius: 12,
              padding: 20,
              color: "#6ee7b7",
              fontSize: 16,
              lineHeight: 1.6,
            }}
          >
            <strong>Check your email.</strong> If an account exists for{" "}
            <strong>{email}</strong>, you'll receive a password reset link
            shortly. The link expires in 1 hour.
          </div>
        ) : (
          <form onSubmit={onSubmit} style={{ display: "grid", gap: 12 }}>
            <p style={{ margin: 0, color: "rgba(229,231,235,0.75)" }}>
              Enter your account email and we'll send you a reset link.
            </p>
            <input
              placeholder="owner@company.com"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              style={inputStyle}
            />
            {err && (
              <div style={{ fontSize: 14, color: "#fecaca", fontWeight: 800, textAlign: "center" }}>
                {err}
              </div>
            )}
            <button
              type="submit"
              disabled={loading}
              style={{
                width: "100%",
                padding: "18px 20px",
                fontSize: 20,
                fontWeight: 900,
                borderRadius: 14,
                border: "none",
                background: "#f97316",
                color: "#111827",
                cursor: loading ? "not-allowed" : "pointer",
                opacity: loading ? 0.75 : 1,
              }}
            >
              {loading ? "Sending…" : "Send Reset Link"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
