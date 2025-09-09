import os
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

ENV = os.getenv("ENV", "dev")
PORT = int(os.getenv("PORT", "8000"))

# Branding / links
FROM_NAME = os.getenv("FROM_NAME", "HVAC Bot")
BOOKING_LINK = os.getenv("BOOKING_LINK", "")

# Twilio creds
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
TWILIO_FROM = os.getenv("TWILIO_FROM")
SMS_DRY_RUN = os.getenv("SMS_DRY_RUN", "false").lower() == "true"
# Storage
LEADS_CSV = os.getenv("LEADS_CSV", "data/leads.csv")
TZ = os.getenv("TZ", "America/New_York")  # used for timestamps
ANTI_SPAM_MINUTES = int(os.getenv("ANTI_SPAM_MINUTES", "120"))  # 2 hours default
