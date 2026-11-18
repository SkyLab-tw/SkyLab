"""Multi-round tool loop that turns a chat turn into staged checklist proposals (package-internal)."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.adherence_check import ADHERENCE_MAX_TOKENS
from app.ai.teacher_judge import chat_transport
from app.ai.teacher_judge._types import VLLMMetrics
from app.ai.teacher_judge.chat_transport import (
    MAX_CHAT_COMPLETION_TOKENS,
    assistant_message,
    charge_missing_completion_usage,
    merge_vllm_metrics,
)
from app.ai.teacher_judge.check_plan_contract import TYPED_STEP_REPAIR_HINT
from app.ai.teacher_judge.proposal_dispatch import ToolTurnState
from app.ai.teacher_judge.proposal_replies import tool_error_reply
from app.ai.teacher_judge.proposal_rules import (
    finalizer_completion_blockers,
)
from app.ai.teacher_judge.proposal_tool_calls import (
    LoopState,
    function_choice,
    normalize_tool_calls,
    run_tool_call,
)
from app.ai.teacher_judge.proposal_tools import (
    CREATE_CHECKLIST_ITEM_TOOL_NAME,
    EDIT_CHECKLIST_ITEM_TOOL_NAME,
    GET_CHECKLIST_ITEM_TOOL_NAME,
    LIST_CHECKLIST_TOOL_NAME,
    build_proposal_tools,
)
from app.ai.teacher_judge.reply_payload import (
    contains_embedded_tool_call,
    parse_chat_reply_payload,
    reply_payload_object,
    structured_requirement_needs_candidate,
    structured_requirement_target_item,
)
from app.ai.teacher_judge.rubric_normalization import rubric_context_data
from app.ai.teacher_judge.schemas import TeacherJudgeRubricItem
from app.ai.utils import apply_thinking_control
from app.models.teacher_judge_template_command import TeacherJudgeTemplateCommand

logger = logging.getLogger(__name__)


_JSON_REPLY_REPAIR_INSTRUCTION = (
    "上一則回覆不是規定的 JSON。請把它的內容原意改寫成 <final_answer> 指定的 JSON 物件，只輸出 JSON。"
    "reply 保留原本要對老師說的話；proposal_status 依本輪工具結果：有 staged 提案為 ready，"
    "正在請老師補充資訊為 needs_information，平台不支援為 unsupported，其他為 none。"
)


_READY_REMINDER_INSTRUCTION = (
    "你在上一則回覆宣稱 Ready 或已建立提案，但沒有成功呼叫任何提案工具。"
    "若需求資料完整，請立即呼叫 create_checklist_item（新增）或 "
    "edit_checklist_item（修改既有項目，需先取得正式 ID）。"
    "若缺少老師才能補充的資訊，請將 proposal_status 改為 needs_information，"
    "並在 reply 逐項說明缺少的內容；不支援取證時改為 unsupported。"
    "不得在沒有提案的情況下宣稱已建立提案。"
)


_MAX_READY_REMINDERS = 2

_PLAIN_REPLY_INSTRUCTION = (
    "本次工具階段已結束，請停止呼叫工具，依已取得的資料輸出非空的 reply "
    "與 proposal_status。說明已建立的修改提案、需要補充的資訊或無須修改的依據。"
    "若尚未完成細查，明確說明未完成；沒有修改候選不代表檢查通過。"
)

_PENDING_ERROR_INSTRUCTION = "工具修改尚未成功；請依工具的 issues 與 repair_hint 修正參數後重新呼叫，不要宣稱完成或承諾背景重試。"


def _empty_metrics() -> VLLMMetrics:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "elapsed_seconds": 0.0,
        "tokens_per_second": 0.0,
        "usage_reported": True,
        "response_model": None,
    }


def _build_base_request(
    payload_data: dict[str, Any],
    *,
    machine_entries: list[dict[str, Any]] | None,
    chat_mode: bool,
    rubric_available: bool,
    require_rubric: bool,
) -> dict[str, Any]:
    base_request = dict(payload_data)
    base_request.pop("messages", None)
    if rubric_available:
        base_request["tools"] = build_proposal_tools(
            machine_entries,
            chat=chat_mode,
        )
        base_request["tool_choice"] = (
            function_choice(LIST_CHECKLIST_TOOL_NAME) if require_rubric else "auto"
        )
        base_request.pop("response_format", None)
    else:
        base_request.pop("tools", None)
        base_request.pop("tool_choice", None)
    return base_request


async def _call_round(state: LoopState, payload: dict[str, Any]) -> dict[str, Any]:
    """Send one request, fold its usage into the run and return the raw message."""
    request = apply_thinking_control(
        payload, chat_transport.settings.VLLM_ENABLE_THINKING
    )
    raw_message, round_metrics = await chat_transport.call_vllm_message(
        request, timeout=float(chat_transport.settings.VLLM_TIMEOUT)
    )
    round_metrics = charge_missing_completion_usage(
        round_metrics, int(payload["max_tokens"])
    )
    state.metrics = merge_vllm_metrics(state.metrics, round_metrics)
    return raw_message


async def _call_tool_round(state: LoopState) -> dict[str, Any]:
    payload = {**state.base_request, "messages": list(state.messages)}
    payload["max_tokens"] = min(state.per_call_max_tokens, state.remaining_tokens())
    if state.forced_tool_choice is not None:
        payload["tool_choice"] = state.forced_tool_choice
        state.forced_tool_choice = None
    return await _call_round(state, payload)


def _retry_pending_error(state: LoopState, content: str) -> bool:
    """Send the model back to a retryable tool error it answered with prose."""
    retry = next(
        (
            key
            for key, error in state.pending_errors.items()
            if error.get("retryable") and key not in state.error_reply_reminders
        ),
        None,
    )
    if retry is None:
        return False
    state.error_reply_reminders.add(retry)
    state.messages.extend(
        [
            {"role": "assistant", "content": content},
            {"role": "system", "content": _PENDING_ERROR_INSTRUCTION},
        ]
    )
    state.forced_tool_choice = function_choice(
        GET_CHECKLIST_ITEM_TOOL_NAME
        if state.pending_errors[retry].get("reason_code") == "checklist_item_not_read"
        else state.pending_errors[retry]["tool"]
    )
    return True


def _repair_finalizer_candidate(state: LoopState) -> bool:
    """Ask the Finalizer to fix a candidate that still fails typed Check Plan checks."""
    turn = state.turn
    blockers = finalizer_completion_blockers(
        turn.snapshot_items,
        turn.staged_ops,
        template_commands=turn.template_commands,
        machine_entries=turn.machine_entries,
    )
    repairable = [
        {
            "item_id": blocker.get("item_id"),
            "reason_code": blocker.get("reason_code"),
            "detail": blocker.get("detail"),
            "issues": blocker.get("issues", []),
        }
        for blocker in blockers
        if blocker.get("reason_code") == "check_plan_contract_invalid"
        and blocker.get("item_id")
    ]
    if not repairable:
        return False
    fingerprint = json.dumps(
        repairable,
        ensure_ascii=False,
        sort_keys=True,
    )
    if fingerprint in state.finalizer_repair_fingerprints:
        return False
    state.finalizer_repair_fingerprints.add(fingerprint)
    state.messages = [
        *state.messages,
        {"role": "assistant", "content": state.final_content},
        {
            "role": "system",
            "content": (
                "Finalizer 的 server-side candidate 尚未通過 typed "
                "Check Plan 驗證。不要只用 reply 宣稱完成；請立即呼叫 "
                "get_checklist_item 讀取尚未讀過的項目，再依下列問題呼叫 "
                "edit_checklist_item 修正對應欄位；保留已有效的步驟與已知路徑。"
                + TYPED_STEP_REPAIR_HINT
                + "\n"
                + json.dumps(
                    repairable,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            ),
        },
    ]
    state.forced_tool_choice = function_choice(
        GET_CHECKLIST_ITEM_TOOL_NAME
        if any(issue["item_id"] not in turn.read_ids for issue in repairable)
        else EDIT_CHECKLIST_ITEM_TOOL_NAME
    )
    return True


def _remind_unbacked_ready_claim(state: LoopState, claims_ready: bool) -> bool:
    """Push back on a Ready claim that no proposal tool call backs up."""
    if not (
        claims_ready
        and not state.turn.staged_ops
        and not state.turn.rejected_ops
        and state.rubric_available
        and not state.require_rubric
        and state.reminder_count < _MAX_READY_REMINDERS
    ):
        return False
    state.reminder_count += 1
    if state.reminder_count == 1:
        state.messages = [
            *state.messages,
            {"role": "assistant", "content": state.final_content},
            {"role": "system", "content": _READY_REMINDER_INSTRUCTION},
        ]
        return True
    # Second reminder: stop re-prompting prose and force the model
    # through the proposal tool channel so the loop converges even
    # for models that keep claiming Ready without calling tools.
    target_item_id = structured_requirement_target_item(state.final_content)
    state.forced_tool_choice = function_choice(
        GET_CHECKLIST_ITEM_TOOL_NAME
        if target_item_id
        else CREATE_CHECKLIST_ITEM_TOOL_NAME
    )
    logger.warning(
        "Teacher Judge ready claim without tools persisted; forcing tool_choice=%s",
        state.forced_tool_choice["function"]["name"],
    )
    return True


def _continue_after_plain_reply(state: LoopState, content: str) -> bool:
    """Handle a round without tool calls; True asks for another tool round."""
    if contains_embedded_tool_call(content):
        logger.warning(
            "Teacher Judge ignored a content-encoded tool call; native "
            "tool_calls is required"
        )
        state.final_content = ""
        return False
    state.final_content = content
    if _retry_pending_error(state, content):
        return True
    _, proposal_status = parse_chat_reply_payload(state.final_content)
    claims_ready = proposal_status == "ready" or structured_requirement_needs_candidate(
        state.final_content
    )
    if state.turn.finalizer and _repair_finalizer_candidate(state):
        return True
    return _remind_unbacked_ready_claim(state, claims_ready)


async def _force_plain_reply(state: LoopState) -> None:
    """The model kept calling tools: one plain reply round so the teacher gets an answer."""
    reply_payload = {
        **state.base_request,
        "messages": [
            *state.messages,
            {"role": "system", "content": _PLAIN_REPLY_INSTRUCTION},
        ],
    }
    reply_payload.pop("tools", None)
    reply_payload.pop("tool_choice", None)
    if state.reply_format:
        reply_payload["response_format"] = state.reply_format
    remaining_tokens = state.remaining_tokens()
    if remaining_tokens > 0 and not state.pending_errors:
        reply_payload["max_tokens"] = min(state.per_call_max_tokens, remaining_tokens)
        raw_message = await _call_round(state, reply_payload)
        state.final_content = str(assistant_message(raw_message).get("content") or "")


async def _restate_reply_as_json(state: LoopState) -> None:
    """Chat final reply came back as prose: one no-tool JSON-mode round restates it
    so proposal_status / focus are not lost."""
    remaining_tokens = state.remaining_tokens()
    if remaining_tokens <= 0:
        return
    repair_payload = {
        **state.base_request,
        "messages": [
            *state.messages,
            {"role": "assistant", "content": state.final_content},
            {"role": "system", "content": _JSON_REPLY_REPAIR_INSTRUCTION},
        ],
        "response_format": state.reply_format,
        "max_tokens": min(state.per_call_max_tokens, remaining_tokens),
    }
    repair_payload.pop("tools", None)
    repair_payload.pop("tool_choice", None)
    logger.warning("Teacher Judge chat final reply was not JSON; restating it")
    raw_message = await _call_round(state, repair_payload)
    repaired = str(assistant_message(raw_message).get("content") or "")
    if reply_payload_object(repaired)[1] is not None:
        state.final_content = repaired


async def run_proposal_tool_loop(
    payload_data: dict[str, Any],
    *,
    rubric_context: str,
    template_key: str,
    template_commands: list[TeacherJudgeTemplateCommand] | None,
    machine_entries: list[dict[str, Any]] | None,
    analysis_revision: int | None,
    rubric_available: bool,
    require_rubric: bool = False,
    ready_only: bool = True,
    finalizer: bool = False,
    completion_token_budget: int = MAX_CHAT_COMPLETION_TOKENS,
) -> tuple[
    str,
    VLLMMetrics,
    list[dict[str, Any]],
    list[tuple[TeacherJudgeRubricItem, dict[str, Any], str]],
    list[dict[str, Any]],
]:
    """Run bounded read/propose tool rounds, then return the final reply content.

    Proposal operations only stage candidates for this turn; the persisted
    rubric is never mutated here. The caller assembles ``updated_items`` from
    the staged entries, and ``tool_outcomes`` records every tool invocation
    for teacher-facing status display.
    """
    # Chat (and attachment-item) proposals; refine/Finalizer keep their loop.
    chat_mode = ready_only and not finalizer
    base_request = _build_base_request(
        payload_data,
        machine_entries=machine_entries,
        chat_mode=chat_mode,
        rubric_available=rubric_available,
        require_rubric=require_rubric,
    )
    state = LoopState(
        turn=ToolTurnState(
            snapshot_items=rubric_context_data(rubric_context).get("items"),
            analysis_revision=analysis_revision,
            template_key=template_key,
            template_commands=template_commands,
            ready_only=ready_only,
            read_ids=set(),
            staged_ops=[],
            rejected_ops=[],
            tool_calls=[],
            machine_entries=machine_entries,
            finalizer=finalizer,
        ),
        base_request=base_request,
        messages=list(payload_data.get("messages") or []),
        metrics=_empty_metrics(),
        chat_mode=chat_mode,
        rubric_available=rubric_available,
        require_rubric=require_rubric,
        # Tool rounds cannot use JSON mode; chat no-tool reply rounds restore it.
        reply_format=payload_data.get("response_format") if chat_mode else None,
        main_completion_budget=max(
            max(int(completion_token_budget), 0) - ADHERENCE_MAX_TOKENS * 2,
            0,
        ),
        per_call_max_tokens=max(int(base_request.get("max_tokens") or 0), 1),
    )
    turn = state.turn

    max_rounds = max(int(chat_transport.settings.VLLM_CHAT_MAX_TOOL_ROUNDS), 1)
    tools_exhausted = False
    for _ in range(max_rounds):
        if state.remaining_tokens() <= 0:
            break
        assistant = assistant_message(await _call_tool_round(state))
        content = str(assistant.get("content") or "")
        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            if _continue_after_plain_reply(state, content):
                continue
            break
        calls = normalize_tool_calls(tool_calls)
        if not calls:
            state.final_content = content
            break
        state.messages = [*state.messages, {**assistant, "content": content or None}]
        for call in calls:
            run_tool_call(state, call)
        if state.pending_errors and all(
            not error.get("retryable") for error in state.pending_errors.values()
        ):
            break
        if state.chat_mode and (state.stop_tools or state.unknown_tool_calls >= 2):
            state.stop_tools = True
            logger.warning(
                "Teacher Judge chat tool phase stopped: repeated_teacher_input=%s "
                "staged_revisit=%s unknown_tool_calls=%d staged=%d rejected=%d",
                bool(state.awaiting_teacher),
                state.staged_revisit,
                state.unknown_tool_calls,
                len(turn.staged_ops),
                len(turn.rejected_ops),
            )
            break
    else:
        tools_exhausted = True
        logger.warning(
            "Teacher Judge tool round budget (%s) exhausted with staged=%d "
            "rejected=%d failed=%d",
            max_rounds,
            len(turn.staged_ops),
            len(turn.rejected_ops),
            len(state.pending_errors),
        )
    if tools_exhausted or state.stop_tools:
        await _force_plain_reply(state)
    elif (
        state.reply_format
        and state.final_content.strip()
        and not state.pending_errors
        and reply_payload_object(state.final_content)[1] is None
    ):
        await _restate_reply_as_json(state)

    if state.pending_errors:
        state.final_content = json.dumps(
            {
                "reply": tool_error_reply(
                    list(state.pending_errors.values()), staged=bool(turn.staged_ops)
                ),
                "proposal_status": "ready" if turn.staged_ops else "none",
            },
            ensure_ascii=False,
        )
    return (
        state.final_content,
        state.metrics,
        turn.staged_ops,
        turn.rejected_ops,
        turn.tool_calls,
    )
