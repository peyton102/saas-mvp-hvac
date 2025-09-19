from fastapi import APIRouter, Request, Response
from app import config

router = APIRouter(prefix="", tags=["public"])

@router.get("/lead-form")
def lead_form(redirect: str = "/thanks"):
    html = f"""
<!doctype html>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{config.FROM_NAME} — Lead Form</title>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 0; padding: 16px; background:#f7f7f8; }}
  .card {{ max-width: 420px; margin: 0 auto; background:#fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.06); padding: 16px; }}
  h1 {{ font-size: 18px; margin: 0 0 8px; }}
  p  {{ margin: 6px 0 14px; color:#444; }}
  label {{ display:block; font-size: 12px; color:#333; margin:10px 0 6px; }}
  input, textarea {{ width:100%; box-sizing:border-box; padding:10px; border:1px solid #ddd; border-radius:8px; font-size:14px; }}
  button {{ width:100%; margin-top:14px; padding:12px; border:0; border-radius:8px; background:#2563eb; color:#fff; font-weight:600; cursor:pointer; }}
  .hint {{ font-size:12px; color:#666; margin-top:8px; }}
</style>
<div class="card">
  <h1>Contact {config.FROM_NAME}</h1>
  <p>Book the next available slot: <a href="{config.BOOKING_LINK}" target="_blank" rel="noopener">{config.BOOKING_LINK}</a></p>
  <form id="leadForm">
    <label>Name</label>
    <input name="name" placeholder="Full name" />
    <label>Phone *</label>
    <input name="phone" placeholder="+1XXXXXXXXXX" required />
    <label>Email</label>
    <input name="email" type="email" placeholder="you@example.com" />
    <label>Message</label>
    <textarea name="message" rows="3" placeholder="What’s going on?"></textarea>
    <button type="submit">Send</button>
    <div class="hint">We’ll text you a link to book. SMS may be in DRY-RUN during testing.</div>
  </form>
</div>
<script>
  const form = document.getElementById('leadForm');
  const redirectTo = new URLSearchParams(window.location.search).get('redirect') || "{redirect}";
  form.addEventListener('submit', async (e) => {{
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    try {{
      const r = await fetch('/lead', {{
        method: 'POST',
        headers: {{ 'Content-Type':'application/json' }},
        body: JSON.stringify(data)
      }});
      if (r.ok) window.location.href = redirectTo;
      else {{
        const body = await r.text();
        alert('Submit failed: ' + body);
      }}
    }} catch (err) {{
      alert('Network error: ' + err);
    }}
  }});
</script>
"""
    return Response(content=html, media_type="text/html")

@router.get("/thanks")
def thanks():
    return Response(
        content="<h2>Thanks! We’ll be in touch shortly.</h2>",
        media_type="text/html",
    )

@router.get("/embed/lead.js")
def lead_widget_js(request: Request, redirect: str = "/thanks"):
    """
    Embed script: <script src="https://YOUR_HOST/embed/lead.js" data-redirect="/thanks"></script>
    Injects an iframe of /lead-form where the script tag is placed.
    """
    base = f"{request.url.scheme}://{request.headers.get('host')}"
    js = f"""
(function() {{
  var script = document.currentScript;
  var redirect = (script && script.dataset && script.dataset.redirect) ? script.dataset.redirect : "{redirect}";
  var iframe = document.createElement('iframe');
  iframe.src = "{base}/lead-form?redirect=" + encodeURIComponent(redirect);
  iframe.style.width = "100%";
  iframe.style.maxWidth = "420px";
  iframe.style.height = "560px";
  iframe.style.border = "0";
  iframe.setAttribute("title", "HVAC Lead Form");
  (script.parentElement || document.body).appendChild(iframe);
}})();
""".strip()
    return Response(
        content=js,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"}
    )

