# app/routers/public.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/lead-form", response_class=HTMLResponse)
def lead_form():
    html = """
<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Request an Estimate</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;background:#f6f7f9;color:#111}
 .wrap{max-width:540px;margin:24px auto;padding:20px;background:#fff;border:1px solid #e5e7eb;border-radius:12px}
 h1{font-size:20px;margin:0 0 12px} form{display:grid;gap:10px}
 label{font-size:12px;color:#555}
 input,textarea{padding:10px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;width:100%}
 button{padding:10px 14px;border:0;border-radius:10px;font-weight:600;cursor:pointer;background:#111;color:#fff}
 button[disabled]{opacity:.6;cursor:not-allowed}
 .note{font-size:12px;color:#666;margin-top:6px}.ok{color:#0a7f2e;font-weight:600}.err{color:#b00020;font-weight:600}
</style></head><body>
<div class="wrap">
  <h1>Request an Estimate</h1>
  <form id="f">
    <div><label>Name</label><input name="name" required placeholder="Jane Doe"></div>
    <div><label>Phone (mobile)</label><input name="phone" required placeholder="+18145551234"></div>
    <div><label>Email</label><input name="email" type="email" required placeholder="jane@example.com"></div>
    <div><label>Issue / Notes</label><textarea name="message" rows="3" placeholder="AC not cooling, short-cycling"></textarea></div>
    <button id="b" type="submit">Send</button>
    <div id="s" class="note"></div>
  </form>
  <div class="note">By submitting, you agree to be contacted about your service request.</div>
</div>
<script>
const f=document.getElementById('f'), b=document.getElementById('b'), s=document.getElementById('s');
const redirectTarget = new URLSearchParams(location.search).get('redirect') || '';
f.addEventListener('submit', async (e)=>{
  e.preventDefault(); s.textContent=''; b.disabled=true;
  const payload=Object.fromEntries(new FormData(f).entries());
  try{
    const r=await fetch('/lead',{method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(payload)});
    const ok=r.ok;
    if(ok && redirectTarget){ window.location.href = redirectTarget; return; }
    let msg='Thanks! We’ll text you a confirmation.';
    try{ const j=await r.json(); if(!ok && j && j.detail) msg=j.detail; }catch(_){}
    s.className=ok?'note ok':'note err'; s.textContent=ok?msg:('Error: '+msg); if(ok) f.reset();
  }catch{ s.className='note err'; s.textContent='Network error. Please try again.'; }
  b.disabled=false;
});
</script>
</body></html>
"""
    return HTMLResponse(html)

@router.get("/thanks", response_class=HTMLResponse)
def thanks():
    return HTMLResponse("""
<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Thanks</title>
<div style="max-width:560px;margin:24px auto;padding:24px;font-family:system-ui">
  <h1 style="margin:0 0 8px">Thanks — request received.</h1>
  <p style="margin:0 0 12px">We’ll reach out shortly to confirm details.</p>
  <a href="/" style="display:inline-block;margin-top:8px;text-decoration:none;padding:10px 14px;background:#111;color:#fff;border-radius:10px">Back to Home</a>
</div>
""")
