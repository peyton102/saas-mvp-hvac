from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from app.services.google_calendar import build_flow, save_creds

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
    return {"ok": True, "msg": "Google authorized. Call /availability next."}
