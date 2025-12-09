import os
import requests
from sqlmodel import Session, select
from app.models import Tenant

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

def resolve_and_save_google_review_link(db: Session, tenant_slug: str) -> dict:
    # fetch tenant
    t = db.exec(select(Tenant).where(Tenant.slug == tenant_slug)).first()
    if not t:
        return {"ok": False, "error": "tenant_not_found"}

    if not GOOGLE_API_KEY:
        return {"ok": False, "error": "missing_api_key"}

    # build a query from business_name + address OR website
    if (t.business_name or "").strip():
        q = t.business_name.strip()
        if (t.address or "").strip():
            q += f", {t.address.strip()}"
    elif (t.website or "").strip():
        q = t.website.strip()
    else:
        return {"ok": False, "error": "missing_profile_fields"}

    # Google Places Find Place
    url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
    params = {
        "input": q,
        "inputtype": "textquery",
        "fields": "place_id,name,formatted_address",
        "key": GOOGLE_API_KEY,
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    candidates = (data or {}).get("candidates", [])
    if not candidates:
        return {"ok": False, "error": "no_match"}

    place_id = candidates[0].get("place_id")
    if not place_id:
        return {"ok": False, "error": "no_place_id"}

    review_url = f"https://search.google.com/local/writereview?placeid={place_id}"

    # save on tenant
    t.review_google_url = review_url
    db.add(t)
    db.commit()
    db.refresh(t)

    return {"ok": True, "review_google_url": review_url, "matched_name": candidates[0].get("name"), "matched_address": candidates[0].get("formatted_address")}
