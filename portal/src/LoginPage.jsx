// portal/src/LoginPage.jsx
import { useState } from "react";
import { setToken } from "./auth";

// Always talk to the backend on Render
const API_BASE =
  import.meta?.env?.VITE_API_BASE ||
  "https://saas-mvp-hvac.onrender.com";

export default function LoginPage({ onLoggedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    try {
      const resp = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, password }),
      });

      // Read the body ONCE
      const text = await resp.text();
      let data = {};
      try {
        data = text ? JSON.parse(text) : {};
      } catch {
        data = {};
      }

      if (!resp.ok) {
        throw new Error(
          data.detail || `Login failed (HTTP ${resp.status})`
        );
      }

      // expect { access_token, tenant_slug, api_key }
      if (!data.access_token) {
        throw new Error("No access_token in response");
      }

      setToken(data.access_token);

      if (onLoggedIn) {
        onLoggedIn(data);
      }
    } catch (err) {
      setError(err.message || "Login failed");
    }
  }

  return (
    <div style={{ maxWidth: 320, margin: "80px auto", padding: 16 }}>
      <h2>Log in</h2>
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 8 }}>
          <label>Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={{ width: "100%" }}
          />
        </div>
        <div style={{ marginBottom: 8 }}>
          <label>Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{ width: "100%" }}
          />
        </div>
        {error && (
          <div style={{ color: "red", marginBottom: 8 }}>{error}</div>
        )}
        <button type="submit">Log in</button>
      </form>
    </div>
  );
}
