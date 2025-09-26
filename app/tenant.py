# app/tenant.py
from typing import Any, Dict
from app import config

def _tenant_overrides() -> Dict[str, Dict[str, Any]]:
    """
    Put per-tenant overrides here (or load from DB later).
    Shape:
    {
      "default": {"FROM_NAME": "Your Brand", "BOOKING_LINK": "https://..."},
      "acme":    {"FROM_NAME": "Acme HVAC",   "BOOKING_LINK": "https://..."},
    }
    """
    # Support either config.TENANT_BRANDS or config.settings.TENANT_BRANDS
    brands = getattr(config, "TENANT_BRANDS", None)
    if brands is None and hasattr(config, "settings"):
        brands = getattr(config.settings, "TENANT_BRANDS", None)
    return brands or {}

def brand(tenant_id: str) -> Dict[str, Any]:
    """
    Returns a dict with at least FROM_NAME and BOOKING_LINK
    (falling back to global config if not overridden).
    """
    overrides = _tenant_overrides().get(tenant_id, {})
    # support both config.<NAME> and config.settings.<NAME>
    FROM_NAME = (
        overrides.get("FROM_NAME")
        or getattr(config, "FROM_NAME", None)
        or getattr(getattr(config, "settings", object()), "FROM_NAME", "Your HVAC")
    )
    BOOKING_LINK = (
        overrides.get("BOOKING_LINK")
        or getattr(config, "BOOKING_LINK", None)
        or getattr(getattr(config, "settings", object()), "BOOKING_LINK", "https://calendly.com/yourhvac/estimate")
    )
    return {"FROM_NAME": FROM_NAME, "BOOKING_LINK": BOOKING_LINK}
