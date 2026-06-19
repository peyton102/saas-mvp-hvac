# app/routers/vapi.py
import json as _json
import os
import re
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
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


def _parse_transcript(messages: list, customer_number: str = "") -> dict:
    """
    Walk artifact.messages in order. For each assistant turn, identify which
    field it's asking about, then claim the IMMEDIATELY FOLLOWING unconsumed
    user turn as the answer. Each user turn can only be consumed once.
    """
    out = {
        "name": "",
        "phone": _normalize_phone(customer_number) if customer_number else "",
        "issue": "",
        "service_urgency": "",
        "service_address": "",
        "zip": "",
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

    for i, (role, text) in enumerate(turns):
        if role != "assistant":
            continue
        lower = text.lower()

        # Issue — "what's going on / how can I help / describe"
        if not out["issue"] and re.search(
            r"(what.{0,20}going on|how can i help|what.{0,15}problem|what.{0,15}issue"
            r"|what brings|help you today|can i help|tell me more|describe)",
            lower,
        ):
            j, answer = _claim_next_user(i)
            if j >= 0:
                consumed.add(j)
                out["issue"] = _compact_reason(answer)

        # Name — "name"
        elif not out["name"] and re.search(r"\bname\b", lower):
            j, answer = _claim_next_user(i)
            if j >= 0:
                consumed.add(j)
                words = answer.split()
                out["name"] = " ".join(words[:3]) if len(words) > 3 else answer

        # Phone — "phone number / callback number"
        elif re.search(r"\b(phone.{0,10}number|callback|call.{0,8}back)\b", lower):
            j, answer = _claim_next_user(i)
            if j >= 0:
                consumed.add(j)  # consume regardless so it can't bleed into other fields
                ph = _extract_phone_from_text(answer) or (
                    _normalize_phone(answer) if re.search(r"\d{7,}", answer) else ""
                )
                if ph:
                    out["phone"] = ph

        # Urgency — "urgent / when would / what day / best time"
        elif not out["service_urgency"] and re.search(
            r"\b(urgent|when would|what day|what time|how soon|when.{0,10}work|best time|schedule)\b",
            lower,
        ):
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

        # Address / ZIP — "address / ZIP / street"
        elif not out["service_address"] and not out["zip"] and re.search(
            r"\b(address|zip|postal|street|location|where.{0,10}you)\b", lower
        ):
            j, answer = _claim_next_user(i)
            if j >= 0:
                consumed.add(j)
                zip_match = re.search(r"\b(\d{5})\b", answer)
                if zip_match and len(answer.strip()) <= 12:
                    out["zip"] = zip_match.group(1)
                else:
                    out["service_address"] = answer.strip()
                    if not out["zip"] and zip_match:
                        out["zip"] = zip_match.group(1)

    # Phone fallback: scan unconsumed user turns for a phone number
    if not out["phone"]:
        for j, (r, t) in enumerate(turns):
            if r == "user" and j not in consumed:
                ph = _extract_phone_from_text(t) or (
                    _normalize_phone(t) if re.search(r"\d{7,}", t) else ""
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
    service_urgency = _first(
        transcript.get("service_urgency"),
        tool_args.get("service_urgency"), tool_args.get("timing"),
        structured.get("service_urgency"),
        _extract_timing(summary),
    )

    print(
        f"[VAPI EXTRACT] final: name={name!r} phone={phone!r} issue={issue!r} "
        f"urgency={service_urgency!r} address={service_address!r} zip={zip_code!r}",
        flush=True,
    )

    return {
        "call_id": call_id,
        "name": name,
        "phone": phone,
        "issue": issue,
        "summary": summary,
        "zip": zip_code,
        "service_address": service_address or None,
        "service_urgency": service_urgency,
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
    service_urgency = (payload.service_urgency or "").strip() or None
    service_address = (payload.service_address or "").strip() or None
    zip_code = (payload.zip or "").strip() or None

    message = issue or "Inbound call via Vapi"

    # Partial lead: fewer than 2 of (name, issue, address/zip) were captured
    key_fields = [name, issue, service_address or zip_code]
    populated_count = sum(1 for f in key_fields if f)
    is_partial = populated_count < 2

    print(
        f"[VAPI] saving lead tenant={tenant_id!r} partial={is_partial} "
        f"name={name!r} phone={phone!r} issue={issue!r} urgency={service_urgency!r} "
        f"address={service_address!r} zip={zip_code!r}",
        flush=True,
    )

    lead = LeadModel(
        name=name or phone or "Unknown caller",
        phone=phone,
        email=None,
        message=message,
        tenant_id=tenant_id,
        source="vapi",
        service_urgency=service_urgency,
        service_address=service_address,
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
            "issue": issue,
            "zip": zip_code,
            "service_address": service_address,
            "service_urgency": service_urgency,
            "partial": is_partial,
        })
        print(f"[VAPI] office SMS sent for tenant={tenant_id!r} partial={is_partial}", flush=True)
    except Exception as e:
        print(f"[VAPI] office SMS error: {e}", flush=True)

    return {"status": "ok", "tenant_id": tenant_id}
