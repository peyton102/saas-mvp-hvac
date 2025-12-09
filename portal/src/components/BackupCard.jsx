import { useMemo } from "react";
const BASE = "/api";

export default function BackupCard({ tenantKey }) {
  const headers = useMemo(() => ({
    "X-API-Key": tenantKey
  }), [tenantKey]);

  async function download(path, filename) {
    const res = await fetch(`${BASE}${path}`, { headers });
    if (!res.ok) { alert(`Download failed: ${res.status}`); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div style={{ border:"1px solid #e5e7eb", borderRadius:12, padding:16, marginTop:16 }}>
      <h2 style={{ marginTop:0 }}>Backup / Export</h2>
      <p style={{ marginTop:6, color:"#6b7280", fontSize:13 }}>
        Download CSV backups for peace of mind. (Tenant-scoped)
      </p>
      <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
        <button onClick={()=>download("/backup/leads.csv", "leads.csv")}>Download Leads CSV</button>
        <button onClick={()=>download("/backup/finance.csv", "finance.csv")}>Download Finance CSV</button>
      </div>
    </div>
  );
}
