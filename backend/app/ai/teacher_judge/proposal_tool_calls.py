"""Per-call handling for the proposal tool loop: chat guards, error bookkeeping, execution (package-internal)."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.ai.teacher_judge._types import VLLMMetrics
from app.ai.teacher_judge.chat_transport import tool_arguments
from app.ai.teacher_judge.proposal_dispatch import (
    ToolTurnState,
    execute_checklist_tool,
)
from app.ai.teacher_judge.proposal_rules import normalized_title_key
from app.ai.teacher_judge.proposal_tools import (
    EDIT_CHECKLIST_ITEM_TOOL_NAME,
    GET_CHECKLIST_ITEM_TOOL_NAME,
    LIST_CHECKLIST_TOOL_NAME,
    PROPOSAL_TOOL_NAMES,
)

logger = logging.getLogger(__name__)


_UNKNOWN_TOOL_ERROR = (
    "工具「{name}」不存在。可用工具只有 list_checklist、get_checklist_item、"
    "create_checklist_item、edit_checklist_item；最終回覆請直接在 content 輸出 JSON，不要呼叫工具。"
)


_AWAITING_TEACHER_ERROR = (
    "此項目需要老師補充資訊；本輪不要再呼叫工具，請在 reply 詢問老師，"
    "proposal_status 設為 needs_information。"
)


_STAGED_REVISIT_ERROR = (
    "本輪提案已建立，不需要再列出、讀取或修改；請停止呼叫工具，"
    "下一則訊息不帶工具呼叫，直接在 content 依「最終回覆格式」輸出 JSON。"
)


@dataclass
class LoopState:
    """Mutable bookkeeping of one ``run_proposal_tool_loop`` call."""

    turn: ToolTurnState
    base_request: dict[str, Any]
    messages: list[dict[str, Any]]
    metrics: VLLMMetrics
    chat_mode: bool
    rubric_available: bool
    require_rubric: bool
    reply_format: Any
    main_completion_budget: int
    per_call_max_tokens: int
    final_content: str = ""
    reminder_count: int = 0
    forced_tool_choice: dict[str, Any] | None = None
    finalizer_repair_fingerprints: set[str] = field(default_factory=set)
    error_counts: dict[str, int] = field(default_factory=dict)
    error_fingerprints: dict[str, int] = field(default_factory=dict)
    pending_errors: dict[str, dict[str, Any]] = field(default_factory=dict)
    terminal_errors: set[str] = field(default_factory=set)
    error_reply_reminders: set[str] = field(default_factory=set)
    # Chat only: items that already asked for teacher input, and hallucinated
    # tool names. Repeating either ends the tool phase instead of looping.
    awaiting_teacher: dict[str, str] = field(default_factory=dict)
    unknown_tool_calls: int = 0
    staged_revisit: bool = False
    stop_tools: bool = False

    def remaining_tokens(self) -> int:
        return self.main_completion_budget - int(
            self.metrics.get("completion_tokens") or 0
        )


def function_choice(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name}}


def normalize_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_call in tool_calls:
        if not isinstance(raw_call, dict):
            continue
        call = dict(raw_call)
        call["id"] = str(call.get("id") or f"call_{uuid.uuid4().hex[:8]}")
        call["type"] = "function"
        normalized.append(call)
    return normalized


def _chat_guard(
    state: LoopState,
    tool_name: str,
    arguments: dict[str, Any],
    attempt_key: str,
) -> dict[str, Any] | None:
    """Chat-only calls that are answered without running a tool."""
    if not state.chat_mode:
        return None
    if tool_name not in PROPOSAL_TOOL_NAMES:
        state.unknown_tool_calls += 1
        logger.warning(
            "Teacher Judge ignored unknown tool call: %s",
            tool_name or "(missing name)",
        )
        return {
            "error": _UNKNOWN_TOOL_ERROR.format(name=tool_name),
            "reason_code": "unknown_tool",
            "retryable": False,
        }
    if state.awaiting_teacher.get(attempt_key) == json.dumps(
        arguments, ensure_ascii=False, sort_keys=True
    ):
        state.stop_tools = True
        return {
            "error": _AWAITING_TEACHER_ERROR,
            "reason_code": "teacher_input_required",
            "retryable": False,
        }
    staged_ops = state.turn.staged_ops
    if staged_ops and (
        tool_name == LIST_CHECKLIST_TOOL_NAME
        or (
            tool_name in {GET_CHECKLIST_ITEM_TOOL_NAME, EDIT_CHECKLIST_ITEM_TOOL_NAME}
            and str(arguments.get("id") or "")
            in {str(entry["item"].id) for entry in staged_ops}
        )
    ):
        # Re-reading or re-editing this turn's own proposals only loops
        # (and invites guessed edits); the staged result is final.
        state.staged_revisit = True
        state.stop_tools = True
        return {
            "error": _STAGED_REVISIT_ERROR,
            "reason_code": "already_staged",
            "retryable": False,
        }
    return None


def _invalid_call_result(
    state: LoopState,
    tool_name: str,
    arguments: dict[str, Any],
    attempt_key: str,
) -> dict[str, Any]:
    """Result for a call that is not executed: retries exhausted or unparsable arguments."""
    terminal = attempt_key in state.terminal_errors
    result: dict[str, Any] = {
        "error": "此項目的有限重試已結束。"
        if terminal
        else "工具 arguments 必須是有效的 JSON 物件。",
        "reason_code": "tool_retry_exhausted" if terminal else "tool_arguments_invalid",
        "retryable": not terminal,
        "repair_hint": "arguments 必須是符合該工具 schema 的 JSON 物件；修正 JSON 格式後重新呼叫。",
    }
    state.turn.tool_calls.append(
        {
            "tool": tool_name,
            "status": "error",
            "item_id": arguments.get("id"),
            "title": str(arguments.get("title") or arguments.get("id") or "未命名項目"),
            "reason": result["error"],
            "reason_code": result["reason_code"],
        }
    )
    return result


def _record_tool_error(
    state: LoopState,
    result: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    attempt_key: str,
) -> None:
    state.error_counts[attempt_key] = state.error_counts.get(attempt_key, 0) + 1
    fingerprint_issues = [
        {key: value for key, value in issue.items() if key != "item_id"}
        for issue in result.get("issues", [])
    ]
    fingerprint = json.dumps(
        [
            attempt_key,
            result.get("reason_code"),
            fingerprint_issues or result["error"],
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    state.error_fingerprints[fingerprint] = (
        state.error_fingerprints.get(fingerprint, 0) + 1
    )
    retryable = (
        bool(result.get("retryable", True))
        and state.error_fingerprints[fingerprint] < 2
        and state.error_counts[attempt_key] < 3
    )
    result.update({"retryable": retryable, "attempt": state.error_counts[attempt_key]})
    outcome = state.turn.tool_calls[-1]
    outcome.update(
        {
            "attempt_key": attempt_key,
            "attempt": state.error_counts[attempt_key],
            "retryable": retryable,
        }
    )
    state.pending_errors[attempt_key] = {
        **result,
        "tool": tool_name,
        "title": outcome.get("title"),
        "item_id": outcome.get("item_id"),
    }
    if result.get("teacher_input_required"):
        # Asking the teacher is the next step, not an AI retry.
        state.pending_errors.pop(attempt_key)
        if state.chat_mode:
            # A changed retry may still fix the item; a second gap
            # for the same item means only the teacher can.
            if attempt_key in state.awaiting_teacher:
                state.stop_tools = True
            state.awaiting_teacher[attempt_key] = json.dumps(
                arguments, ensure_ascii=False, sort_keys=True
            )
    if not retryable and not result.get("teacher_input_required"):
        state.terminal_errors.add(attempt_key)
    logger.warning(
        "Teacher Judge tool %s failed argument validation: %s",
        tool_name or "(missing name)",
        result["error"],
    )


def _record_tool_success(
    state: LoopState,
    result: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    attempt_key: str,
) -> None:
    tool_outcomes = state.turn.tool_calls
    if tool_name == LIST_CHECKLIST_TOOL_NAME:
        # The initial index read is a prerequisite, not a permanent
        # restriction on every subsequent model decision.
        state.base_request["tool_choice"] = "auto"
    write_accepted = bool(result.get("staged") or result.get("unchanged"))
    for key, error in list(state.pending_errors.items()):
        read_repaired = (
            tool_name in {LIST_CHECKLIST_TOOL_NAME, GET_CHECKLIST_ITEM_TOOL_NAME}
            and error.get("tool") == tool_name
        )
        precondition_repaired = (
            tool_name == GET_CHECKLIST_ITEM_TOOL_NAME
            and error.get("reason_code") == "checklist_item_not_read"
            and error.get("item_id") == arguments.get("id")
        )
        anonymous_repaired = (
            key == f"{tool_name}:"
            and error.get("reason_code") == "tool_arguments_invalid"
        )
        if (
            read_repaired
            or precondition_repaired
            or (
                write_accepted
                and (
                    key == attempt_key
                    or anonymous_repaired
                    or (
                        result.get("item_id")
                        and result.get("item_id") == error.get("item_id")
                    )
                )
            )
        ):
            state.pending_errors.pop(key)
            state.error_reply_reminders.discard(key)
            for outcome in tool_outcomes:
                if outcome.get("attempt_key") == key:
                    outcome["resolved"] = True
    if write_accepted:
        for outcome in tool_outcomes:
            if outcome.get("attempt_key") == attempt_key and outcome.get("reason"):
                outcome["resolved"] = True
    logger.debug(
        "Teacher Judge tool round executed: tool=%s staged=%d rejected=%d",
        tool_name,
        len(state.turn.staged_ops),
        len(state.turn.rejected_ops),
    )


def run_tool_call(state: LoopState, tool_call: dict[str, Any]) -> None:
    function = tool_call.get("function")
    function = function if isinstance(function, dict) else {}
    tool_name = str(function.get("name") or "")
    parsed_arguments = tool_arguments(function.get("arguments"))
    arguments = parsed_arguments or {}
    attempt_key = f"{tool_name}:{arguments.get('id') or normalized_title_key(arguments.get('title'))}"
    result = _chat_guard(state, tool_name, arguments, attempt_key)
    if result is None:
        if attempt_key in state.terminal_errors or parsed_arguments is None:
            result = _invalid_call_result(state, tool_name, arguments, attempt_key)
        else:
            result = execute_checklist_tool(tool_name, arguments, state.turn)
        if result.get("error"):
            _record_tool_error(state, result, tool_name, arguments, attempt_key)
        else:
            _record_tool_success(state, result, tool_name, arguments, attempt_key)
    # A chat guard answer is not a proposal outcome: it stays out of
    # tool_outcomes/pending errors so the teacher never sees a fake per-item failure.
    state.messages.append(
        {
            "role": "tool",
            "tool_call_id": str(tool_call["id"]),
            "content": json.dumps(result, ensure_ascii=False),
        },
    )
