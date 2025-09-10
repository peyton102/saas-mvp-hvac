# app/utils/phone.py
import phonenumbers
from fastapi import HTTPException

def normalize_us_phone(raw: str) -> str:
    """
    Normalize US/CA numbers to E.164 (+1XXXXXXXXXX).
    Raise 422 if invalid so the API returns a clean error.
    """
    try:
        pn = phonenumbers.parse(raw, "US")
        if not phonenumbers.is_possible_number(pn) or not phonenumbers.is_valid_number(pn):
            raise ValueError("invalid")
        return phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid phone number. Use format like +18145551234.")