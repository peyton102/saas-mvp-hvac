import React, { useEffect, useMemo, useState } from "react";
import LeadsCard from "./components/LeadsCard.jsx";
import BookingBlank from "./components/BookingsCard.jsx";
import FinanceCard from "./components/FinanceCard.jsx";
import LoginPage from "./LoginPage";
import TenantSettingsCard from "./components/TenantSettingsCard.jsx";
import { getToken, setToken, clearToken } from "./auth";
import InviteSignupPage from "./InviteSignupPage.jsx";
import ForgotPasswordPage from "./ForgotPasswordPage.jsx";
import ResetPasswordPage from "./ResetPasswordPage.jsx";
import BookingAvailabilityCard from "./components/BookingAvailabilityCard.jsx";
import MissedCallsCard from "./components/MissedCallsCard.jsx";
import AdminTab from "./components/AdminTab.jsx";

// ====== CONFIG ======
const API_BASE =
  import.meta?.env?.VITE_API_BASE ||
  "https://saas-mvp-hvac.onrender.com";   // 👈 fallback to Render backend

const BASE = API_BASE;

const params = new URLSearchParams(window.location.search || "");
const TENANT_KEY = params.get("tenant") || "default";   // 👈 read from ?tenant=
const NGROK_HEADER = { "ngrok-skip-browser-warning": "true" };
// use same base for auth for now




function PortalApp({ me }) {
  const features = me?.features || [];
  const has = (f) => features.includes(f);

  const [tab, setTab] = useState("home");
  const [apiHealth, setApiHealth] = useState("checking…");
  const [settingsComplete, setSettingsComplete] = useState(false);

  const needsSetup = me?.needs_setup;
  const TENANT_SLUG =
  localStorage.getItem("TENANT_SLUG") ||
  "default";
  const token = getToken();

  function handleLogout() {
    clearToken();
    window.location.href = "/"; // force full reload to login screen
  }
  // ====== API health ping (hits BASE directly) ======
  useEffect(() => {
    async function ping() {
      try {
        const r = await fetch(`${BASE}/health`, { headers: NGROK_HEADER });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        setApiHealth(`OK (env=${j.env})`);
      } catch (e) {
        setApiHealth(`ERROR: ${String(e)}`);
      }
    }
    ping();
  }, []);


const headers = useMemo(() => {
  const h = {
    ...NGROK_HEADER,
    "Content-Type": "application/json",
  };

  const apiKey = localStorage.getItem("API_KEY");
  if (apiKey) {
    h["X-API-Key"] = apiKey;
  }

  if (token) {
    h["Authorization"] = `Bearer ${token}`;
  }

  return h;
}, [token]);






      return (
  <div
    style={{
      minHeight: "100vh",
      width: "100%",
      boxSizing: "border-box",
      padding: "16px",
      background:
        "radial-gradient(900px 520px at 50% 0%, rgba(249,115,22,0.14), rgba(0,0,0,0) 65%), linear-gradient(180deg, #0b1220 0%, #05070d 100%)",
      color: "#e5e7eb",
      fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Arial",
    }}
  >
    {/* centered page container */}
    <div style={{ width: "100%", maxWidth: 1180, margin: "0 auto", minWidth: 0 }}>
      {/* top bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 18,
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 28, fontWeight: 900, letterSpacing: 0.2 }}>
            <span style={{ color: "#e5e7eb" }}>Tore</span>
            <span style={{ color: "#f97316" }}>vez</span>
          </div>
          <div style={{ fontSize: 13, color: "rgba(229,231,235,0.75)" }}>
            Client management, bookings, and finance — in one place.
          </div>
        </div>

        <button
          onClick={handleLogout}
          style={{
            padding: "10px 14px",
            color: "#111827",
            fontSize: 13,
            fontWeight: 800,
            borderRadius: 10,
            border: "none",
            background: "#f97316",
            cursor: "pointer",
          }}
        >
          Log out
        </button>
      </div>

      {/* setup banner */}
      {needsSetup && !settingsComplete && (

        <div
          style={{
            marginBottom: 14,
            padding: 14,
            borderRadius: 14,
            background: "rgba(249,115,22,0.10)",
            border: "1px solid rgba(249,115,22,0.35)",
            color: "#fde68a",
            fontSize: 14,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div style={{ color: "rgba(229,231,235,0.9)" }}>
            <strong style={{ color: "#fde68a" }}>Finish your setup:</strong>{" "}
            Add business phone, email, and review link in Settings so reminders go to the right place.
          </div>

          <button
            type="button"
            onClick={() => {
              setTab("settings");
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
            style={{
              padding: "10px 12px",
              borderRadius: 10,
              border: "1px solid rgba(249,115,22,0.55)",
              background: "rgba(249,115,22,0.18)",
              color: "#f97316",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 900,
              whiteSpace: "nowrap",
            }}
          >
            Go to settings
          </button>
        </div>
      )}

      {/* tabs */}
      <div
        className="portal-tabs-bar"
        style={{
          display: "flex",
          gap: 8,
          padding: 8,
          borderRadius: 16,
          border: "1px solid rgba(255,255,255,0.10)",
          background: "rgba(255,255,255,0.04)",
          backdropFilter: "blur(10px)",
          marginBottom: 16,
        }}
      >
        <TopTab label="Home" active={tab === "home"} onClick={() => setTab("home")} />
        {has("finance") && (
          <TopTab label="Finance" active={tab === "finance"} onClick={() => setTab("finance")} />
        )}
        {has("leads") && (
          <TopTab label="Leads" active={tab === "leads"} onClick={() => setTab("leads")} />
        )}
        {has("vapi") && (
          <TopTab label="Calls" active={tab === "calls"} onClick={() => setTab("calls")} />
        )}
        {has("bookings") && (
          <TopTab label="Bookings" active={tab === "bookings"} onClick={() => setTab("bookings")} />
        )}
        <TopTab label="Settings" active={tab === "settings"} onClick={() => setTab("settings")} />
        {me?.is_admin && (
          <TopTab label="Admin" active={tab === "admin"} onClick={() => setTab("admin")} admin />
        )}
      </div>

      {/* page body */}
      <div
        style={{
          borderRadius: 18,
          border: "1px solid rgba(255,255,255,0.10)",
          background: "rgba(255,255,255,0.03)",
          backdropFilter: "blur(10px)",
          padding: "16px 12px",
          minWidth: 0,
        }}
      >
        {/* Settings card mount */}
        <div id="tenant-settings"></div>

        {tab === "bookings" && (
          <BookingBlank
            tenantKey={TENANT_KEY}
            tenantSlug={TENANT_KEY} // 👈 match the URL tenant
            apiBase={API_BASE}
            commonHeaders={headers}
          />
        )}

        {tab === "home" && (
          <div style={{ display: "grid", gap: 12 }}>
            <div
              style={{
                border: "1px solid rgba(255,255,255,0.10)",
                borderRadius: 16,
                padding: 18,
                background: "rgba(0,0,0,0.12)",
              }}
            >
              <h2 style={{ margin: 0, fontSize: 22 }}>Welcome</h2>
              <p style={{ marginTop: 8, color: "rgba(229,231,235,0.75)" }}>
                Choose a section above to get started.
              </p>
            </div>
          </div>
        )}

        {tab === "settings" && (
          <>
            <TenantSettingsCard
              apiBase={BASE}
              commonHeaders={headers}
              tenantSlug={TENANT_SLUG}
              onCompleteChange={setSettingsComplete}
            />
            <BookingAvailabilityCard
              apiBase={BASE}
              commonHeaders={headers}
              tenantSlug={TENANT_SLUG}
            />
          </>
        )}


        {/* FINANCE */}
        {tab === "finance" && (
          <FinanceCard apiBase={BASE} commonHeaders={headers} />
        )}

        {tab === "leads" && (
          <LeadsCard tenantKey={TENANT_KEY} apiBase={BASE} commonHeaders={headers} />
        )}

        {tab === "calls" && (
          <MissedCallsCard apiBase={BASE} commonHeaders={headers} />
        )}

        {tab === "admin" && me?.is_admin && (
          <AdminTab apiBase={BASE} commonHeaders={headers} />
        )}
      </div>
    </div>
  </div>
);

/** inline helper component for tabs */
function TopTab({ label, active, onClick, admin = false }) {
  return (
    <button
      onClick={onClick}
      disabled={active}
      style={{
        padding: "9px 11px",
        borderRadius: 12,
        flexShrink: 0,
        fontSize: 13,
        border: admin
          ? (active ? "1px solid rgba(167,139,250,0.5)" : "1px solid rgba(167,139,250,0.25)")
          : "1px solid rgba(255,255,255,0.10)",
        background: admin
          ? (active ? "rgba(167,139,250,0.18)" : "rgba(167,139,250,0.07)")
          : (active ? "rgba(249,115,22,0.18)" : "rgba(255,255,255,0.04)"),
        color: admin
          ? (active ? "#a78bfa" : "rgba(167,139,250,0.85)")
          : (active ? "#f97316" : "rgba(229,231,235,0.85)"),
        fontWeight: 900,
        cursor: active ? "default" : "pointer",
      }}
    >
      {label}
    </button>
  );
}

}

// ---------- Auth wrapper ----------

function App() {
  const [me, setMe] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [showInviteSignup, setShowInviteSignup] = useState(false);
  const [showForgotPassword, setShowForgotPassword] = useState(false);

  // Check URL for ?reset_token=, ?invite=, ?email= on initial load
  const resetToken  = new URLSearchParams(window.location.search).get("reset_token");
  const inviteParam = new URLSearchParams(window.location.search).get("invite");
  const emailParam  = new URLSearchParams(window.location.search).get("email");


  async function fetchMe(token) {
    try {
      const resp = await fetch(`${API_BASE}/auth/me`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!resp.ok) {
        throw new Error("Not authenticated");
      }

      const data = await resp.json(); // { email, tenant_slug, needs_setup, ... }
      setMe(data);
    } catch (err) {
      console.error("auth/me error", err);
      clearToken();
      setMe(null);
    } finally {
      setAuthLoading(false);
    }
  }

  useEffect(() => {
    const token = getToken();
    if (token) {
      fetchMe(token);
    } else {
      setAuthLoading(false);
    }
  }, []);

function handleLoggedIn(loginData) {
  // 0️⃣ SAVE TOKEN (this is what you're missing)
  setToken(loginData.access_token);

  if (loginData?.tenant_slug) {
    localStorage.setItem("TENANT_SLUG", loginData.tenant_slug);
  }

  if (loginData?.api_key) {
    localStorage.setItem("API_KEY", loginData.api_key);
  }

  fetchMe(loginData.access_token);
}


  if (authLoading) {
    return <div style={{ padding: 16 }}>Loading…</div>;
  }

  const token = getToken();
  if (!token || !me) {
    // Password reset link — show reset form regardless of auth state
    if (resetToken) {
      return (
        <ResetPasswordPage
          token={resetToken}
          onDone={() => {
            window.history.replaceState({}, "", "/");
            window.location.reload();
          }}
        />
      );
    }

    if (showInviteSignup || inviteParam) {
      return (
        <InviteSignupPage
          onSignedUp={(data) => {
            if (inviteParam) window.history.replaceState({}, "", "/");
            handleLoggedIn(data);
          }}
          onBack={() => {
            if (inviteParam) window.history.replaceState({}, "", "/");
            setShowInviteSignup(false);
          }}
          initialCode={inviteParam || ""}
          initialEmail={emailParam || ""}
        />
      );
    }

    if (showForgotPassword) {
      return (
        <ForgotPasswordPage
          onBack={() => setShowForgotPassword(false)}
        />
      );
    }

    return (
      <LoginPage
        onLoggedIn={handleLoggedIn}
        onInviteSignup={() => setShowInviteSignup(true)}
        onForgotPassword={() => setShowForgotPassword(true)}
      />
    );
  }


  // Logged-in: show the real portal
    // Logged-in: show the real portal
  return <PortalApp me={me} />;
}

export default App;
