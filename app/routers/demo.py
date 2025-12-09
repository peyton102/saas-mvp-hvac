# app/routers/demo.py
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Lead as LeadModel
from app.deps import get_tenant_id

router = APIRouter(tags=["demo"])

@router.get("/demo", response_class=HTMLResponse)
def demo_page():
    # Plain string (no f-strings) to avoid brace issues
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>SaaSMVP Demo</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:24px}
    button,input{padding:8px;border-radius:8px;border:1px solid #ccc}
    .log{white-space:pre-wrap;background:#f7f7f9;border:1px solid #eee;border-radius:8px;padding:12px;min-height:80px}
    .row{display:flex;gap:8px;margin:8px 0}
    .card{border:1px solid #ddd;border-radius:12px;padding:16px;margin:12px 0}
  </style>
</head>
<body>
  <h1>SaaSMVP Demo (no SMS required)</h1>

  <div class="card">
    <h2>Voice test</h2>
    <p>Call your Twilio number. Then click "Load Latest Leads". You should see an "Inbound call" row.</p>
    <div class="row">
      <button onclick="loadLeads()">Load Latest Leads</button>
    </div>
    <div id="leads" class="log"></div>
  </div>

  <div class="card">
    <h2>Create a Lead (manual)</h2>
    <div class="row"><input id="name"  placeholder="Name"  value="Site Lead"></div>
    <div class="row"><input id="phone" placeholder="+1814555..." value="+18145550001"></div>
    <div class="row"><input id="email" placeholder="email" value="lead@example.com"></div>
    <div class="row"><input id="msg"   placeholder="message" value="test lead"></div>
    <div class="row"><button onclick="createLead()">Create Lead</button></div>
    <div id="lead_out" class="log"></div>
  </div>

<script>
async function loadLeads(){
  const r = await fetch('/demo/leads');
  const j = await r.json();
  document.getElementById('leads').textContent = JSON.stringify(j, null, 2);
}
async function createLead(){
  const body = {
    name:  document.getElementById('name').value,
    phone: document.getElementById('phone').value,
    email: document.getElementById('email').value,
    message: document.getElementById('msg').value
  };
  const r = await fetch('/demo/lead', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const j = await r.json();
  document.getElementById('lead_out').textContent = JSON.stringify(j, null, 2);
}
</script>
</body>
</html>
    """

# No-debug helper: list latest leads for current tenant (no special headers needed)
@router.get("/demo/leads")
def demo_leads(session: Session = Depends(get_session), tenant_id: str = Depends(get_tenant_id)):
    rows = session.exec(
        select(LeadModel)
        .where(LeadModel.tenant_id == tenant_id)
        .order_by(LeadModel.id.desc())
        .limit(5)
    ).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "name": r.name,
            "phone": r.phone,
            "email": r.email,
            "message": r.message,
            "tenant_id": r.tenant_id,
        }
        for r in rows
    ]

# No-debug helper: create a lead (same as POST /lead but here for the demo page)
@router.post("/demo/lead")
def demo_create_lead(payload: dict, session: Session = Depends(get_session), tenant_id: str = Depends(get_tenant_id)):
    lead = LeadModel(
        name=(payload.get("name") or "").strip(),
        phone=(payload.get("phone") or "").strip(),
        email=(payload.get("email") or "").strip(),
        message=(payload.get("message") or "").strip(),
        tenant_id=tenant_id,
    )
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return {"ok": True, "id": lead.id}
