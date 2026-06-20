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


def _normalize_word_digits(text: str) -> str:
    """
    Convert consecutive runs of spoken digit-words into numeric strings.
    Non-digit words pass through unchanged.

    'six nine five nine Main Street, Apopka, Florida, three four seven three six'
    → '6959 Main Street, Apopka, Florida, 34736'
    """
    if not text:
        return text
    tokens = text.split()
    result: list[str] = []
    i = 0
    while i < len(tokens):
        # Strip trailing punctuation only for the lookup; preserve it in output
        # for non-digit words, but drop it for digit words (period after "six." → "6")
        bare = tokens[i].lower().rstrip(".,;:")
        if bare in _WORD_TO_DIGIT:
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
    return " ".join(result)


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
                word = "".join(letters)
                if digs:
                    word += "".join(digs)
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

    def _claim_next_user(after_idx: int) -> tuple[int, str]:
        """Return (index, text) of the first unconsumed user turn after after_idx."""
        for j in range(after_idx + 1, len(turns)):
            if turns[j][0] == "user" and j not in consumed:
                return j, turns[j][1]
        return -1, ""

    def _find_assistant(keyword_re: str, exclude_re: str = "") -> int:
        """Return index of first assistant turn matching keyword_re (skipping exclude_re matches)."""
        for i, (role, text) in enumerate(turns):
            if role != "assistant":
                continue
            lower = text.lower()
            if re.search(keyword_re, lower):
                if exclude_re and re.search(exclude_re, lower):
                    continue
                return i
        return -1

    # 1. NAME — parse first so the name answer is locked before any other field runs
    i = _find_assistant(r"\bname\b")
    if i >= 0:
        j, answer = _claim_next_user(i)
        if j >= 0:
            consumed.add(j)
            name = re.sub(r"^(yes|yeah|yep|yup|sure|okay|ok|alright)[.,!]?\s*", "", answer, flags=re.IGNORECASE).strip()
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
            out["name"] = name or answer

    # 2. PHONE — explicit phone question; skip if already recovered from name turn
    if not out["phone"]:
        i = _find_assistant(r"\b(phone.{0,10}number|callback|call.{0,8}back|number to call|best number)\b")
        if i >= 0:
            j, answer = _claim_next_user(i)
            if j >= 0:
                consumed.add(j)
                answer_n = _normalize_word_digits(answer)
                ph = _extract_phone_from_text(answer_n) or (
                    _normalize_phone(answer_n) if re.search(r"\d{7,}", answer_n) else ""
                )
                if ph:
                    out["phone"] = ph

    # 3. EMAIL
    i = _find_assistant(r"\bemail\b")
    if i >= 0:
        j, answer = _claim_next_user(i)
        if j >= 0:
            consumed.add(j)
            out["email"] = _normalize_email(answer)

    # 4. ISSUE
    i = _find_assistant(
        r"(what.{0,20}going on|what.{0,20}happening|how can i help|what.{0,15}problem"
        r"|what.{0,15}issue|what brings|help you today|can i help|tell me more|describe"
        r"|blowing warm|not turning on|leaking)"
    )
    if i >= 0:
        j, answer = _claim_next_user(i)
        if j >= 0:
            consumed.add(j)
            out["issue"] = _compact_reason(answer)

    # 5. CUSTOMER TYPE
    i = _find_assistant(r"\b(existing|first.?time|new customer|existing.*customer|existing.*frost)\b")
    if i >= 0:
        j, answer = _claim_next_user(i)
        if j >= 0:
            consumed.add(j)
            a = answer.lower()
            if re.search(r"\b(existing|yes|i.?m a customer|called before|have called|i have)\b", a):
                out["customer_type"] = "existing"
            elif re.search(r"\b(new|first.?time|no|haven.?t called|first)\b", a):
                out["customer_type"] = "new"

    # 6. PROPERTY TYPE
    i = _find_assistant(r"\b(residential or commercial|commercial or residential|residential.*commercial)\b")
    if i >= 0:
        j, answer = _claim_next_user(i)
        if j >= 0:
            consumed.add(j)
            a = answer.lower()
            if re.search(r"\b(residential|home|house)\b", a):
                out["property_type"] = "residential"
            elif re.search(r"\b(commercial|business|office|shop)\b", a):
                out["property_type"] = "commercial"

    # 7. SERVICE URGENCY
    i = _find_assistant(
        r"\b(urgent|when would|what day|what date|what time|how soon|when.{0,10}work|best time|schedule)\b"
    )
    if i >= 0:
        j, answer = _claim_next_user(i)
        if j >= 0:
            consumed.add(j)
            timing = _extract_timing(answer)
            if timing:
                out["service_urgency"] = timing
            elif re.search(r"\b(asap|right away|immediately|today)\b", answer, re.IGNORECASE):
                out["service_urgency"] = "ASAP"
            else:
                out["service_urgency"] = _clean_text(answer).rstrip(".")[:60]

    # 8. ADDRESS — last; exclude "email address" questions (already consumed in step 3)
    i = _find_assistant(
        r"\b(address|zip|postal|street|location|where.{0,10}you)\b",
        exclude_re=r"\bemail\b",
    )
    if i >= 0:
        j, answer = _claim_next_user(i)
        if j >= 0:
            consumed.add(j)
            answer = re.sub(
                r"^(?:yes|yeah|yep|yup|sure|okay|ok|alright|so)[.,!]?\s*",
                "", answer, flags=re.IGNORECASE,
            ).strip()
            answer = re.sub(
                r"^(?:it.?s|the address is|my address is|it is)\s+(?:at\s+)?",
                "", answer, flags=re.IGNORECASE,
            ).strip()
            answer_n = _normalize_word_digits(answer)
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

    print(
        f"[VAPI EXTRACT] final: name={name!r} phone={phone!r} issue={issue!r} "
        f"urgency={service_urgency!r} address={service_address!r} zip={zip_code!r} "
        f"customer_type={customer_type!r} property_type={property_type!r} email={email!r}",
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


def _process_tool_call_background(tenant_id: str, call_id: str, name: str, phone: str, issue: str, zip_code: str, service_urgency: str):
    """DB + SMS work done after VAPI already got its response."""
    try:
        gen = get_session()
        session = next(gen)
        try:
            if call_id and not _dedupe_insert(session, source=f"vapi_tool:{tenant_id}", event_id=call_id):
                print(f"[VAPI TOOL-CALL] duplicate ignored call_id={call_id!r}", flush=True)
                return

            lead = LeadModel(
                name=name,
                phone=phone or "",
                email=None,
                message=issue or "Inbound call via Vapi",
                tenant_id=tenant_id,
                source="vapi",
                service_urgency=service_urgency or None,
                needs_callback_for_scheduling=(service_urgency == "needs scheduling"),
            )
            session.add(lead)
            session.commit()
            print(f"[VAPI TOOL-CALL] lead saved for tenant={tenant_id!r}", flush=True)
        except Exception as e:
            session.rollback()
            print(f"[VAPI TOOL-CALL] lead insert error: {e}", flush=True)
        finally:
            session.close()
    except Exception as e:
        print(f"[VAPI TOOL-CALL] background session error: {e}", flush=True)

    try:
        vapi_lead_office_sms(tenant_id, {
            "name": name,
            "phone": phone,
            "issue": issue,
            "zip": zip_code,
            "service_urgency": service_urgency,
        })
    except Exception as e:
        print(f"[VAPI TOOL-CALL] office SMS error: {e}", flush=True)


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
        name=name or phone or "Unknown caller",
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
        })
        print(f"[VAPI] office SMS sent for tenant={tenant_id!r} partial={is_partial}", flush=True)
    except Exception as e:
        print(f"[VAPI] office SMS error: {e}", flush=True)

    return {"status": "ok", "tenant_id": tenant_id}
