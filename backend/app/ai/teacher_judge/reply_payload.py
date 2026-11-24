"""Parse the model's final JSON reply and structured conversation focus (package-internal)."""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai.teacher_judge.proposal_tools import PROPOSAL_TOOL_NAMES


def _as_text_list(value: Any) -> list[Any]:
    """Coerce a model-emitted list field: a bare string is one entry, junk is none."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return value
    return []


def conversation_focus_from_content(
    content: str,
    *,
    proposal: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Keep only compact, model-stated requirement facts needed by the next turn."""
    _leftover, payload = reply_payload_object(content)
    if payload is None:
        return None
    raw_focus = payload.get("conversation_focus")
    if not isinstance(raw_focus, dict):
        return None
    raw_requirements = raw_focus.get("requirements")
    if not isinstance(raw_requirements, list):
        return None
    requirements: list[dict[str, Any]] = []
    for raw in raw_requirements[:4]:
        if not isinstance(raw, dict):
            continue
        focus_key = str(raw.get("focus_key") or "").strip()[:40]
        if not focus_key:
            continue
        known = _as_text_list(raw.get("known_information"))
        missing = _as_text_list(raw.get("missing_information"))
        target_item_id = str(raw.get("target_item_id") or "").strip() or None
        requirements.append(
            {
                "focus_key": focus_key,
                "status": (
                    "ready"
                    if proposal and raw.get("status") == "ready"
                    else "needs_information"
                    if any(str(value).strip() for value in missing)
                    else "unsupported"
                    if raw.get("status") == "unsupported"
                    else "none"
                ),
                "known_information": [
                    str(value).strip()[:80] for value in known if str(value).strip()
                ][:3],
                "missing_information": [
                    str(value).strip()[:80] for value in missing if str(value).strip()
                ][:3],
                **({"target_item_id": target_item_id} if target_item_id else {}),
            }
        )
    if not requirements:
        return None
    return {
        "turn_kind": str(raw_focus.get("turn_kind") or "requirement")
        if raw_focus.get("turn_kind") in {"question", "requirement", "follow_up"}
        else "requirement",
        "requirements": requirements,
    }


def structured_requirement_needs_candidate(content: str) -> bool:
    """Detect a concrete requirement that the model left without a candidate or gap."""
    _leftover, payload = reply_payload_object(content)
    if payload is None:
        return False
    focus = payload.get("conversation_focus")
    if not isinstance(focus, dict) or focus.get("turn_kind") not in {
        "requirement",
        "follow_up",
    }:
        return False
    requirements = focus.get("requirements")
    if not isinstance(requirements, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("status") not in {"needs_information", "unsupported"}
        and not any(
            str(value).strip()
            for value in _as_text_list(item.get("missing_information"))
        )
        for item in requirements
    )


def structured_requirement_target_item(content: str) -> str | None:
    """Return the item id the structured focus points at, when editing intent."""
    _leftover, payload = reply_payload_object(content)
    if payload is None:
        return None
    focus = payload.get("conversation_focus")
    if not isinstance(focus, dict):
        return None
    requirements = focus.get("requirements")
    if not isinstance(requirements, list):
        return None
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        target = str(requirement.get("target_item_id") or "").strip()
        if target:
            return target
    return None


# Fenced JSON is accepted only for the non-executable reply payload. Tool calls
# must arrive through the native ``tool_calls`` field.
_JSON_FENCE_RE = re.compile(
    r"```(?:json|tool_code)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)


_PROPOSAL_STATUS_VALUES = {"ready", "needs_information", "unsupported", "none"}

_REPLY_PAYLOAD_KEYS_RE = re.compile(
    r'"(?:reply|proposal_status|conversation_focus)"\s*:'
)


def contains_embedded_tool_call(content: str) -> bool:
    """辨識可執行協定外洩；只能拒絕，不能從 prose 恢復執行。"""

    text = content or ""
    if "<|tool_call|>" in text or "<tool_call>" in text:
        return True
    for match in _JSON_FENCE_RE.finditer(text):
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(
            value, dict
        ):  # pragma: no cover - fence 只擷取 {…}，必為 dict
            continue
        name = value.get("name")
        if isinstance(value.get("tool_call"), dict):
            name = value["tool_call"].get("name")
        if name in PROPOSAL_TOOL_NAMES:
            return True
    return False


def _is_reply_payload_object(value: Any) -> bool:
    """Recognize the structured chat reply payload across model variants."""
    if not isinstance(value, dict):
        return False
    reply = value.get("reply")
    if isinstance(reply, str) and reply.strip():
        return True
    if value.get("proposal_status") in _PROPOSAL_STATUS_VALUES:
        return True
    return isinstance(value.get("conversation_focus"), dict)


def reply_payload_object(content: str) -> tuple[str, dict[str, Any] | None]:
    """Extract the structured reply payload from raw, fenced or mixed text.

    The prompt asks the model to answer with one plain JSON object (reply /
    proposal_status / conversation_focus), but Qwen-family models sometimes
    wrap it in a ```json fence or emit it next to leftover prose instead of
    plain JSON. Return the text with every recognized payload blob removed
    plus the first parsed payload, so internal fields never reach the reply.
    """
    text = (content or "").strip()
    if not text:
        return "", None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if _is_reply_payload_object(parsed):
        return "", parsed
    payload: dict[str, Any] | None = None
    leftover = text
    for match in _JSON_FENCE_RE.finditer(text):
        try:
            parsed = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            continue
        if _is_reply_payload_object(parsed):
            if payload is None:
                payload = parsed
            leftover = leftover.replace(match.group(0), "")
    if payload is not None:
        return leftover.strip(), payload
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        brace = text.find("{", index)
        if brace < 0:
            break
        try:
            parsed, end = decoder.raw_decode(text, brace)
        except ValueError:
            index = brace + 1
            continue
        if _is_reply_payload_object(parsed):
            # raw_decode returns an absolute end index, not a length.
            leftover = (text[:brace] + text[end:]).strip()
            return leftover, parsed
        index = end
    # Unparseable fence bodies still carrying internal payload keys are
    # contract noise, not teacher-facing prose; drop them as a safety net.
    for match in _JSON_FENCE_RE.finditer(text):
        if _REPLY_PAYLOAD_KEYS_RE.search(match.group(1)):
            leftover = leftover.replace(match.group(0), "")
    return leftover.strip(), None


def parse_chat_reply_payload(content: str) -> tuple[str, str | None]:
    """Extract the teacher-facing reply and normalized proposal_status."""
    text = (content or "").strip()
    leftover, payload = reply_payload_object(text)
    if payload is None:
        return leftover, None
    raw_status = payload.get("proposal_status")
    status = (
        raw_status.strip().lower()
        if isinstance(raw_status, str)
        and raw_status.strip().lower() in _PROPOSAL_STATUS_VALUES
        else None
    )
    # Once a payload is recognized never fall back to the raw JSON text: that
    # would leak proposal_status / conversation_focus to the teacher. The
    # caller substitutes a neutral sentence when the reply ends up empty.
    reply = str(payload.get("reply") or "").strip() or leftover
    return reply, status
