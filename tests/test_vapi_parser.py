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

# ── Transcript A: property_type opener before name question ────────────
r = _parse_transcript(turns(
    ("assistant", "Are you calling about a residential or commercial property today?"),
    ("user", "Residential."),
    ("assistant", "Can I get your full name?"),
    ("user", "Peyton Madden."),
))
check("TxA property_type", r.get("property_type"), "residential")
check("TxA name", r.get("name"), "Peyton Madden.")

# ── Transcript B: email confirmation spelling + duplicate removal ───────
r = _parse_transcript(turns(
    ("assistant", "Can I get your email so the team can set up your account?"),
    ("user", "Madden M A D D E N P zero seven zero six at gmail dot com"),
))
check("TxB email", r.get("email"), "madden.p0706@gmail.com")

# ── Transcript C: tens+ones address normalization ──────────────────────
r = _parse_transcript(turns(
    ("assistant", "Can I get the full service address?"),
    ("user", "Sixty nine fifty nine Perch Hammock Loop, Groveland, Florida, three four seven three six"),
))
check("TxC address", r.get("service_address"), "6959 Perch Hammock Loop, Groveland, Florida, 34736")
check("TxC zip", r.get("zip"), "34736")

# ── Tens normalization unit tests ──────────────────────────────────────
check("tens sixty nine", _normalize_word_digits("sixty nine fifty nine Perch Hammock"),
      "6959 Perch Hammock")
check("tens mixed sixty 9", _normalize_word_digits("sixty 9 fifty 9 Main Street"),
      "6959 Main Street")
check("tens bare fifty", _normalize_word_digits("fifty Main Street"),
      "50 Main Street")

# ── .mom → .com fix ───────────────────────────────────────────────────
check("email .mom fix", _normalize_email("peyton at gmail dot mom"), "peyton@gmail.com")

# ── Readback confirmation tests ────────────────────────────────────────

# Test 1 - Email self-correction mid-answer, confirmed on readback
r = _parse_transcript(turns(
    ("assistant", "Can I get your email address?"),
    ("user", "peyton at gmail dot com... wait, peyton.madden at gmail dot com"),
    ("assistant", "So that's p-e-y-t-o-n dot m-a-d-d-e-n at gmail dot com. Did I get that right?"),
    ("user", "yes"),
))
check("READBACK1 email corrected", r.get("email"), "peyton.madden@gmail.com")
check("READBACK1 confirmed no flag", r.get("needs_verification"), False)

# Test 2 - Phone correction on readback: inline "no, last one's a three" + re-ask
r = _parse_transcript(turns(
    ("assistant", "What's your callback phone number?"),
    ("user", "eight one four five six four two two one two"),
    ("assistant", "Got it, that's 8-1-4-5-6-4-2-2-1-2. Correct?"),
    ("user", "no, last one's a three"),
    ("assistant", "No problem, can you say it again?"),
    ("user", "eight one four five six four two two one three"),
    ("assistant", "Got it, that's 8-1-4-5-6-4-2-2-1-3. Correct?"),
    ("user", "yes"),
))
check("READBACK2 phone corrected", r.get("phone"), "8145642213")
check("READBACK2 confirmed no flag", r.get("needs_verification"), False)

# Test 3 - Address confirmed first try
r = _parse_transcript(turns(
    ("assistant", "Can I get the service address?"),
    ("user", "six nine five nine main street groveland florida three four seven three six"),
    ("assistant", "Just to confirm, the address is 6959 Main Street, Groveland, Florida, 34736. Is that right?"),
    ("user", "yep"),
))
check("READBACK3 address captured", "6959" in (r.get("service_address") or ""), True)
check("READBACK3 zip captured", r.get("zip"), "34736")
check("READBACK3 confirmed no flag", r.get("needs_verification"), False)

# Test 4 - Caller hangs up before confirming readback → needs_verification = True
r = _parse_transcript(turns(
    ("assistant", "Can I get your email address?"),
    ("user", "peyton at gmail dot com"),
    ("assistant", "So that's p-e-y-t-o-n at gmail dot com. Did I get that right?"),
    # caller hangs up — no user turn follows
))
check("READBACK4 email saved", r.get("email"), "peyton@gmail.com")
check("READBACK4 needs_verification set", r.get("needs_verification"), True)

# Test 5 - No readback in transcript (old-style) → confirmed = False but no flag set
r = _parse_transcript(turns(
    ("assistant", "Can I get your full name?"),
    ("user", "John Smith"),
    ("assistant", "And what's the issue?"),
    ("user", "My AC is not cooling"),
))
check("READBACK5 name no flag", r.get("needs_verification"), False)

# ── Bug-regression tests ───────────────────────────────────────────────

# BUG1-REG: leading filler before "yes" still counts as confirmed
r = _parse_transcript(turns(
    ("assistant", "Can I get your full name?"),
    ("user", "John Smith"),
    ("assistant", "Just to confirm, I have John Smith. Is that correct?"),
    ("user", "Oh yes, that's right"),
))
check("BUG1-REG filler+yes confirmed", r.get("needs_verification"), False)
check("BUG1-REG name correct", r.get("name"), "John Smith")

# BUG1-REG: "That's correct" (not at anchor position by old RE) now matches
r = _parse_transcript(turns(
    ("assistant", "What's your callback phone number?"),
    ("user", "eight one four five six four two two one two"),
    ("assistant", "Got it, that's 8-1-4-5-6-4-2-2-1-2. Correct?"),
    ("user", "That's correct"),
))
check("BUG1-REG thats-correct confirmed", r.get("needs_verification"), False)
check("BUG1-REG phone correct", r.get("phone"), "8145642212")

# BUG2-REG: closing "Is there anything else I can help you with?" must NOT capture issue
r = _parse_transcript(turns(
    ("assistant", "What's going on with your system today?"),
    ("user", "My AC is not cooling"),
    ("assistant", "Is there anything else I can help you with?"),
    ("user", "No. That's it"),
))
check("BUG2-REG issue not overwritten", r.get("issue"), "My AC is not cooling")

# BUG3-REG: email with no TLD for known provider gets .com appended
from app.routers.vapi import _normalize_email
check("BUG3-REG gmail no TLD", _normalize_email("madden at gmail"), "madden@gmail.com")
check("BUG3-REG trailing period stripped", _normalize_email("peyton at gmail dot com."), "peyton@gmail.com")

# BUG3-REG: unknown TLD-less email gets flagged in transcript parser
r = _parse_transcript(turns(
    ("assistant", "Can I get your email?"),
    ("user", "john at customdomain"),
    ("assistant", "So that's john at customdomain. Did I get that right?"),
    ("user", "yes"),
))
check("BUG3-REG unknown no-TLD flagged", r.get("needs_verification"), True)

if FAIL:
    print("\n--- FAILURES ---")
    for f in FAIL:
        print(f)
    sys.exit(1)
else:
    print("\nAll tests passed OK")
