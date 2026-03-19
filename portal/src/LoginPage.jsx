import React, { useState } from "react";

const API_BASE =
  import.meta?.env?.VITE_API_BASE || "https://saas-mvp-hvac.onrender.com";

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

const linkStyle = {
  border: "none",
  background: "transparent",
  color: "#f97316",
  fontWeight: 900,
  cursor: "pointer",
  padding: 0,
  fontSize: 14,
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

export default function LoginPage({ onLoggedIn, onInviteSignup, onForgotPassword }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);


  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setMsg("");
    setLoading(true);

    try {
            const url = `${API_BASE}/auth/login`;
      const body = { email, password };


      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `HTTP ${res.status}`);
      }

      const data = await res.json(); // { access_token, tenant_slug, api_key }
      onLoggedIn?.(data);
    } catch (err) {
      console.error(err);
      setMsg("Login failed. Check email/password and try again.");
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
      <form
        onSubmit={handleSubmit}
        style={{
          width: "min(720px, 92vw)",
          display: "grid",
          gap: 14,
          margin: 0,
        }}
      >
        {/* ONE Torevez only */}
        <div style={{ textAlign: "center", marginBottom: 2 }}>
          <div style={{ fontSize: 74, fontWeight: 900, letterSpacing: 0.2 }}>
            <span style={{ color: "#e5e7eb" }}>Tore</span>
            <span style={{ color: "#f97316" }}>vez</span>
          </div>
        </div>

        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: "#e5e7eb" }}>
            Email
          </div>
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="owner@company.com"
            autoComplete="email"
            style={inputStyle}
          />
        </div>

        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: "#e5e7eb" }}>Password</div>
          <div style={{ position: "relative" }}>
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              style={{ ...inputStyle, paddingRight: 56 }}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
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
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              <EyeIcon open={showPassword} />
            </button>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%",
            padding: "18px 20px",
            fontSize: 22,
            fontWeight: 900,
            borderRadius: 14,
            border: "none",
            background: "#f97316",
            color: "#111827",
            cursor: loading ? "not-allowed" : "pointer",
            opacity: loading ? 0.75 : 1,
            marginTop: 6,
          }}
        >
                    {loading ? "Please wait…" : "Log in"}
        </button>

        {msg ? (
          <div style={{ textAlign: "center", fontSize: 14, color: "#fecaca" }}>
            {msg}
          </div>
        ) : null}

        <div style={{ textAlign: "center" }}>
          <button type="button" onClick={() => onForgotPassword?.()} style={linkStyle}>
            Forgot password?
          </button>
        </div>

        <div style={{ textAlign: "center", color: "rgba(229,231,235,0.85)" }}>
          Need an invite?{" "}
          <button
            type="button"
        onClick={() => onInviteSignup?.()}
            style={linkStyle}
          >
            Create account
          </button>
        </div>

      </form>
    </div>
  );
}
