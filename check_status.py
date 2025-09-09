from twilio.rest import Client
from dotenv import load_dotenv
import os

load_dotenv()
c = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

# show the last few outbound messages
for m in c.messages.list(limit=5):
    print(m.sid, "status:", m.status, "error:", m.error_code, m.error_message, "to:", m.to, "from:", m.from_)
