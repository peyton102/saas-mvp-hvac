# app/call_cache.py
# In-memory store mapping Twilio CallSid -> ForwardedFrom.
# Written by /twilio/voice when a call arrives; read by /vapi/intake using
# call.id (which Vapi sets to the originating Twilio CallSid).

_forwarded_from: dict = {}


def store(call_sid: str, forwarded_from: str) -> None:
    if call_sid:
        _forwarded_from[call_sid] = forwarded_from
        print(f"[CALL CACHE] stored call_sid={call_sid!r} forwarded_from={forwarded_from!r}", flush=True)


def lookup(call_id: str) -> str:
    value = _forwarded_from.get(call_id, "")
    print(f"[CALL CACHE] lookup call_id={call_id!r} → {value!r} "
          f"(cache size={len(_forwarded_from)})", flush=True)
    return value


def evict(call_id: str) -> None:
    _forwarded_from.pop(call_id, None)
