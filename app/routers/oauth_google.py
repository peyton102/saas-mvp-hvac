from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from app.services.google_calendar import build_flow, save_creds
import os
from pathlib import Path

router = APIRouter()

@router.get("/oauth/google/start")
def oauth_google_start():
    flow = build_flow()
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return RedirectResponse(url)

@router.get("/oauth/google/callback")
def oauth_google_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(400, "Missing code")
    flow = build_flow()
    flow.fetch_token(code=code)
    save_creds(flow.credentials)

    # Verify the file actually exists where we expect
    d = Path(os.getenv("GOOGLE_TOKEN_DIR", "data/google_tokens"))
    p = d / "default.json"
    return {
        "ok": True,
        "msg": "Google authorized. Call /availability next.",
        "token_path": str(p),
        "exists": p.exists(),
        "size": (p.stat().st_size if p.exists() else 0),
    }

@router.get("/debug/google-config")
def google_cfg():
    return {
        "client_id_prefix": (os.getenv("GOOGLE_CLIENT_ID","")[:20] + "..."),
        "redirect_uri": os.getenv("GOOGLE_OAUTH_REDIRECT_URI"),
        "scopes": os.getenv("GOOGLE_SCOPES"),
        "token_dir": os.getenv("GOOGLE_TOKEN_DIR", "data/google_tokens"),
    }

@router.get("/debug/google-token")
def google_token():
    p = Path(os.getenv("GOOGLE_TOKEN_DIR","data/google_tokens")) / "default.json"
    return {"path": str(p), "exists": p.exists(), "size": (p.stat().st_size if p.exists() else 0)}
