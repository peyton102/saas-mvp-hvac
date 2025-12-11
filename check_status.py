from twilio.rest import Client
from dotenv import load_dotenv
import os

load_dotenv()

# Use Twilio API Key auth:
#   Client(api_key_sid, api_key_secret, account_sid)
c = Client(
    os.getenv("TWILIO_API_KEY"),
    os.getenv("TWILIO_AUTH_TOKEN"),
    os.getenv("TWILIO_ACCOUNT_SID"),
)

# show the last few outbound messages
for m in c.messages.list(limit=5):
    print(
        m.sid,
        "status:", m.status,
        "error:", m.error_code, m.error_message,
        "to:", m.to,
        "from:", m.from_,
    )
