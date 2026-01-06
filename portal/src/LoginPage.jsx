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

export default function LoginPage({ onLoggedIn }) {
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [businessName, setBusinessName] = useState("");

  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setMsg("");
    setLoading(true);

    try {
      const url =
        mode === "login" ? `${API_BASE}/auth/login` : `${API_BASE}/auth/signup`;

      const body =
        mode === "login"
          ? { email, password }
          : { email, password, business_name: businessName || "New Business" };

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

        {mode === "signup" && (
          <div style={{ display: "grid", gap: 8 }}>
            <div style={{ fontSize: 16, fontWeight: 900, color: "#e5e7eb" }}>
              Business name
            </div>
            <input
              value={businessName}
              onChange={(e) => setBusinessName(e.target.value)}
              placeholder="Acme HVAC"
              autoComplete="organization"
              style={inputStyle}
            />
          </div>
        )}

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
          <div style={{ fontSize: 16, fontWeight: 900, color: "#e5e7eb" }}>
            Password
          </div>
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            style={inputStyle}
          />
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
          {loading ? "Please wait…" : mode === "login" ? "Log in" : "Sign up"}
        </button>

        {msg ? (
          <div style={{ textAlign: "center", fontSize: 14, color: "#fecaca" }}>
            {msg}
          </div>
        ) : null}

        <div style={{ textAlign: "center", color: "rgba(229,231,235,0.85)" }}>
          {mode === "login" ? (
            <>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => setMode("login")}
                style={linkStyle}
              >
                Log in
              </button>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
