// portal/src/LoginPage.jsx
import { useState } from "react";
import { setToken } from "./auth";

const API_BASE =
  import.meta?.env?.VITE_API_BASE ||
  "https://saas-mvp-hvac.onrender.com"; // backend on Render

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

    let data = null;
    try {
      data = await resp.json();
    } catch {
      data = null;
    }

    if (!resp.ok) {
      const msg =
        (data && data.detail) ||
        (typeof data === "string" ? data : "Login failed");
      throw new Error(msg);
    }

    // data is now the parsed JSON from backend
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
