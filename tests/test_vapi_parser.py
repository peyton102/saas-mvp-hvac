"""
Quick smoke-test for the vapi.py transcript parser.
Run: python tests/test_vapi_parser.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.routers.vapi import _parse_transcript, _normalize_email, _normalize_urgency, _normalize_word_digits
from datetime import date

def turns(*pairs):
    return [{"role": r, "content": c} for r, c in pairs]

FAIL = []

def check(label, got, expected):
    if got != expected:
        FAIL.append(f"FAIL [{label}]: got {got!r}, expected {expected!r}")
    else:
        print(f"  OK  [{label}]")

# ── BUG 1: name + phone in one breath ──────────────────────────────────
r = _parse_transcript(turns(
    ("assistant", "Can I get your name?"),
    ("user", "Payton Madden eight one four five six four two two one two"),
    ("assistant", "And your callback number?"),
))
check("BUG1 name stripped", r["name"], "Payton Madden")
# Phone should be recovered from the trailing digits
check("BUG1 phone recovered", r["phone"], "8145642212")

# ── BUG 2: spoken phone wins over caller ID ─────────────────────────────
r = _parse_transcript(turns(
    ("assistant", "What's your callback phone number?"),
    ("user", "eight one four five six four two two one two"),
), customer_number="+13525579832")
check("BUG2 spoken phone", r["phone"], "8145642212")

# ── BUG 3: no issue fallback to first user turn ─────────────────────────
r = _parse_transcript(turns(
    ("assistant", "Is this residential or commercial?"),
    ("user", "Residential"),
))
check("BUG3 issue blank", r["issue"], "")

# ── BUG 4: address digit-words preserved ───────────────────────────────
r = _parse_transcript(turns(
    ("assistant", "What is the service address?"),
    ("user", "six nine five nine perch hammock loop groveland florida three four seven three six"),
))
check("BUG4 street number", "6959" in r.get("service_address", ""), True)
check("BUG4 zip extracted", r.get("zip"), "34736")

# ── BUG 5: email parsing ───────────────────────────────────────────────
r = _parse_transcript(turns(
    ("assistant", "Can I get your email address?"),
    ("user", "peyton at gmail dot com"),
))
check("BUG5 email parsed", r.get("email"), "peyton@gmail.com")

# ── _normalize_email ───────────────────────────────────────────────────
check("email norm 1", _normalize_email("peyton at gmail dot com"), "peyton@gmail.com")
check("email norm 2", _normalize_email("john dot doe at company dot net"), "john.doe@company.net")

# ── _normalize_urgency smoke ───────────────────────────────────────────
today = date(2025, 6, 20)  # Friday (June 20 2025 is indeed a Friday)
check("urgency ASAP",    _normalize_urgency("ASAP", today), "ASAP")
check("urgency Friday",  _normalize_urgency("Friday", today), "Friday June 27")
check("urgency the 22nd",_normalize_urgency("The 22nd", today), "June 22")
check("urgency Monday 2pm", _normalize_urgency("Monday at 2pm", today), "Monday June 23 at 2pm")
check("urgency tomorrow morning", _normalize_urgency("Tomorrow morning", today), "Saturday June 21 morning")
check("urgency filler", _normalize_urgency("Alright just I'd like to schedule", today), "needs scheduling")
check("urgency range", _normalize_urgency("8 to 10 on Tuesday", today), "Tuesday June 24 from 8am-10am")

# ── _normalize_word_digits address ────────────────────────────────────
check("addr digits", _normalize_word_digits("six nine five nine Main Street three four seven three six"),
      "6959 Main Street 34736")

if FAIL:
    print("\n--- FAILURES ---")
    for f in FAIL:
        print(f)
    sys.exit(1)
else:
    print("\nAll tests passed OK")
