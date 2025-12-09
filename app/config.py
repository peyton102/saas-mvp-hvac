# app/config.py
import os
from dotenv import load_dotenv
from pathlib import Path
# load .env into process env vars
load_dotenv(override=True)
ROOT = Path(__file__).resolve().parents[1]
load_dotenv( Path(__file__).resolve().parents[1] / ".env" )

def _as_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")

def _as_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except Exception:
        return default

def _parse_tenant_keys(raw: str) -> dict:
    """
    Accepts:  'default:devkey,acme:acmekey'
    Returns:  { 'devkey': 'default', 'acmekey': 'acme' }
    """
    mapping = {}
    raw = (raw or "").strip()
    if not raw:
        return mapping
    for part in raw.split(","):
        if ":" in part:
            tenant, key = part.split(":", 1)
            tenant, key = tenant.strip(), key.strip()
            if tenant and key:
                mapping[key] = tenant
    return mapping

class Settings:
    # App
    ENV: str = os.getenv("ENV", "dev")
    PORT: int = _as_int("PORT", 8000)
    TZ: str = os.getenv("TZ", "America/New_York")

    QBO_ENV = os.getenv("QBO_ENV", "sandbox")
    QBO_CLIENT_ID = os.getenv("QBO_CLIENT_ID", "")
    QBO_CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET", "")
    QBO_REDIRECT_URI = os.getenv("QBO_REDIRECT_URI", "")
    QBO_SCOPES = os.getenv("QBO_SCOPES", "com.intuit.quickbooks.accounting openid profile email")

    # Branding / links
    FROM_NAME: str = os.getenv("FROM_NAME", "HVAC Bot")
    BOOKING_LINK = os.getenv("BOOKING_LINK", "http://localhost:5173/book/index.html?")

    # Reminders
    REMINDERS: str = os.getenv("REMINDERS", "24h,2h")
    REMINDER_WINDOW_SECONDS: int = _as_int("REMINDER_WINDOW_SECONDS", 900)

    # Spam / throttle
    ANTI_SPAM_MINUTES: int = _as_int("ANTI_SPAM_MINUTES", 120)
    DB_FIRST: bool = _as_bool("DB_FIRST", True)

    # Debug / auth
    # Prefer DEBUG_BEARER; fallback to legacy DEBUG_BEARER_TOKEN
    DEBUG_BEARER: str = (os.getenv("DEBUG_BEARER") or os.getenv("DEBUG_BEARER_TOKEN") or "").strip()

    # Multi-tenant (token -> tenant_id)
    import json
    _raw = os.getenv("TENANT_KEYS", "")
    try:
        TENANT_KEYS = json.loads(_raw)
        if not isinstance(TENANT_KEYS, dict) or not TENANT_KEYS:
            TENANT_KEYS = {"devkey": "default"}
    except Exception:
        TENANT_KEYS = {"devkey": "default"}

    # Twilio
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    TWILIO_MESSAGING_SERVICE_SID: str = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "").strip()
    TWILIO_FROM: str = os.getenv("TWILIO_FROM", "").strip()
    SMS_DRY_RUN: bool = _as_bool("SMS_DRY_RUN", False)
    TWILIO_VALIDATE_SIGNATURES: bool = _as_bool("TWILIO_VALIDATE_SIGNATURES", False)

    # Storage
    LEADS_CSV: str = os.getenv("LEADS_CSV", "data/leads.csv")

    # Email (optional)
    EMAIL_DRY_RUN: bool = _as_bool("EMAIL_DRY_RUN", True)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = _as_int("SMTP_PORT", 587)
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    FROM_EMAIL: str = os.getenv("FROM_EMAIL", "no-reply@example.com")
    EMAIL_OFFICE: str = os.getenv("EMAIL_OFFICE", os.getenv("FROM_EMAIL", "no-reply@example.com"))

    # Calendly
    CALENDLY_WEBHOOK_SECRET: str = os.getenv("CALENDLY_WEBHOOK_SECRET", "").strip()

# instantiate settings FIRST
settings = Settings()

# expose selected fields as module-level aliases (for older imports)
LEADS_CSV = settings.LEADS_CSV
TENANT_KEYS = settings.TENANT_KEYS
FROM_NAME = settings.FROM_NAME
BOOKING_LINK = settings.BOOKING_LINK
ANTI_SPAM_MINUTES = settings.ANTI_SPAM_MINUTES
DB_FIRST = settings.DB_FIRST
TWILIO_VALIDATE_SIGNATURES = settings.TWILIO_VALIDATE_SIGNATURES
TWILIO_AUTH_TOKEN = settings.TWILIO_AUTH_TOKEN

# Email aliases
EMAIL_DRY_RUN  = settings.EMAIL_DRY_RUN
SMTP_HOST      = settings.SMTP_HOST
SMTP_PORT      = settings.SMTP_PORT
SMTP_USERNAME  = settings.SMTP_USERNAME
SMTP_PASSWORD  = settings.SMTP_PASSWORD
FROM_EMAIL     = settings.FROM_EMAIL
EMAIL_OFFICE   = settings.EMAIL_OFFICE

# app/config.py (add near existing settings)
import os
from dataclasses import dataclass

@dataclass
class _Settings:
    TZ: str
    FROM_NAME: str
    FROM_EMAIL: str | None  # global fallback (optional)
    EMAIL_OFFICE: str | None  # global fallback (optional)
    TENANT_OFFICE_MAP_RAW: str | None  # "default:ops@example.com;acme:ops@acme.com"

    # ... include your existing fields too

    def tenant_office_map(self) -> dict[str, str]:
        """
        Parse TENANT_OFFICE_MAP like:
        default:ops@example.com;acme:ops@acme.com
        """
        raw = (self.TENANT_OFFICE_MAP_RAW or "").strip()
        if not raw:
            return {}
        out: dict[str, str] = {}
        for pair in raw.split(";"):
            pair = pair.strip()
            if not pair:
                continue
            if ":" not in pair:
                raise ValueError(f"Bad TENANT_OFFICE_MAP entry (missing colon): {pair}")
            t, email = pair.split(":", 1)
            t, email = t.strip(), email.strip()
            if not t or not email:
                raise ValueError(f"Bad TENANT_OFFICE_MAP entry (empty): {pair}")
            out[t] = email
        return out

    def office_email_for(self, tenant: str) -> str:
        m = self.tenant_office_map()
        if tenant in m:
            return m[tenant]
        if self.EMAIL_OFFICE:
            return self.EMAIL_OFFICE  # explicit global fallback if you configured it
        # No fallback => hard fail to avoid silent loss
        raise ValueError(f"No office email configured for tenant '{tenant}'. "
                         f"Set TENANT_OFFICE_MAP or EMAIL_OFFICE.")

# build settings from env (example; adapt to your loader)
# NOTE: CHANGED NAME so it doesn't overwrite the main `settings` above.
OFFICE_SETTINGS = _Settings(   # <-- was `settings = _Settings(`; renamed
    TZ=os.getenv("TZ", "America/New_York"),
    FROM_NAME=os.getenv("FROM_NAME", "Torevez"),
    FROM_EMAIL=os.getenv("FROM_EMAIL", "noreply@example.com"),
    EMAIL_OFFICE=os.getenv("EMAIL_OFFICE") or None,
    TENANT_OFFICE_MAP_RAW=os.getenv("TENANT_OFFICE_MAP") or None,
)
# app/config.py
