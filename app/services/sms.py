from twilio.rest import Client
from app import config
from app import config
def _client() -> Client:
    if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN):
        raise RuntimeError("Missing Twilio creds in .env")
    return Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)

def send_sms(to: str, body: str) -> bool:
    try:
        # ---- DRY RUN MODE ----
        if config.SMS_DRY_RUN:
            print(f"[DRY RUN] Would send SMS to {to}: {body}")
            return True

        client = _client()
        msid = (config.TWILIO_MESSAGING_SERVICE_SID or "").strip()
        frm  = (config.TWILIO_FROM or "").strip()

        kwargs = {"to": to, "body": body}
        if msid:
            print("Using Messaging Service:", msid)
            kwargs["messaging_service_sid"] = msid
        elif frm:
            print("Using From number:", frm)
            kwargs["from_"] = frm
        else:
            raise RuntimeError("Set TWILIO_FROM or TWILIO_MESSAGING_SERVICE_SID")

        msg = client.messages.create(**kwargs)
        print("Twilio queued:", msg.sid, msg.status)
        return True
    except Exception as e:
        print("SMS error:", e)
        return False
def send_sms(to: str, body: str) -> bool:
    # ... your existing setup ...
    if getattr(config, "SMS_DRY_RUN", True):
        print(f"[DRY-RUN SMS] to={to} body={body}")
        return True     # <= make previews + sent logs look “successful”
    # real send below...
