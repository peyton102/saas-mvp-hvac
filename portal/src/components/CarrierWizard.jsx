// portal/src/components/CarrierWizard.jsx
// Shown when assistant_status === 'ready' (Part 4 — carrier setup wizard)
import { useState } from "react";

// ── Carrier metadata ──────────────────────────────────────────────────────────

const CARRIERS = [
  { id: "verizon",  label: "Verizon" },
  { id: "att",      label: "AT&T" },
  { id: "tmobile",  label: "T-Mobile" },
  { id: "metro",    label: "Metro by T-Mobile" },
  { id: "spectrum", label: "Spectrum Mobile" },
  { id: "cricket",  label: "Cricket" },
  { id: "boost",    label: "Boost Mobile" },
  { id: "other",    label: "Other" },
];

// CRITICAL FORMAT: digits only, NO plus, NO dashes
function buildActivationCode(carrierId, dialableNumber) {
  const num = (dialableNumber || "").replace(/\D/g, "");
  if (!num) return null;
  switch (carrierId) {
    case "verizon":
    case "spectrum": return `*71${num}`;
    case "att":
    case "cricket":  return `*92${num}#`;
    case "tmobile":
    case "metro":    return `**61*${num}#`;
    default:         return null; // boost, other → no code
  }
}

function deactivationCode(carrierId) {
  switch (carrierId) {
    case "verizon":
    case "spectrum":
    case "boost":    return "*73";
    case "att":
    case "cricket":
    case "tmobile":
    case "metro":    return "##61#";
    default:         return null;
  }
}

function carrierTroubleshootHint(carrierId) {
  if (carrierId === "metro") {
    return "Open the MyMetro app → Account → Add-ons → enable Call Forwarding. Restart your phone, then dial the code again.";
  }
  // All other supported carriers: generic
  return "Call your carrier and ask them to enable conditional call forwarding on your line, then dial the code again.";
}

const needsGetHelp = (carrierId) => carrierId === "boost" || carrierId === "other";

// ── Shared styles ─────────────────────────────────────────────────────────────

const card = {
  padding: "24px 28px",
  borderRadius: 18,
  border: "1px solid rgba(255,255,255,0.09)",
  background: "rgba(255,255,255,0.03)",
};

const btnOrange = {
  padding: "14px 28px",
  fontWeight: 900,
  fontSize: 15,
  borderRadius: 12,
  border: "none",
  background: "#f97316",
  color: "#111827",
  cursor: "pointer",
};

const btnGhost = {
  padding: "12px 24px",
  fontWeight: 700,
  fontSize: 14,
  borderRadius: 12,
  border: "1px solid rgba(249,115,22,0.45)",
  background: "rgba(249,115,22,0.10)",
  color: "#f97316",
  cursor: "pointer",
};

const btnGreen = {
  padding: "14px 28px",
  fontWeight: 900,
  fontSize: 15,
  borderRadius: 12,
  border: "1px solid rgba(110,231,183,0.4)",
  background: "rgba(110,231,183,0.12)",
  color: "#6ee7b7",
  cursor: "pointer",
};

const btnRed = {
  padding: "14px 28px",
  fontWeight: 900,
  fontSize: 15,
  borderRadius: 12,
  border: "1px solid rgba(239,68,68,0.4)",
  background: "rgba(239,68,68,0.10)",
  color: "#f87171",
  cursor: "pointer",
};

// ── Step 1 — Carrier selection ────────────────────────────────────────────────

function StepCarrier({ onSelect }) {
  return (
    <div style={{ display: "grid", gap: 24, maxWidth: 640, margin: "0 auto" }}>
      <div>
        <div style={{ fontSize: 22, fontWeight: 900, color: "#e5e7eb", marginBottom: 6 }}>
          Who's your phone carrier?
        </div>
        <div style={{ fontSize: 14, color: "rgba(229,231,235,0.5)" }}>
          Pick the carrier you use for the phone number you want calls forwarded from.
        </div>
      </div>
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
        gap: 10,
      }}>
        {CARRIERS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => onSelect(id)}
            style={{
              padding: "18px 12px",
              borderRadius: 14,
              border: "1px solid rgba(255,255,255,0.10)",
              background: "rgba(255,255,255,0.04)",
              color: "#e5e7eb",
              fontSize: 14,
              fontWeight: 700,
              cursor: "pointer",
              transition: "all 0.12s",
              textAlign: "center",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.border = "1px solid rgba(249,115,22,0.5)";
              e.currentTarget.style.background = "rgba(249,115,22,0.10)";
              e.currentTarget.style.color = "#f97316";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.border = "1px solid rgba(255,255,255,0.10)";
              e.currentTarget.style.background = "rgba(255,255,255,0.04)";
              e.currentTarget.style.color = "#e5e7eb";
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Step 2 — Code display ─────────────────────────────────────────────────────

function StepCode({ carrierId, dialableNumber, onNext, onBack }) {
  const [troubleshootOpen, setTroubleshootOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const code = buildActivationCode(carrierId, dialableNumber);
  const deactCode = deactivationCode(carrierId);
  const carrierLabel = CARRIERS.find((c) => c.id === carrierId)?.label || carrierId;

  function copyCode() {
    if (!code) return;
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  // Boost / Other → no code, just Get Help
  if (needsGetHelp(carrierId)) {
    return (
      <div style={{ display: "grid", gap: 24, maxWidth: 600, margin: "0 auto" }}>
        <button onClick={onBack} style={{ ...btnGhost, alignSelf: "start", padding: "8px 16px", fontSize: 13 }}>
          ← Back
        </button>
        <div style={card}>
          <div style={{ fontSize: 20, fontWeight: 900, color: "#e5e7eb", marginBottom: 10 }}>
            {carrierId === "boost" ? "Boost Mobile" : "Other carrier"}
          </div>
          <div style={{ fontSize: 14, color: "rgba(229,231,235,0.7)", lineHeight: 1.7, marginBottom: 20 }}>
            {carrierId === "boost"
              ? "Boost Mobile doesn't support conditional call forwarding codes. We'll set this up manually for you."
              : "We need to confirm the right code for your carrier before setting this up."}
          </div>
          <button onClick={onNext} style={btnOrange}>
            Get help from Torevez
          </button>
        </div>
      </div>
    );
  }

  if (!code) {
    return (
      <div style={{ padding: 24, color: "#fca5a5" }}>
        No Torevez number assigned yet. Contact support.
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 24, maxWidth: 600, margin: "0 auto" }}>
      <button onClick={onBack} style={{ ...btnGhost, alignSelf: "start", padding: "8px 16px", fontSize: 13 }}>
        ← Back
      </button>

      {/* Hero: the code */}
      <div style={{
        ...card,
        border: "1px solid rgba(249,115,22,0.3)",
        background: "rgba(249,115,22,0.04)",
        textAlign: "center",
      }}>
        <div style={{ fontSize: 13, color: "rgba(229,231,235,0.5)", marginBottom: 16, fontWeight: 700 }}>
          {carrierLabel} — conditional forwarding code
        </div>

        {/* The code — biggest element on screen */}
        <div style={{
          fontFamily: "monospace",
          fontSize: "clamp(28px, 7vw, 48px)",
          fontWeight: 900,
          color: "#f97316",
          letterSpacing: "0.04em",
          padding: "16px 0",
          wordBreak: "break-all",
        }}>
          {code}
        </div>

        <button
          onClick={copyCode}
          style={{
            ...btnOrange,
            marginBottom: 20,
            minWidth: 160,
            background: copied ? "#22c55e" : "#f97316",
            color: copied ? "#fff" : "#111827",
          }}
        >
          {copied ? "Copied!" : "Copy code"}
        </button>

        <div style={{ fontSize: 15, fontWeight: 700, color: "#e5e7eb" }}>
          Dial this from your phone. Wait for the confirmation tone.
        </div>
      </div>

      {/* Collapsed troubleshoot link */}
      <div>
        <button
          onClick={() => setTroubleshootOpen((o) => !o)}
          style={{
            background: "none",
            border: "none",
            color: "rgba(229,231,235,0.5)",
            fontSize: 13,
            cursor: "pointer",
            padding: 0,
            textDecoration: "underline",
            textUnderlineOffset: 3,
          }}
        >
          Code didn't work? Click here →
        </button>

        {troubleshootOpen && (
          <div style={{
            marginTop: 14,
            padding: "18px 20px",
            borderRadius: 12,
            border: "1px solid rgba(255,255,255,0.08)",
            background: "rgba(0,0,0,0.2)",
            display: "grid",
            gap: 14,
          }}>
            <div style={{ fontSize: 14, color: "rgba(229,231,235,0.8)", lineHeight: 1.6 }}>
              Some carriers need call forwarding switched on for your account first.
              It's usually a ~$1/month add-on and takes about two minutes.
            </div>

            <div style={{ fontSize: 14, color: "#e5e7eb", lineHeight: 1.6 }}>
              {carrierTroubleshootHint(carrierId)}
            </div>

            {deactCode && (
              <div style={{ fontSize: 13, color: "rgba(229,231,235,0.55)", lineHeight: 1.6 }}>
                To clear old forwarding and start over, dial <strong style={{ color: "#e5e7eb", fontFamily: "monospace" }}>{deactCode}</strong> (or <strong style={{ color: "#e5e7eb", fontFamily: "monospace" }}>##002#</strong> to wipe all forwarding), then re-enter the activation code.
              </div>
            )}
          </div>
        )}
      </div>

      <div>
        <button onClick={onNext} style={btnOrange}>
          I dialed it — did it work? →
        </button>
      </div>
    </div>
  );
}

// ── Step 3 — Confirmation ─────────────────────────────────────────────────────

function StepConfirm({ carrierId, dialableNumber, onYes, onNo, onHelp, loading }) {
  const [noExpanded, setNoExpanded] = useState(false);
  const deactCode = deactivationCode(carrierId);
  const code = buildActivationCode(carrierId, dialableNumber);
  const carrierLabel = CARRIERS.find((c) => c.id === carrierId)?.label || carrierId;

  return (
    <div style={{ display: "grid", gap: 24, maxWidth: 600, margin: "0 auto" }}>
      <div style={{ ...card, textAlign: "center" }}>
        <div style={{ fontSize: 22, fontWeight: 900, color: "#e5e7eb", marginBottom: 8 }}>
          Did it work?
        </div>
        <div style={{ fontSize: 14, color: "rgba(229,231,235,0.5)", marginBottom: 28 }}>
          You should have heard a confirmation tone after dialing.
        </div>
        <div style={{ display: "flex", gap: 14, justifyContent: "center", flexWrap: "wrap" }}>
          <button onClick={onYes} disabled={loading} style={{ ...btnGreen, opacity: loading ? 0.6 : 1 }}>
            {loading ? "Saving…" : "Yes, it worked!"}
          </button>
          <button
            onClick={() => { setNoExpanded(true); onNo(); }}
            disabled={loading}
            style={{ ...btnRed, opacity: loading ? 0.6 : 1 }}
          >
            No
          </button>
        </div>
      </div>

      {noExpanded && (
        <div style={{
          padding: "18px 20px",
          borderRadius: 12,
          border: "1px solid rgba(239,68,68,0.2)",
          background: "rgba(239,68,68,0.05)",
          display: "grid",
          gap: 14,
        }}>
          <div style={{ fontSize: 14, color: "rgba(229,231,235,0.8)", lineHeight: 1.6 }}>
            Some carriers need call forwarding switched on for your account first.
            It's usually a ~$1/month add-on and takes about two minutes.
          </div>
          <div style={{ fontSize: 14, color: "#e5e7eb", lineHeight: 1.6 }}>
            {carrierTroubleshootHint(carrierId)}
          </div>
          {deactCode && code && (
            <div style={{ fontSize: 13, color: "rgba(229,231,235,0.55)", lineHeight: 1.6 }}>
              To clear old forwarding and start over, dial{" "}
              <strong style={{ color: "#e5e7eb", fontFamily: "monospace" }}>{deactCode}</strong>
              {" "}(or <strong style={{ color: "#e5e7eb", fontFamily: "monospace" }}>##002#</strong> to wipe all forwarding), then re-enter{" "}
              <strong style={{ color: "#f97316", fontFamily: "monospace" }}>{code}</strong>.
            </div>
          )}
          <button onClick={onHelp} style={{ ...btnOrange, alignSelf: "start" }}>
            Get help from Torevez
          </button>
        </div>
      )}
    </div>
  );
}

// ── Success screen ────────────────────────────────────────────────────────────

function SuccessScreen() {
  return (
    <div style={{ display: "grid", gap: 20, maxWidth: 560, margin: "0 auto", textAlign: "center" }}>
      <div style={{
        ...card,
        border: "1px solid rgba(52,211,153,0.3)",
        background: "rgba(52,211,153,0.05)",
      }}>
        <div style={{ fontSize: 48, marginBottom: 12 }}>✓</div>
        <div style={{ fontSize: 24, fontWeight: 900, color: "#34d399", marginBottom: 10 }}>
          You're all set!
        </div>
        <div style={{ fontSize: 15, color: "rgba(229,231,235,0.7)", lineHeight: 1.6 }}>
          Your Torevez assistant is now live. Missed calls will be answered automatically
          and captured as leads in your dashboard.
        </div>
      </div>
    </div>
  );
}

// ── Main wizard component ─────────────────────────────────────────────────────

export default function CarrierWizard({ me, apiBase, commonHeaders, onComplete }) {
  const [step, setStep] = useState(1); // 1 | 2 | 3 | "success" | "help-sent"
  const [carrier, setCarrier] = useState(null);
  const [loading, setLoading] = useState(false);

  // Strip non-digits from the stored number — critical format rule
  const dialableNumber = (me?.torevez_dialable_number || "").replace(/\D/g, "");

  async function saveCarrier(carrierId) {
    // Best-effort save — don't block UX on failure
    try {
      await fetch(`${apiBase}/onboarding/carrier`, {
        method: "PATCH",
        headers: commonHeaders,
        body: JSON.stringify({ carrier: carrierId }),
      });
    } catch (_) {}
  }

  async function handleCarrierSelect(carrierId) {
    setCarrier(carrierId);
    await saveCarrier(carrierId);
    setStep(2);
  }

  function handleCodeNext() {
    if (needsGetHelp(carrier)) {
      // Boost / Other → trigger help immediately
      handleHelp();
    } else {
      setStep(3);
    }
  }

  async function handleYes() {
    setLoading(true);
    try {
      await fetch(`${apiBase}/onboarding/complete`, {
        method: "POST",
        headers: commonHeaders,
      });
      setStep("success");
      if (onComplete) onComplete();
    } catch (_) {
      setStep("success"); // still show success — don't block customer
      if (onComplete) onComplete();
    } finally {
      setLoading(false);
    }
  }

  async function handleHelp() {
    try {
      await fetch(`${apiBase}/onboarding/help`, {
        method: "POST",
        headers: commonHeaders,
      });
    } catch (_) {}
    setStep("help-sent");
  }

  if (step === "success") return <SuccessScreen />;

  if (step === "help-sent") {
    return (
      <div style={{ display: "grid", gap: 16, maxWidth: 560, margin: "0 auto", textAlign: "center" }}>
        <div style={{ ...card, border: "1px solid rgba(96,165,250,0.3)", background: "rgba(96,165,250,0.05)" }}>
          <div style={{ fontSize: 22, fontWeight: 900, color: "#60a5fa", marginBottom: 10 }}>
            Help is on the way
          </div>
          <div style={{ fontSize: 14, color: "rgba(229,231,235,0.7)", lineHeight: 1.7 }}>
            We've been notified and will reach out to you directly to get this sorted.
            You don't need to do anything else right now.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 8 }}>
      {/* Step indicator */}
      {step !== "success" && step !== "help-sent" && (
        <div style={{
          display: "flex",
          gap: 6,
          marginBottom: 8,
          fontSize: 12,
          color: "rgba(229,231,235,0.35)",
          fontWeight: 700,
        }}>
          {[1, 2, 3].map((n) => (
            <span key={n} style={{
              color: step === n ? "#f97316" : "rgba(229,231,235,0.25)",
              fontWeight: step === n ? 900 : 400,
            }}>
              {n === 1 ? "Carrier" : n === 2 ? "Dial code" : "Confirm"}
              {n < 3 && <span style={{ marginLeft: 6, opacity: 0.3 }}>›</span>}
            </span>
          ))}
        </div>
      )}

      {step === 1 && (
        <StepCarrier onSelect={handleCarrierSelect} />
      )}

      {step === 2 && (
        <StepCode
          carrierId={carrier}
          dialableNumber={dialableNumber}
          onNext={handleCodeNext}
          onBack={() => setStep(1)}
        />
      )}

      {step === 3 && (
        <StepConfirm
          carrierId={carrier}
          dialableNumber={dialableNumber}
          onYes={handleYes}
          onNo={() => {}} // auto-expand handled inside StepConfirm
          onHelp={handleHelp}
          loading={loading}
        />
      )}
    </div>
  );
}
