import { useEffect, useState } from "react";
const BASE = "/api";

export default function WhoAmIStatus() {
  const [data, setData] = useState(null);
  const [verbose, setVerbose] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const a = await fetch(`${BASE}/whoami`).then(r=>r.json());
        const b = await fetch(`${BASE}/debug/whoami-verbose`).then(r=>r.json());
        if (!alive) return;
        setData(a); setVerbose(b);
      } catch {
        /* ignore */
      }
    })();
    return () => { alive = false; };
  }, []);

  if (!data) return null;

  return (
    <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:12, marginBottom:12, fontSize:13 }}>
      <div><strong>Tenant:</strong> {data.tenant_id}</div>
      <div style={{ color:"#6b7280" }}>
        auth header seen: {verbose?.headers_seen?.authorization_startswith ? "yes" : "no"} ·
        X-API-Key present: {String(verbose?.headers_seen?.x_api_key_present)}
      </div>
    </div>
  );
}
