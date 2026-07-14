// portal/src/components/WelcomeCard.jsx
// Shown when assistant_status === 'pending' (first login after signup)

export default function WelcomeCard() {
  return (
    <div style={{ display: "grid", gap: 20, maxWidth: 720, margin: "0 auto" }}>

      {/* Video section */}
      <div style={{
        borderRadius: 18,
        border: "1px solid rgba(249,115,22,0.25)",
        background: "rgba(249,115,22,0.05)",
        overflow: "hidden",
      }}>
        <div style={{
          padding: "16px 20px 12px",
          fontSize: 18,
          fontWeight: 900,
          color: "#e5e7eb",
        }}>
          Watch this first
        </div>

        {/* Video embed — replace src with real URL when ready */}
        <div style={{
          position: "relative",
          width: "100%",
          paddingBottom: "56.25%", // 16:9
          background: "#0b1220",
        }}>
          <iframe
            src="https://www.youtube.com/embed/yGFZ767y0m0"
            title="Torevez walkthrough"
            frameBorder="0"
            allowFullScreen
            style={{
              position: "absolute",
              top: 0, left: 0,
              width: "100%", height: "100%",
              borderRadius: "0 0 0 0",
            }}
          />
        </div>
      </div>

      {/* Status banner */}
      <div style={{
        padding: "18px 22px",
        borderRadius: 14,
        border: "1px solid rgba(96,165,250,0.25)",
        background: "rgba(96,165,250,0.06)",
        display: "flex",
        gap: 14,
        alignItems: "flex-start",
      }}>
        <div style={{
          marginTop: 2,
          width: 10, height: 10,
          borderRadius: "50%",
          background: "#60a5fa",
          flexShrink: 0,
          boxShadow: "0 0 8px rgba(96,165,250,0.6)",
        }} />
        <div style={{ fontSize: 15, color: "#e5e7eb", lineHeight: 1.6 }}>
          Your AI assistant is being set up. Nothing needed from you yet.
          I'll text you the moment it's ready.
        </div>
      </div>

    </div>
  );
}
