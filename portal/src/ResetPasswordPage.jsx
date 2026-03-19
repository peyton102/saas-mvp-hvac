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

function EyeIcon({ open }) {
  return open ? (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  ) : (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
      <line x1="1" y1="1" x2="23" y2="23"/>
    </svg>
  );
}

function PasswordInput({ placeholder, value, onChange, show, onToggle }) {
  return (
    <div style={{ position: "relative" }}>
      <input
        placeholder={placeholder}
        type={show ? "text" : "password"}
        value={value}
        onChange={onChange}
        autoComplete="new-password"
        style={{ ...inputStyle, paddingRight: 56 }}
      />
      <button
        type="button"
        onClick={onToggle}
        style={{
          position: "absolute",
          right: 14,
          top: "50%",
          transform: "translateY(-50%)",
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "#6b7280",
          padding: 4,
          display: "flex",
          alignItems: "center",
        }}
        aria-label={show ? "Hide password" : "Show password"}
      >
        <EyeIcon open={show} />
      </button>
    </div>
  );
}

export default function ResetPasswordPage({ token, onDone }) {
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [err, setErr] = useState("");

  const toggleShow = () => setShowPassword((v) => !v);

  async function onSubmit(e) {
    e.preventDefault();
    setErr("");

    if (!password) return setErr("Password is required.");
    if (password.length < 8) return setErr("Password must be at least 8 characters.");
    if (password !== confirmPassword) return setErr("Passwords do not match.");

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setErr(data?.detail || "Reset failed. The link may have expired.");
        return;
      }
      setSuccess(true);
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
        <h1 style={{ fontSize: 36, margin: 0, color: "#e5e7eb", fontWeight: 900 }}>
          Set New Password
        </h1>

        {success ? (
          <div style={{ display: "grid", gap: 16 }}>
            <div
              style={{
                background: "rgba(16,185,129,0.12)",
                border: "1px solid rgba(16,185,129,0.35)",
                borderRadius: 12,
                padding: 20,
                color: "#6ee7b7",
                fontSize: 16,
              }}
            >
              <strong>Password updated.</strong> You can now log in with your new password.
            </div>
            <button
              type="button"
              onClick={onDone}
              style={{
                width: "100%",
                padding: "18px 20px",
                fontSize: 20,
                fontWeight: 900,
                borderRadius: 14,
                border: "none",
                background: "#f97316",
                color: "#111827",
                cursor: "pointer",
              }}
            >
              Go to Login
            </button>
          </div>
        ) : (
          <form onSubmit={onSubmit} style={{ display: "grid", gap: 12 }}>
            <p style={{ margin: 0, color: "rgba(229,231,235,0.75)" }}>
              Choose a new password for your account.
            </p>
            <PasswordInput
              placeholder="New password (min 8 characters)"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              show={showPassword}
              onToggle={toggleShow}
            />
            <PasswordInput
              placeholder="Confirm new password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              show={showPassword}
              onToggle={toggleShow}
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
              {loading ? "Saving…" : "Set New Password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
