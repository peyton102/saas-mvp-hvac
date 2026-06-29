# app/routers/vapi.py
import json as _json
import os
import re
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from datetime import date, datetime, timedelta
from typing import Any, Optional

from app.call_cache import lookup as cache_lookup, evict as cache_evict
from app.db import get_session
from app.models import Lead as LeadModel, Tenant, WebhookDedup
from app.services.sms import vapi_lead_office_sms

router = APIRouter(prefix="", tags=["vapi"])

# ── Universal Vapi assistant system prompt template ───────────────────────────
# Copy this block into every Vapi assistant's system prompt.
# Do NOT reference any specific company name here.
VAPI_SYSTEM_PROMPT_TEMPLATE = """
[Universal Readback Behavior]

After collecting each of the following fields, immediately read it back and confirm
before moving to the next question:

1. NAME — "Just to confirm, I have [name]. Is that correct?"
2. PHONE — "Got it, that's [digit-by-digit, e.g. '8-1-4-5-6-4-2-2-1-2']. Correct?"
3. EMAIL (new customers only) — "So that's [letter-by-letter, 'at' for @, 'dot' for periods]. Did I get that right?"
4. SERVICE ADDRESS — "Just to confirm, the address is [full address]. Is that right?"

Always read back, every time, no exceptions. Do not judge whether the value sounds
correct. If the caller confirms, move on. If they correct, re-read the corrected
version and confirm again.

Skip readback for: issue description, service urgency/timing, customer type (new/existing),
and property type (residential/commercial).

If the caller says "no," "wait," "that's wrong," "actually," or similar mid-answer:
- Say: "No problem, can you say it again?"
- Capture only the corrected value
- Read it back one more time to confirm
- Repeat up to 3 times, then move on with the latest version
""".strip()


class VapiIntakePayload(BaseModel):
    call_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    issue: Optional[str] = None
    language: Optional[str] = None
    summary: Optional[str] = None
    zip: Optional[str] = None
    service_address: Optional[str] = None
    service_urgency: Optional[str] = None
    customer_type: Optional[str] = None
    property_type: Optional[str] = None
    email: Optional[str] = None
    phone_number_id: Optional[str] = None
    forwarded_from: Optional[str] = None
    needs_verification: Optional[bool] = None


def _message_type(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    msg = body.get("message") or {}
    return str(msg.get("type") or "").strip()


def _clean_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _normalize_phone(value: Optional[str]) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) == 10:
        return digits
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    return text


def _format_display_phone(value: Optional[str]) -> str:
    normalized = _normalize_phone(value)
    if not normalized:
        return ""
    digits = re.sub(r"\D", "", normalized)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if normalized.startswith("+"):
        return normalized
    return normalized


def _extract_name_from_text(*values: Optional[str]) -> str:
    patterns = [
        r"\b(?:their|the caller'?s|caller)\s+name\s+(?:is|was)\s+([A-Z][a-z]+)\b",
        r"\b([A-Z][a-z]+)\s+called\b",
    ]
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip(" ,.")
                return candidate[:1].upper() + candidate[1:]
    return ""


def _extract_phone_from_text(*values: Optional[str]) -> str:
    patterns = [
        r"\b(?:callback|call\s*back|best)\s+(?:number|phone)\D*([+]?\d[\d\-\(\)\s]{8,}\d)",
        r"\bphone\s+number\D*([+]?\d[\d\-\(\)\s]{8,}\d)",
    ]
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                phone = _normalize_phone(match.group(1))
                if phone:
                    return phone
    return ""


def _compact_reason(value: Optional[str]) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    if len(text) <= 60 and not re.search(r"\b(called|assistant|contact|schedule|confirm)\b", text, re.IGNORECASE):
        return text.rstrip(".")

    patterns = [
        r"\b(?:because|for)\s+(their\s+)?(.+?)(?:\s+and\s+(?:needed|needs|requested)|[.!?]|$)",
        r"\b(?:issue|reason)\D+(.+?)(?:[.!?]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            phrase = match.group(match.lastindex).strip(" ,.")
            phrase = re.sub(r"^(their|the)\s+", "", phrase, flags=re.IGNORECASE)
            return phrase[:1].upper() + phrase[1:]

    match = re.match(r"(.+?)(?:[.!?]|$)", text)
    if match:
        return match.group(1).strip(" ,.")
    return text


def _compact_notes(value: Optional[str], fallback_text: Optional[str] = None) -> str:
    combined = _clean_text(value)
    fallback = _clean_text(fallback_text)
    source = combined or fallback
    if not source:
        return ""

    parts: list[str] = []

    zip_match = re.search(r"\bZIP(?:\s+code)?\D*(\d{5})\b", source, re.IGNORECASE)
    if zip_match:
        parts.append(f"ZIP {zip_match.group(1)}")

    if re.search(r"\burgent|asap|immediate|right away|fastest possible\b", source, re.IGNORECASE):
        parts.append("urgent repair")
    elif re.search(r"\btoday or tomorrow\b", source, re.IGNORECASE):
        parts.append("today or tomorrow")

    preferred_patterns = [
        r"\b(?:prefer(?:red)?|best|available)\s+(?:time|day|day/time|date)\D*(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(morning|afternoon|evening))?",
        r"\b(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(morning|afternoon|evening))?\b",
    ]
    for pattern in preferred_patterns:
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            day = match.group(1)
            day_part = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
            preferred = day.lower()
            if day_part:
                preferred = f"{preferred} {day_part.lower()}"
            parts.append(f"prefers {preferred}")
            break

    time_match = re.search(
        r"\b(?:prefer(?:red)?|best|available)\s+(?:time|day|day/time|date)\D*"
        r"((?:\d{1,2})(?::\d{2})?\s*(?:am|pm)|(?:morning|afternoon|evening))\b",
        source,
        re.IGNORECASE,
    ) or re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", source, re.IGNORECASE)
    if time_match:
        parts.append(f"prefers {time_match.group(1).lower()}")

    if not parts and combined and len(combined) <= 80:
        parts.append(combined.rstrip("."))

    return ", ".join(dict.fromkeys(parts))


def _split_reason_and_notes(reason: Optional[str], notes: Optional[str]) -> tuple[str, str]:
    return _compact_reason(reason), _compact_notes(notes, fallback_text=reason)


def _extract_zip(value: Optional[str]) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    match = re.search(r"\b(\d{5})\b", text)
    return match.group(1) if match else ""


def _extract_timing(*values: Optional[str]) -> str:
    patterns = [
        r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(morning|afternoon|evening))?(?:\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)))?\b",
        r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
    ]
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        if re.search(r"\b(asap|urgent|immediately|right away|as soon as possible)\b", text, re.IGNORECASE):
            return "ASAP"
        match = re.search(patterns[0], text, re.IGNORECASE)
        if match:
            day = (match.group(1) or "").lower()
            part = (match.group(2) or "").lower()
            at_time = (match.group(3) or "").lower()
            result = day
            if part:
                result = f"{result} {part}"
            if at_time:
                result = f"{result} at {at_time}"
            return result.strip()
        match = re.search(patterns[1], text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return ""


_WORD_TO_DIGIT = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "oh": "0",
}

_TENS_TO_NUM = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


def _normalize_word_digits(text: str) -> str:
    """
    Convert spoken digit-words and number-words to numerics, collapsing adjacent groups.
    Handles tens+ones compounds ("sixty nine" → "69") and mixed ("sixty 9" → "69").

    'six nine five nine Main Street three four seven three six' → '6959 Main Street 34736'
    'sixty nine fifty nine Perch Hammock Loop' → '6959 Perch Hammock Loop'
    """
    if not text:
        return text
    tokens = text.split()
    result: list[str] = []
    i = 0
    while i < len(tokens):
        bare = tokens[i].lower().rstrip(".,;:")
        if bare in _TENS_TO_NUM:
            tens_val = _TENS_TO_NUM[bare]
            i += 1
            if i < len(tokens):
                nb = tokens[i].lower().rstrip(".,;:")
                if nb in _WORD_TO_DIGIT:
                    # "sixty nine" → 69
                    result.append(str(tens_val + int(_WORD_TO_DIGIT[nb])))
                    i += 1
                elif re.match(r"^[1-9]$", nb):
                    # "sixty 9" (mixed) → 69
                    result.append(str(tens_val + int(nb)))
                    i += 1
                else:
                    result.append(str(tens_val))
            else:
                result.append(str(tens_val))
        elif bare in _WORD_TO_DIGIT:
            digits: list[str] = []
            while i < len(tokens):
                b = tokens[i].lower().rstrip(".,;:")
                if b in _WORD_TO_DIGIT:
                    digits.append(_WORD_TO_DIGIT[b])
                    i += 1
                else:
                    break
            result.append("".join(digits))
        else:
            result.append(tokens[i])
            i += 1
    # Collapse adjacent all-digit tokens ("69" "59" → "6959")
    collapsed: list[str] = []
    for tok in result:
        if collapsed and re.match(r"^\d+$", tok) and re.match(r"^\d+$", collapsed[-1]):
            collapsed[-1] += tok
        else:
            collapsed.append(tok)
    return " ".join(collapsed)


def _normalize_email(text: str) -> str:
    """
    Normalize a spoken email address.
    Handles letter-by-letter spelling, digit-words, and domain compounds.
    "peyton at gmail dot com" → "peyton@gmail.com"
    "m a d d e n dot p zero seven zero six at g mail dot com" → "madden.p0706@gmail.com"
    """
    if not text:
        return text
    s = text.strip()

    # Phase 1: fix spoken domain compounds
    s = re.sub(r"\bg\s+mail\b", "gmail", s, flags=re.IGNORECASE)
    s = re.sub(r"\bgee\s*mail\b", "gmail", s, flags=re.IGNORECASE)
    s = re.sub(r"\bhot\s+mail\b", "hotmail", s, flags=re.IGNORECASE)
    s = re.sub(r"\byahoo\s+mail\b", "yahoo", s, flags=re.IGNORECASE)

    # Phase 2: split username / domain on spoken " at "
    at_parts = re.split(r"\s+at\s+", s, maxsplit=1, flags=re.IGNORECASE)
    if len(at_parts) == 2:
        username_raw, domain_raw = at_parts
    elif "@" in s:
        username_raw, domain_raw = s.split("@", 1)
    else:
        return re.sub(r"\s+dot\s+", ".", s, flags=re.IGNORECASE).strip().lower()

    # Phase 3: normalize username tokens
    def _norm_username(raw: str) -> str:
        raw = re.sub(r"[,;]", " ", raw)
        tokens = raw.split()
        parts: list[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i].lower().rstrip(".,;:")
            if tok == "dot":
                parts.append(".")
                i += 1
            elif len(tok) == 1 and tok.isalpha():
                # Collapse consecutive single-letter tokens into one word
                letters: list[str] = []
                while i < len(tokens):
                    t = tokens[i].lower().rstrip(".,;:")
                    if len(t) == 1 and t.isalpha():
                        letters.append(t)
                        i += 1
                    else:
                        break
                # Attach any immediately following digit-words to the collapsed word
                digs: list[str] = []
                while i < len(tokens):
                    t = tokens[i].lower().rstrip(".,;:")
                    if t in _WORD_TO_DIGIT:
                        digs.append(_WORD_TO_DIGIT[t])
                        i += 1
                    else:
                        break
                # Detect confirmation spelling: "madden m a d d e n p..." →
                # letters start with the previous word → keep only the suffix
                prev = parts[-1].lower() if parts and parts[-1] != "." else ""
                joined = "".join(letters)
                if prev and joined.startswith(prev):
                    suffix = letters[len(prev):]
                else:
                    suffix = letters
                word = "".join(suffix)
                if digs:
                    word += "".join(digs)
                if word:
                    parts.append(word)
            elif tok in _WORD_TO_DIGIT:
                # Bare digit-word run (no preceding single letters)
                digs = []
                while i < len(tokens):
                    t = tokens[i].lower().rstrip(".,;:")
                    if t in _WORD_TO_DIGIT:
                        digs.append(_WORD_TO_DIGIT[t])
                        i += 1
                    else:
                        break
                parts.append("".join(digs))
            else:
                parts.append(tok)
                i += 1

        # Join: explicit dots stay, other tokens get "." separator
        username = ""
        for j, p in enumerate(parts):
            if p == ".":
                username += "."
            elif j == 0:
                username += p
            elif parts[j - 1] == ".":
                username += p
            else:
                username += "." + p

        # Remove adjacent duplicates: "madden.madden" → "madden"
        username = re.sub(r"\b(\w+)\.\1\b", r"\1", username)
        username = re.sub(r"\.{2,}", ".", username)
        return username.strip(".").lower()

    # Phase 4: normalize domain
    def _norm_domain(raw: str) -> str:
        d = re.sub(r"\s+dot\s+", ".", raw, flags=re.IGNORECASE)
        d = re.sub(r"\bdot\b", ".", d, flags=re.IGNORECASE)
        d = re.sub(r"\s+", "", d)
        return d.strip(".").lower()

    username = _norm_username(username_raw)
    domain = _norm_domain(domain_raw)

    if not username or not domain:
        return s.strip().lower()

    result = f"{username}@{domain}"

    # Strip trailing period that sometimes comes from sentence-ending punctuation
    result = result.rstrip(".")

    # Fix common ASR "com" transcription errors
    result = re.sub(r"\.(mom|cum|con|calm)$", ".com", result, flags=re.IGNORECASE)

    # Fix well-known providers missing their TLD (e.g. "@gmail" → "@gmail.com")
    _PROVIDER_TLDS = {
        "gmail": ".com", "yahoo": ".com", "hotmail": ".com",
        "outlook": ".com", "icloud": ".com", "aol": ".com",
        "protonmail": ".com", "live": ".com", "msn": ".com",
    }
    if "@" in result:
        domain_part = result.split("@", 1)[1]
        if "." not in domain_part:
            tld = _PROVIDER_TLDS.get(domain_part.lower().strip("."))
            if tld:
                result = result + tld

    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", result)
    return m.group(0).lower() if m else result.lower()


_URGENCY_HOUR_MAP = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_URGENCY_MINUTE_MAP = {
    "oh": 0, "zero": 0, "five": 5, "ten": 10, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}
_URGENCY_DATE_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_URGENCY_DATE_TENS = {"twenty": 20, "thirty": 30}
_URGENCY_MONTHS_RE = (
    r"january|february|march|april|may|june|july|august"
    r"|september|october|november|december"
)


_URGENCY_TOD_KEYWORDS = {"morning", "afternoon", "evening", "anytime"}


def _normalize_urgency(text: str, _today: Optional[date] = None) -> str:
    """
    Full normalization of a service_urgency capture:
      C. Strip conversational filler ("Alright", "I'd like to schedule for", …)
      +  Digit-word conversion ("two pm" → "2pm", "June twenty one" → "June 21")
      A. Resolve dates (day-of-week → upcoming calendar date, today/tomorrow, ordinals)
      B. Extract times (ranges → "from Xam-Yam", specific, time-of-day keywords)
    Returns "needs scheduling" when no parseable date or time is found.
    """
    if not text:
        return text

    today = _today or datetime.now().date()
    s = text.strip()

    # Quick passthrough for clean ASAP values
    if re.match(r"^(asap|urgent|right away|immediately|as soon as possible)$", s, re.IGNORECASE):
        return "ASAP"

    # ── Part C: Strip conversational filler ─────────────────────────────
    s = re.sub(
        r"^(?:(?:alright|okay|ok|sure|yes|yeah|yep|just|so)[.,!]?\s+)+",
        "", s, flags=re.IGNORECASE,
    ).strip()
    s = re.sub(
        r"(i.{0,2}d like to schedule\s*(?:for\s*)?|let.{0,2}s (?:do|say)\s*"
        r"|how about\s*|i was thinking\s*|can we (?:do|schedule)\s*)",
        "", s, flags=re.IGNORECASE,
    ).strip()
    s = re.sub(r"^for\s+", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\b(?:a\s+)?routine\b", "", s, flags=re.IGNORECASE).strip()

    if re.search(r"\b(asap|right away|immediately|as soon as possible)\b", s, re.IGNORECASE):
        return "ASAP"

    # ── Digit-word pre-pass ──────────────────────────────────────────────
    _ones_re = "|".join(_URGENCY_DATE_ONES)
    _tens_re = "|".join(_URGENCY_DATE_TENS)
    _hour_re = "|".join(_URGENCY_HOUR_MAP)
    _min_re = "|".join(_URGENCY_MINUTE_MAP)

    def _sub_spoken_date(m: re.Match) -> str:
        month, tw, ow = m.group(1), (m.group(2) or "").lower(), (m.group(3) or "").lower()
        day = (_URGENCY_DATE_TENS.get(tw, 0) + _URGENCY_DATE_ONES.get(ow, 0)
               if tw in _URGENCY_DATE_TENS else _URGENCY_DATE_ONES.get(tw, 0))
        return f"{month} {day}" if day else m.group(0)

    s = re.sub(
        rf"\b({_URGENCY_MONTHS_RE})\s+({_tens_re}|{_ones_re})(?:\s+({_ones_re}))?\b",
        _sub_spoken_date, s, flags=re.IGNORECASE,
    )

    def _sub_at_tw(m: re.Match) -> str:
        hw, mw = m.group(1).lower(), (m.group(2) or "").lower()
        ap = (m.group(3) or "").lower().replace(" ", "")
        h = _URGENCY_HOUR_MAP.get(hw)
        if h is None:
            return m.group(0)
        if mw:
            mi = _URGENCY_MINUTE_MAP.get(mw)
            return f"at {h}:{mi:02d}{ap}" if mi is not None else m.group(0)
        return f"at {h}{ap}"

    s = re.sub(
        rf"\bat\s+({_hour_re})(?:\s+({_min_re}))?(\s+(?:am|pm))?\b",
        _sub_at_tw, s, flags=re.IGNORECASE,
    )

    def _sub_bare_tw(m: re.Match) -> str:
        hw, mw = m.group(1).lower(), (m.group(2) or "").lower()
        ap = m.group(3).lower().replace(" ", "")
        h = _URGENCY_HOUR_MAP.get(hw)
        if h is None:
            return m.group(0)
        if mw:
            mi = _URGENCY_MINUTE_MAP.get(mw)
            return f"{h}:{mi:02d}{ap}" if mi is not None else m.group(0)
        return f"{h}{ap}"

    s = re.sub(
        rf"\b({_hour_re})(?:\s+({_min_re}))?(\s+(?:am|pm))\b",
        _sub_bare_tw, s, flags=re.IGNORECASE,
    )

    # ── Part A: Date resolution ──────────────────────────────────────────
    date_str = ""

    # today / tomorrow
    if re.search(r"\btoday\b", s, re.IGNORECASE):
        date_str = f"{today.strftime('%A')} {today.strftime('%B')} {today.day}"
        s = re.sub(r"\btoday\b", "", s, flags=re.IGNORECASE).strip()
    elif re.search(r"\btomorrow\b", s, re.IGNORECASE):
        tmrw = today + timedelta(days=1)
        date_str = f"{tmrw.strftime('%A')} {tmrw.strftime('%B')} {tmrw.day}"
        s = re.sub(r"\btomorrow\b", "", s, flags=re.IGNORECASE).strip()

    # Day-of-week → resolve to upcoming date (same weekday → next week)
    _DOW = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    dm = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", s, re.IGNORECASE)
    if dm and not date_str:
        dn = dm.group(1).lower()
        ahead = (_DOW.index(dn) - today.weekday()) % 7 or 7
        resolved = today + timedelta(days=ahead)
        date_str = f"{dn.capitalize()} {resolved.strftime('%B')} {resolved.day}"
        s = (s[:dm.start()] + s[dm.end():]).strip()

    # Ordinal date: "the 22nd", "22nd", "the 22"
    om = re.search(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)?\b|\b(\d{1,2})(?:st|nd|rd|th)\b", s, re.IGNORECASE)
    if om and not date_str:
        dn_num = int(om.group(1) or om.group(2))
        if 1 <= dn_num <= 31:
            try:
                cand = today.replace(day=dn_num)
                if cand < today:
                    raise ValueError
                date_str = f"{today.strftime('%B')} {dn_num}"
            except ValueError:
                try:
                    nm = (today.replace(month=1, year=today.year + 1)
                          if today.month == 12 else today.replace(month=today.month + 1))
                    date_str = f"{nm.strftime('%B')} {dn_num}"
                except ValueError:
                    pass
            s = (s[:om.start()] + s[om.end():]).strip()

    # Already-normalized "Month DD" (from spoken-date digit-word pass above)
    mmm = re.search(rf"\b({_URGENCY_MONTHS_RE})\s+(\d{{1,2}})\b", s, re.IGNORECASE)
    if mmm and not date_str:
        date_str = f"{mmm.group(1).capitalize()} {mmm.group(2)}"
        s = (s[:mmm.start()] + s[mmm.end():]).strip()

    # ── Part B: Time extraction ──────────────────────────────────────────
    time_str = ""

    def _infer_ampm(h: int) -> str:
        return "am" if 6 <= h <= 11 else "pm"

    # Range: "8 to 10", "8am to 10am", "8-10am"
    rng = re.search(
        r"\b(\d{1,2}(?::\d{2})?(?:am|pm)?)\s*(?:to|-)\s*(\d{1,2}(?::\d{2})?(?:am|pm)?)\b",
        s, re.IGNORECASE,
    )
    if rng:
        t1, t2 = rng.group(1).lower(), rng.group(2).lower()
        a1, a2 = re.search(r"(am|pm)$", t1), re.search(r"(am|pm)$", t2)
        if a2 and not a1:
            t1 += a2.group(1)
        elif a1 and not a2:
            t2 += a1.group(1)
        elif not a1 and not a2:
            h1 = int(re.match(r"(\d+)", t1).group(1))
            h2 = int(re.match(r"(\d+)", t2).group(1))
            t1 += _infer_ampm(h1)
            t2 += _infer_ampm(h2)
        time_str = f"from {t1}-{t2}"
        s = (s[:rng.start()] + s[rng.end():]).strip()

    if not time_str:
        # Specific time: "2pm", "2:30pm", "8am"
        tm = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", s, re.IGNORECASE)
        if tm:
            time_str = tm.group(1).lower().replace(" ", "")
            s = (s[:tm.start()] + s[tm.end():]).strip()

    if not time_str:
        # Time-of-day keyword: morning / afternoon / evening / anytime
        todm = re.search(r"\b(morning|afternoon|evening|anytime|any\s*time)\b", s, re.IGNORECASE)
        if todm:
            time_str = todm.group(1).lower().replace(" ", "")
            s = (s[:todm.start()] + s[todm.end():]).strip()

    # ── Combine ──────────────────────────────────────────────────────────
    if not date_str and not time_str:
        return "needs scheduling"

    parts: list[str] = []
    if date_str:
        parts.append(date_str)
    if time_str:
        if time_str in _URGENCY_TOD_KEYWORDS or time_str.startswith("from "):
            parts.append(time_str)
        elif date_str:
            parts.append(f"at {time_str}")
        else:
            parts.append(time_str)
    return " ".join(parts)


# ── Readback confirmation helpers ────────────────────────────────────────────

_READBACK_ASST_RE = re.compile(
    r"\b(just to confirm|got it[,.]?\s+that.s|so that.s|did i get that right"
    r"|is that correct|is that right|correct\?|is that right\?)\b",
    re.IGNORECASE,
)

_CONFIRM_USER_RE = re.compile(
    r"^(yes|yeah|yep|yup|yessir|correct|that.?s (right|correct)|right"
    r"|uh.?huh|mm.?hmm|mhm|perfect|exactly|sounds (good|right)"
    r"|affirmative|great|sure|spot on|that('s| is) it)\b",
    re.IGNORECASE,
)

# Leading filler words callers add before a confirmation ("Oh yes", "Uh yeah")
_CONFIRM_FILLER_RE = re.compile(
    r"^(oh|uh|um|well|so|hmm|okay|ok|alright|right|and)[,.]?\s+",
    re.IGNORECASE,
)

_REJECT_USER_RE = re.compile(
    r"^(no\b|nope\b|wait\b|that.?s wrong|wrong\b|not quite|incorrect|actually\b|let me start over)",
    re.IGNORECASE,
)


def _strip_mid_answer_correction(text: str) -> str:
    """
    If caller corrects themselves within a single turn, take only the last version.
    'peyton at gmail dot com... wait, peyton.madden at gmail dot com'
    → 'peyton.madden at gmail dot com'
    """
    parts = re.split(
        r"\b(?:wait[,.]?|actually[,.]?|no wait[,.]?|let me start over[,.]?|i mean[,.]?)\s+",
        text, flags=re.IGNORECASE,
    )
    if len(parts) > 1:
        return parts[-1].strip()
    return text


def _trace_readback(
    turns: list,
    consumed: set,
    initial_user_idx: int,
    initial_answer: str,
    field: str = "",
) -> tuple:
    """
    Walk forward from initial_user_idx through readback → correction → re-readback cycles.

    Returns (final_answer, confirmed, readback_attempted, new_consumed).
    - confirmed: True if caller said yes/correct/etc. after a readback
    - readback_attempted: True if assistant attempted a readback but caller never confirmed
      (caller hung up or abandoned the correction loop)
    """
    answer = initial_answer
    current_idx = initial_user_idx
    new_consumed: set = set()
    confirmed = False
    readback_attempted = False

    for _ in range(3):
        # Find next assistant turn after the current user turn
        next_asst_idx = None
        for k in range(current_idx + 1, len(turns)):
            if turns[k][0] == "assistant":
                next_asst_idx = k
                break

        if next_asst_idx is None:
            break

        if not _READBACK_ASST_RE.search(turns[next_asst_idx][1]):
            break  # Next assistant turn is not a readback; stop

        readback_attempted = True

        # Find next user turn after the readback
        next_user_idx = None
        for k in range(next_asst_idx + 1, len(turns)):
            if turns[k][0] == "user":
                next_user_idx = k
                break

        if next_user_idx is None:
            print(f"[READBACK] field={field!r} readback_detected=True user_confirmed=False confirmation_text=<hung up>", flush=True)
            break  # Caller hung up before confirming

        user_response = turns[next_user_idx][1].strip()

        # Strip leading filler words ("Oh yes", "Uh yeah") before confirmation check
        stripped_response = _CONFIRM_FILLER_RE.sub("", user_response).strip()

        is_confirmed = bool(_CONFIRM_USER_RE.search(stripped_response))
        is_rejected = bool(_REJECT_USER_RE.search(user_response))

        print(
            f"[READBACK] field={field!r} readback_detected=True "
            f"user_confirmed={is_confirmed} confirmation_text={user_response!r}",
            flush=True,
        )

        if is_confirmed:
            confirmed = True
            new_consumed.add(next_user_idx)
            break

        if is_rejected:
            new_consumed.add(next_user_idx)

            # Look for the re-ask from the assistant
            next_asst2_idx = None
            for k in range(next_user_idx + 1, len(turns)):
                if turns[k][0] == "assistant":
                    next_asst2_idx = k
                    break

            search_start = next_asst2_idx + 1 if next_asst2_idx is not None else next_user_idx + 1

            # Find the next user "value turn" (not a confirmation or rejection)
            next_value_idx = None
            for k in range(search_start, len(turns)):
                if turns[k][0] == "user":
                    t = turns[k][1].strip()
                    t_stripped = _CONFIRM_FILLER_RE.sub("", t).strip()
                    if not _CONFIRM_USER_RE.search(t_stripped) and not _REJECT_USER_RE.search(t):
                        next_value_idx = k
                        break

            if next_value_idx is not None:
                answer = turns[next_value_idx][1]
                new_consumed.add(next_value_idx)
                current_idx = next_value_idx
                continue

            # No separate value turn; extract any inline correction from the rejection turn
            inline = re.sub(
                r"^(no|nope|wait|actually|that.?s wrong|wrong)[,.]?\s*",
                "", user_response, flags=re.IGNORECASE,
            ).strip()
            if inline:
                answer = inline
            current_idx = next_user_idx
            continue

        # Unrecognized response after a readback — treat as unconfirmed but don't loop
        print(
            f"[READBACK] field={field!r} readback_detected=True "
            f"user_confirmed=False confirmation_text={user_response!r} (unrecognized)",
            flush=True,
        )
        break

    if not readback_attempted:
        print(f"[READBACK] field={field!r} readback_detected=False", flush=True)

    return answer, confirmed, readback_attempted, new_consumed


def _parse_transcript(messages: list, customer_number: str = "") -> dict:
    """
    Walk artifact.messages in order. For each assistant turn, identify which
    field it's asking about, then claim the IMMEDIATELY FOLLOWING unconsumed
    user turn as the answer. Each user turn can only be consumed once.
    """
    out = {
        "name": "",
        "phone": "",  # never pre-fill with caller ID; use _extract_from_vapi_body fallback
        "issue": "",
        "service_urgency": "",
        "service_address": "",
        "zip": "",
        "customer_type": "",
        "property_type": "",
        "email": "",
        "needs_verification": False,
    }

    turns: list[tuple[str, str]] = []
    for m in (messages or []):
        role = (m.get("role") or "").lower()
        text = _clean_text(m.get("content") or m.get("message") or "")
        if role in ("assistant", "bot") and text:
            turns.append(("assistant", text))
        elif role in ("user", "human", "customer") and text:
            turns.append(("user", text))

    consumed: set[int] = set()

    def _find_pair(keyword_re: str, exclude_re: str = "") -> tuple[int, str]:
        """
        Find the first (assistant, user) pairing where:
        - assistant turn matches keyword_re (and not exclude_re)
        - the immediately following user turn is unconsumed
        If a matching assistant turn's next user turn is consumed, tries the
        next matching assistant turn. Returns (user_idx, user_text) or (-1, "").
        """
        for i, (role, text) in enumerate(turns):
            if role != "assistant":
                continue
            lower = text.lower()
            if not re.search(keyword_re, lower):
                continue
            if exclude_re and re.search(exclude_re, lower):
                continue
            for j in range(i + 1, len(turns)):
                if turns[j][0] == "user":
                    if j not in consumed:
                        return j, turns[j][1]
                    break  # next user turn is consumed; try next matching assistant
        return -1, ""

    # 1. NAME — require explicit ask for the caller's name; skip assistant self-intros
    _NAME_STREET_WORDS = r"(?:loop|drive|road|avenue|street|circle|way|court|lane|boulevard|place|blvd|ave|dr|rd|ct|ln|st)\b"
    _NAME_META_PHRASES = re.compile(
        r"^(can you repeat|repeat that|residential|commercial|i.?m sorry|what was that"
        r"|i didn.?t|could you|sorry|i need)",
        re.IGNORECASE,
    )

    j, answer = _find_pair(
        r"\byour\s+(?:full\s+)?name\b|\bfull\s+name\b|\bget\s+your\s+name\b"
        r"|\bname\s+please\b|\bwhat.{0,15}your\s+name\b"
        r"|\bwho am i speaking\b|\bmay i ask who.{0,10}calling\b"
        r"|\bwho is this\b|\bcan i get a name\b|\bwhat should i call you\b"
    )
    if j >= 0:
        consumed.add(j)
        raw = _strip_mid_answer_correction(answer)
        final_raw, _confirmed, _rb, _nc = _trace_readback(turns, consumed, j, raw, field="name")
        consumed.update(_nc)
        if _rb and not _confirmed:
            out["needs_verification"] = True
        name = re.sub(r"^(yes|yeah|yep|yup|sure|okay|ok|alright)[.,!]?\s*", "", final_raw, flags=re.IGNORECASE).strip()
        name = re.sub(r"^(it.?s|my name is|i.?m|this is)\s+", "", name, flags=re.IGNORECASE).strip()
        name = re.sub(r"\s+\b(and|or|but)\b\s*$", "", name, flags=re.IGNORECASE).strip()
        _dw = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|oh)"
        phone_tail = re.search(rf"(?:\s+{_dw}){{5,}}\s*$", name, re.IGNORECASE)
        if phone_tail:
            if not out["phone"]:
                tail_n = _normalize_word_digits(phone_tail.group(0).strip())
                ph = _normalize_phone(tail_n) if re.search(r"\d{7,}", tail_n) else ""
                if ph:
                    out["phone"] = ph
            name = name[:phone_tail.start()].strip()
        # Sanity filter: reject if it looks like an address or a meta-phrase
        _name_is_address = bool(re.search(r"\d", name) and re.search(_NAME_STREET_WORDS, name, re.IGNORECASE))
        _name_is_meta = bool(_NAME_META_PHRASES.search(name))
        if _name_is_address or _name_is_meta:
            print(f"[NAME] rejected garbage name={name!r} (address={_name_is_address} meta={_name_is_meta})", flush=True)
            name = ""
        out["name"] = name or final_raw if not (_name_is_address or _name_is_meta) else ""

    # 2. PROPERTY TYPE — match before customer_type and issue so the opener is consumed first
    j, answer = _find_pair(r"\b(residential or commercial|commercial or residential|residential.*commercial)\b")
    if j >= 0:
        consumed.add(j)
        a = answer.lower()
        if re.search(r"\b(residential|home|house)\b", a):
            out["property_type"] = "residential"
        elif re.search(r"\b(commercial|business|office|shop)\b", a):
            out["property_type"] = "commercial"

    # 3. CUSTOMER TYPE
    j, answer = _find_pair(r"\b(existing|first.?time|new customer|existing.*customer|existing.*frost)\b")
    if j >= 0:
        consumed.add(j)
        a = answer.lower()
        if re.search(r"\b(existing|yes|i.?m a customer|called before|have called|i have)\b", a):
            out["customer_type"] = "existing"
        elif re.search(r"\b(new|first.?time|no|haven.?t called|first)\b", a):
            out["customer_type"] = "new"

    # 4. PHONE — skip if already captured from name turn
    if not out["phone"]:
        j, answer = _find_pair(r"\b(phone.{0,10}number|callback|call.{0,8}back|number to call|best number)\b")
        if j >= 0:
            consumed.add(j)
            raw = _strip_mid_answer_correction(answer)
            final_raw, _confirmed, _rb, _nc = _trace_readback(turns, consumed, j, raw, field="phone")
            consumed.update(_nc)
            if _rb and not _confirmed:
                out["needs_verification"] = True
            answer_n = _normalize_word_digits(final_raw)
            ph = _extract_phone_from_text(answer_n) or (
                _normalize_phone(answer_n) if re.search(r"\d{7,}", answer_n) else ""
            )
            if ph:
                out["phone"] = ph

    # 5. EMAIL
    j, answer = _find_pair(r"\bemail\b")
    if j >= 0:
        consumed.add(j)
        raw = _strip_mid_answer_correction(answer)
        final_raw, _confirmed, _rb, _nc = _trace_readback(turns, consumed, j, raw, field="email")
        consumed.update(_nc)
        if _rb and not _confirmed:
            out["needs_verification"] = True
        normalized_email = _normalize_email(final_raw)
        out["email"] = normalized_email
        # If email has no valid TLD after normalization, flag for verification
        if normalized_email and "@" in normalized_email and not re.search(r"@[\w.-]+\.\w{2,}$", normalized_email):
            out["needs_verification"] = True
            print(f"[EMAIL] missing TLD after normalization: {normalized_email!r}", flush=True)

    # 6. ISSUE — explicit issue question from assistant (primary), HVAC keyword fallback (last resort)
    _issue_exclude_re = r"anything else|else.*help|is there something else|all set|that.{0,10}everything|is that everything"
    _issue_primary_re = (
        r"(what.{0,20}going on|what.{0,20}happening"
        r"|tell me about.*issue|tell me about what"
        r"|can you describe"
        r"|what.{0,5}(?:is|s) the issue"
        r"|what brings you)"
    )
    _issue_source: str = ""
    _issue_asst_q: str = ""

    if not out["issue"]:
        # Primary: walk turns to find assistant explicitly asking about the issue
        for i, (role, text) in enumerate(turns):
            if role != "assistant":
                continue
            lower = text.lower()
            if not re.search(_issue_primary_re, lower):
                continue
            if re.search(_issue_exclude_re, lower):
                continue
            for jj in range(i + 1, len(turns)):
                if turns[jj][0] == "user":
                    if jj not in consumed:
                        m = re.search(_issue_primary_re, lower)
                        _issue_asst_q = m.group(0) if m else text[:80]
                        consumed.add(jj)
                        out["issue"] = _compact_reason(turns[jj][1])
                        _issue_source = "primary"
                    break
            if out["issue"]:
                break

    # 6b. ISSUE fallback — last resort: HVAC keyword in any unconsumed user turn
    if not out["issue"]:
        _hvac_re = re.compile(
            r"blowing (?:warm|hot|cold)"
            r"|not turning on|won.{0,2}t turn on"
            r"|not cooling|not heating"
            r"|making noise|grinding|buzzing|rattling"
            r"|leaking|water"
            r"|freezing up|frozen"
            r"|AC (?:broken|stopped|down)"
            r"|heat (?:broken|stopped)|no heat"
            r"|smells?",
            re.IGNORECASE,
        )
        for idx, (role, text) in enumerate(turns):
            if role != "user":
                continue
            if idx in consumed:
                continue
            if re.search(_issue_exclude_re, text, re.IGNORECASE):
                continue
            if _hvac_re.search(text):
                _issue_asst_q = "(none — user volunteered)"
                consumed.add(idx)
                out["issue"] = _compact_reason(text)
                _issue_source = "fallback"
                break

    if out["issue"]:
        print(f"[ISSUE] assistant_question={_issue_asst_q!r} user_response={out['issue']!r} source={_issue_source!r}", flush=True)

    # 7. SERVICE URGENCY
    j, answer = _find_pair(
        r"\b(urgent|when would|what day|what date|what time|how soon|when.{0,10}work|best time|schedule)\b"
    )
    if j >= 0:
        consumed.add(j)
        timing = _extract_timing(answer)
        if timing:
            out["service_urgency"] = timing
        elif re.search(r"\b(asap|right away|immediately|today)\b", answer, re.IGNORECASE):
            out["service_urgency"] = "ASAP"
        else:
            out["service_urgency"] = _clean_text(answer).rstrip(".")[:60]

    # 8. ADDRESS — last; exclude "email address" questions (consumed in step 5)
    j, answer = _find_pair(
        r"\b(address|zip|postal|street|location|where.{0,10}you)\b",
        exclude_re=r"\bemail\b",
    )
    if j >= 0:
        consumed.add(j)
        raw = _strip_mid_answer_correction(answer)
        final_raw, _confirmed, _rb, _nc = _trace_readback(turns, consumed, j, raw, field="address")
        consumed.update(_nc)
        if _rb and not _confirmed:
            out["needs_verification"] = True
        final_raw = re.sub(
            r"^(?:yes|yeah|yep|yup|sure|okay|ok|alright|so)[.,!]?\s*",
            "", final_raw, flags=re.IGNORECASE,
        ).strip()
        final_raw = re.sub(
            r"^(?:it.?s|the address is|my address is|it is)\s+(?:at\s+)?",
            "", final_raw, flags=re.IGNORECASE,
        ).strip()
        answer_n = _normalize_word_digits(final_raw)
        zip_match = re.search(r"\b(\d{5})\b", answer_n)
        if zip_match and len(answer_n.strip()) <= 12:
            out["zip"] = zip_match.group(1)
        else:
            out["service_address"] = answer_n.strip()
            if not out["zip"] and zip_match:
                out["zip"] = zip_match.group(1)

    # Phone fallback: scan remaining unconsumed user turns for a digit string
    if not out["phone"]:
        for j, (r, t) in enumerate(turns):
            if r == "user" and j not in consumed:
                t_n = _normalize_word_digits(t)
                ph = _extract_phone_from_text(t_n) or (
                    _normalize_phone(t_n) if re.search(r"\d{7,}", t_n) else ""
                )
                if ph:
                    out["phone"] = ph
                    break

    print(f"[VAPI TRANSCRIPT] parsed: {out}", flush=True)
    return out


def _extract_tool_call_args(messages: list) -> dict:
    """
    Secondary fallback: find hvac_intake tool call args in artifact.messages.
    Vapi includes these even in end-of-call payloads.
    """
    for msg in reversed(messages or []):
        role = (msg.get("role") or "").lower()
        if role in ("tool_call", "tool_calls"):
            for tc in (msg.get("toolCalls") or []):
                fn = tc.get("function") or {}
                if fn.get("name") == "hvac_intake":
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = _json.loads(args)
                        except Exception:
                            args = {}
                    print(f"[VAPI TOOL-ARGS] found hvac_intake args: {args}", flush=True)
                    return args
    return {}


def _reason_for_sms(reason: Optional[str], summary: Optional[str]) -> str:
    reason_text = _clean_text(reason)
    if reason_text and reason_text.lower() != "pending":
        return _compact_reason(reason_text)

    summary_text = _clean_text(summary)
    if not summary_text:
        return ""

    match = re.match(r"(.+?)(?:[.!?]|$)", summary_text)
    if match:
        return match.group(1).strip(" ,.")
    return summary_text


def _extract_from_vapi_body(body: dict) -> dict:
    """
    Extract intake fields from a Vapi end-of-call-report payload.

    Priority order:
      1. Transcript conversation parsing (_parse_transcript) — most reliable
      2. hvac_intake tool call args found in artifact.messages — strong fallback
      3. analysis.structuredData — only if Vapi assistant is configured to populate it
      4. call.customer.number — always used as phone fallback
    """
    if "message" not in body:
        return body

    msg = body.get("message") or {}
    call = msg.get("call") or {}
    analysis = msg.get("analysis") or {}
    structured = analysis.get("structuredData") or {}
    summary = msg.get("summary") or analysis.get("summary") or ""
    artifact = msg.get("artifact") or {}
    artifact_messages = artifact.get("messages") or []

    customer = call.get("customer") or {}
    customer_number = customer.get("number") or ""
    phone_number_id = call.get("phoneNumberId") or ""
    call_id = call.get("id") or ""
    forwarded_from = call.get("forwardingPhoneNumber") or call.get("forwardedFrom") or ""

    print(
        f"[VAPI EXTRACT] call_id={call_id!r} phoneNumberId={phone_number_id!r} "
        f"artifact_messages={len(artifact_messages)} structured={bool(structured)}",
        flush=True,
    )

    # Layer 1: parse the actual conversation transcript
    transcript = _parse_transcript(artifact_messages, customer_number=customer_number)

    # Layer 2: hvac_intake tool call args (mid-call args stored in artifact.messages)
    tool_args = _extract_tool_call_args(artifact_messages)

    def _first(*values):
        return next((v for v in values if v and str(v).strip()), "")

    name = _first(
        transcript.get("name"),
        tool_args.get("name"), tool_args.get("caller_name"),
        structured.get("name"), structured.get("caller_name"),
        _extract_name_from_text(summary),
    )
    phone = _first(
        transcript.get("phone"),
        tool_args.get("phone"), tool_args.get("callback_phone"), tool_args.get("phone_number"),
        structured.get("phone"), structured.get("phoneNumber"), structured.get("callback_phone"),
        _extract_phone_from_text(summary),
        _normalize_phone(customer_number),
    )
    issue = _first(
        transcript.get("issue"),
        tool_args.get("issue"), tool_args.get("reason"),
        structured.get("issue"), structured.get("reason"),
        _compact_reason(summary),
    )
    service_address = _first(
        transcript.get("service_address"),
        tool_args.get("service_address"), tool_args.get("address"),
        structured.get("service_address"), structured.get("address"),
    )
    zip_code = _first(
        transcript.get("zip"),
        tool_args.get("zip"), tool_args.get("zip_code"),
        structured.get("zip"), structured.get("zip_code"),
        _extract_zip(summary),
    )
    service_urgency = _normalize_urgency(_first(
        transcript.get("service_urgency"),
        tool_args.get("service_urgency"), tool_args.get("timing"),
        structured.get("service_urgency"),
        _extract_timing(summary),
    ))
    customer_type = _first(
        transcript.get("customer_type"),
        tool_args.get("customer_type"),
        structured.get("customer_type"),
    )
    property_type = _first(
        transcript.get("property_type"),
        tool_args.get("property_type"),
        structured.get("property_type"),
    )
    email = _first(
        transcript.get("email"),
        tool_args.get("email"),
        structured.get("email"),
    ) or None

    needs_verification = bool(transcript.get("needs_verification"))

    print(
        f"[VAPI EXTRACT] final: name={name!r} phone={phone!r} issue={issue!r} "
        f"urgency={service_urgency!r} address={service_address!r} zip={zip_code!r} "
        f"customer_type={customer_type!r} property_type={property_type!r} email={email!r} "
        f"needs_verification={needs_verification}",
        flush=True,
    )

    return {
        "call_id": call_id,
        "name": name,
        "phone": phone,
        "issue": issue,
        "email": email,
        "summary": summary,
        "zip": zip_code,
        "service_address": service_address or None,
        "service_urgency": service_urgency,
        "customer_type": customer_type or None,
        "property_type": property_type or None,
        "phone_number_id": phone_number_id,
        "forwarded_from": forwarded_from,
        "needs_verification": needs_verification,
    }


def _resolve_tenant(phone_number_id: Optional[str], session: Session) -> Optional[str]:
    """Identify the tenant by matching call.phoneNumberId against Tenant.twilio_number."""
    if not phone_number_id:
        fallback = (os.getenv("VAPI_DEFAULT_TENANT") or "").strip()
        if fallback:
            print(f"[VAPI] phone_number_id empty - using VAPI_DEFAULT_TENANT={fallback!r}", flush=True)
            return fallback
        print("[VAPI] ERROR: phone_number_id empty - cannot resolve tenant.", flush=True)
        return None

    rows = session.exec(
        select(Tenant).where(
            Tenant.twilio_number != None,
            Tenant.twilio_number != "",
        )
    ).all()
    candidates = {t.slug: t.twilio_number for t in rows}
    print(f"[VAPI] tenant lookup: phone_number_id={phone_number_id!r} candidates={candidates}", flush=True)

    for t in rows:
        if (t.twilio_number or "").strip() == phone_number_id.strip():
            print(f"[VAPI] tenant resolved: phone_number_id={phone_number_id!r} -> {t.slug!r}", flush=True)
            return t.slug

    print(
        f"[VAPI] ERROR: phone_number_id={phone_number_id!r} unmatched against "
        f"Tenant.twilio_number - lead will NOT be saved.",
        flush=True,
    )
    return None


def _dedupe_insert(session: Session, source: str, event_id: str) -> bool:
    try:
        session.rollback()
        session.add(WebhookDedup(source=source, event_id=event_id))
        session.commit()
        return True
    except IntegrityError:
        session.rollback()
        return False
    except Exception as e:
        session.rollback()
        print(f"[VAPI] dedupe insert error: {e}", flush=True)
        return False



async def _handle_tool_call(body: dict, background_tasks: BackgroundTasks):
    """
    Handle VAPI tool-call events mid-conversation.
    hvac_intake: acknowledge only — all data capture happens on end-of-call-report.
    No DB writes, no SMS sends here.
    """
    msg = body.get("message") or {}
    tool_calls = msg.get("toolCalls") or msg.get("toolCallList") or []
    call = msg.get("call") or {}
    call_id = call.get("id") or ""

    print(
        f"[VAPI TOOL-CALL] mid-call ack-only call_id={call_id!r} "
        f"tools={[tc.get('function', {}).get('name') for tc in tool_calls]}",
        flush=True,
    )

    results = []
    for tc in tool_calls:
        tc_id = tc.get("id") or ""
        fn_name = (tc.get("function") or {}).get("name") or ""
        if fn_name == "hvac_intake":
            results.append({"toolCallId": tc_id, "result": "Got it, we'll have them call you back shortly."})
        else:
            results.append({"toolCallId": tc_id, "result": "ok"})

    return {"results": results}


@router.post("/vapi/intake")
async def vapi_intake(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    try:
        raw_body = await request.body()
        raw_text = raw_body.decode("utf-8", errors="replace")
        print(f"[VAPI] raw body received: {raw_text[:2000]}", flush=True)
        body: Any = _json.loads(raw_text) if raw_text.strip() else {}
    except Exception as e:
        print(f"[VAPI] body parse error: {e}", flush=True)
        body = {}

    msg_type = _message_type(body)
    if msg_type == "tool-calls":
        print(f"[VAPI TOOL-CALL RAW] {raw_text[:3000]}", flush=True)
        try:
            return await _handle_tool_call(body, background_tasks)
        except Exception as e:
            print(f"[VAPI TOOL-CALL ERROR] {e}", flush=True)
            msg = body.get("message") or {}
            tool_calls = msg.get("toolCalls") or msg.get("toolCallList") or []
            results = [{"toolCallId": tc.get("id") or "", "result": "Received."} for tc in tool_calls]
            return {"results": results}
    if msg_type and msg_type != "end-of-call-report":
        print(f"[VAPI] ignoring non-final event type={msg_type!r}", flush=True)
        return {"status": "ok", "ignored_event_type": msg_type}

    flat = _extract_from_vapi_body(body) if isinstance(body, dict) else {}
    payload = VapiIntakePayload(**{k: v for k, v in flat.items() if k in VapiIntakePayload.model_fields})

    tenant_id = _resolve_tenant(payload.phone_number_id, session)
    print(
        f"[VAPI] intake - phone_number_id={payload.phone_number_id!r} forwarded_from={payload.forwarded_from!r} "
        f"tenant_id={tenant_id!r} caller={payload.phone!r} name={payload.name!r}",
        flush=True,
    )

    if tenant_id is None:
        print(
            f"[VAPI] DROPPING lead - tenant unresolved. "
            f"caller={payload.phone!r} name={payload.name!r} issue={payload.issue!r} "
            f"forwarded_from={payload.forwarded_from!r}",
            flush=True,
        )
        return {"status": "error", "detail": "tenant not resolved"}

    if payload.call_id and not _dedupe_insert(session, source=f"vapi_intake:{tenant_id}", event_id=payload.call_id):
        print(f"[VAPI] duplicate intake ignored for tenant={tenant_id!r} call_id={payload.call_id!r}", flush=True)
        return {"status": "ok", "tenant_id": tenant_id, "deduped": True}

    name = (payload.name or "").strip()
    phone = (payload.phone or "").strip()
    issue = (payload.issue or "").strip()
    email = (payload.email or "").strip() or None
    service_urgency = (payload.service_urgency or "").strip() or None
    service_address = (payload.service_address or "").strip() or None
    zip_code = (payload.zip or "").strip() or None
    customer_type = (payload.customer_type or "").strip() or None
    property_type = (payload.property_type or "").strip() or None
    needs_verification = bool(payload.needs_verification)

    message = issue or "Inbound call via Vapi"

    # Partial lead: fewer than 2 of (name, issue, address/zip) were captured
    key_fields = [name, issue, service_address or zip_code]
    populated_count = sum(1 for f in key_fields if f)
    is_partial = populated_count < 2

    print(
        f"[VAPI] saving lead tenant={tenant_id!r} partial={is_partial} "
        f"name={name!r} phone={phone!r} issue={issue!r} urgency={service_urgency!r} "
        f"address={service_address!r} zip={zip_code!r} "
        f"customer_type={customer_type!r} property_type={property_type!r}",
        flush=True,
    )

    lead = LeadModel(
        name=name or "Unknown caller",
        phone=phone,
        email=email,
        message=message,
        tenant_id=tenant_id,
        source="vapi",
        service_urgency=service_urgency,
        service_address=service_address,
        customer_type=customer_type,
        property_type=property_type,
        needs_callback_for_scheduling=(service_urgency == "needs scheduling"),
        needs_verification=needs_verification,
    )
    try:
        session.add(lead)
        session.commit()
        session.refresh(lead)
    except Exception as e:
        session.rollback()
        print(f"[VAPI] lead insert error: {e}", flush=True)

    try:
        vapi_lead_office_sms(tenant_id, {
            "name": name,
            "phone": phone,
            "email": email,
            "issue": issue,
            "zip": zip_code,
            "service_address": service_address,
            "service_urgency": service_urgency,
            "customer_type": customer_type,
            "property_type": property_type,
            "partial": is_partial,
            "needs_verification": needs_verification,
        })
        print(f"[VAPI] office SMS sent for tenant={tenant_id!r} partial={is_partial} needs_verification={needs_verification}", flush=True)
    except Exception as e:
        print(f"[VAPI] office SMS error: {e}", flush=True)

    return {"status": "ok", "tenant_id": tenant_id}
