"""Multi-round tool loop that turns a chat turn into staged checklist proposals (package-internal)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.ai.adherence_check import ADHERENCE_MAX_TOKENS
from app.ai.teacher_judge import chat_transport
from app.ai.teacher_judge._types import VLLMMetrics
from app.ai.teacher_judge.chat_transport import (
    MAX_CHAT_COMPLETION_TOKENS,
    assistant_message,
    charge_missing_completion_usage,
    merge_vllm_metrics,
    tool_arguments,
)
from app.ai.teacher_judge.check_plan_contract import TYPED_STEP_REPAIR_HINT
from app.ai.teacher_judge.proposal_dispatch import (
    ToolTurnState,
    execute_checklist_tool,
)
from app.ai.teacher_judge.proposal_replies import tool_error_reply
from app.ai.teacher_judge.proposal_rules import (
    finalizer_completion_blockers,
    normalized_title_key,
)
from app.ai.teacher_judge.proposal_tools import (
    CREATE_CHECKLIST_ITEM_TOOL_NAME,
    EDIT_CHECKLIST_ITEM_TOOL_NAME,
    GET_CHECKLIST_ITEM_TOOL_NAME,
    LIST_CHECKLIST_TOOL_NAME,
    PROPOSAL_TOOL_NAMES,
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
    "直接依 <final_answer> 輸出 JSON。"
)


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
    snapshot_items = rubric_context_data(rubric_context).get("items")
    read_ids: set[str] = set()
    staged_ops: list[dict[str, Any]] = []
    rejected_ops: list[tuple[TeacherJudgeRubricItem, dict[str, Any], str]] = []
    tool_outcomes: list[dict[str, Any]] = []
    turn = ToolTurnState(
        snapshot_items=snapshot_items,
        analysis_revision=analysis_revision,
        template_key=template_key,
        template_commands=template_commands,
        ready_only=ready_only,
        read_ids=read_ids,
        staged_ops=staged_ops,
        rejected_ops=rejected_ops,
        tool_calls=tool_outcomes,
        machine_entries=machine_entries,
        finalizer=finalizer,
    )

    # Chat (and attachment-item) proposals; refine/Finalizer keep their loop.
    chat_mode = ready_only and not finalizer
    # Tool rounds cannot use JSON mode; chat no-tool reply rounds restore it.
    reply_format = payload_data.get("response_format") if chat_mode else None
    base_request = dict(payload_data)
    base_request.pop("messages", None)
    if rubric_available:
        base_request["tools"] = build_proposal_tools(
            machine_entries,
            chat=chat_mode,
        )
        base_request["tool_choice"] = (
            {"type": "function", "function": {"name": LIST_CHECKLIST_TOOL_NAME}}
            if require_rubric
            else "auto"
        )
        base_request.pop("response_format", None)
    else:
        base_request.pop("tools", None)
        base_request.pop("tool_choice", None)

    messages = list(payload_data.get("messages") or [])
    metrics: VLLMMetrics = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "elapsed_seconds": 0.0,
        "tokens_per_second": 0.0,
        "usage_reported": True,
        "response_model": None,
    }

    max_rounds = max(int(chat_transport.settings.VLLM_CHAT_MAX_TOOL_ROUNDS), 1)
    completion_token_budget = max(int(completion_token_budget), 0)
    main_completion_budget = max(
        completion_token_budget - ADHERENCE_MAX_TOKENS * 2,
        0,
    )
    per_call_max_tokens = max(int(base_request.get("max_tokens") or 0), 1)
    final_content = ""
    reminder_count = 0
    forced_tool_choice: dict[str, Any] | None = None
    finalizer_repair_fingerprints: set[str] = set()
    error_counts: dict[str, int] = {}
    error_fingerprints: dict[str, int] = {}
    pending_errors: dict[str, dict[str, Any]] = {}
    terminal_errors: set[str] = set()
    error_reply_reminders: set[str] = set()
    # Chat only: items that already asked for teacher input, and hallucinated
    # tool names. Repeating either ends the tool phase instead of looping.
    awaiting_teacher: dict[str, str] = {}
    unknown_tool_calls = 0
    staged_revisit = False
    stop_tools = False
    tools_exhausted = False
    for _ in range(max_rounds):
        remaining_tokens = main_completion_budget - int(
            metrics.get("completion_tokens") or 0
        )
        if remaining_tokens <= 0:
            break
        round_payload = {**base_request, "messages": list(messages)}
        round_payload["max_tokens"] = min(per_call_max_tokens, remaining_tokens)
        if forced_tool_choice is not None:
            round_payload["tool_choice"] = forced_tool_choice
            forced_tool_choice = None
        request = apply_thinking_control(
            round_payload, chat_transport.settings.VLLM_ENABLE_THINKING
        )
        raw_message, round_metrics = await chat_transport.call_vllm_message(
            request, timeout=float(chat_transport.settings.VLLM_TIMEOUT)
        )
        round_metrics = charge_missing_completion_usage(
            round_metrics, int(round_payload["max_tokens"])
        )
        metrics = merge_vllm_metrics(metrics, round_metrics)
        assistant = assistant_message(raw_message)
        cleaned_content = str(assistant.get("content") or "")
        assistant = {**assistant, "content": cleaned_content or None}
        tool_calls = assistant.get("tool_calls")
        if not tool_calls:
            if contains_embedded_tool_call(cleaned_content):
                logger.warning(
                    "Teacher Judge ignored a content-encoded tool call; native "
                    "tool_calls is required"
                )
                final_content = ""
                break
            final_content = cleaned_content
            retry = next(
                (
                    key
                    for key, error in pending_errors.items()
                    if error.get("retryable") and key not in error_reply_reminders
                ),
                None,
            )
            if retry is not None:
                error_reply_reminders.add(retry)
                messages.extend(
                    [
                        {"role": "assistant", "content": cleaned_content},
                        {
                            "role": "system",
                            "content": "工具修改尚未成功；請依工具的 issues 與 repair_hint 修正參數後重新呼叫，不要宣稱完成或承諾背景重試。",
                        },
                    ]
                )
                forced_tool_choice = {
                    "type": "function",
                    "function": {
                        "name": (
                            GET_CHECKLIST_ITEM_TOOL_NAME
                            if pending_errors[retry].get("reason_code")
                            == "checklist_item_not_read"
                            else pending_errors[retry]["tool"]
                        )
                    },
                }
                continue
            _, proposal_status = parse_chat_reply_payload(final_content)
            claims_ready = (
                proposal_status == "ready"
                or structured_requirement_needs_candidate(final_content)
            )
            if finalizer:
                blockers = finalizer_completion_blockers(
                    snapshot_items,
                    staged_ops,
                    template_commands=template_commands,
                    machine_entries=machine_entries,
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
                if repairable:
                    fingerprint = json.dumps(
                        repairable,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    if fingerprint not in finalizer_repair_fingerprints:
                        finalizer_repair_fingerprints.add(fingerprint)
                        messages = [
                            *messages,
                            {"role": "assistant", "content": final_content},
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
                        forced_tool_choice = {
                            "type": "function",
                            "function": {
                                "name": (
                                    GET_CHECKLIST_ITEM_TOOL_NAME
                                    if any(
                                        issue["item_id"] not in read_ids
                                        for issue in repairable
                                    )
                                    else EDIT_CHECKLIST_ITEM_TOOL_NAME
                                )
                            },
                        }
                        continue
            if (
                claims_ready
                and not staged_ops
                and not rejected_ops
                and rubric_available
                and not require_rubric
                and reminder_count < _MAX_READY_REMINDERS
            ):
                reminder_count += 1
                if reminder_count == 1:
                    messages = [
                        *messages,
                        {"role": "assistant", "content": final_content},
                        {"role": "system", "content": _READY_REMINDER_INSTRUCTION},
                    ]
                    continue
                # Second reminder: stop re-prompting prose and force the model
                # through the proposal tool channel so the loop converges even
                # for models that keep claiming Ready without calling tools.
                target_item_id = structured_requirement_target_item(final_content)
                forced_tool_choice = {
                    "type": "function",
                    "function": {
                        "name": (
                            GET_CHECKLIST_ITEM_TOOL_NAME
                            if target_item_id
                            else CREATE_CHECKLIST_ITEM_TOOL_NAME
                        )
                    },
                }
                logger.warning(
                    "Teacher Judge ready claim without tools persisted; "
                    "forcing tool_choice=%s",
                    forced_tool_choice["function"]["name"],
                )
                continue
            break

        normalized_calls: list[dict[str, Any]] = []
        for raw_call in tool_calls:
            if not isinstance(raw_call, dict):
                continue
            call = dict(raw_call)
            call["id"] = str(call.get("id") or f"call_{uuid.uuid4().hex[:8]}")
            call["type"] = "function"
            normalized_calls.append(call)
        if not normalized_calls:
            final_content = str(assistant.get("content") or "")
            break
        messages = [*messages, assistant]
        for tool_call in normalized_calls:
            function = tool_call.get("function")
            function = function if isinstance(function, dict) else {}
            tool_name = str(function.get("name") or "")
            parsed_arguments = tool_arguments(function.get("arguments"))
            arguments = parsed_arguments or {}
            attempt_key = f"{tool_name}:{arguments.get('id') or normalized_title_key(arguments.get('title'))}"
            chat_block = None
            if chat_mode and tool_name not in PROPOSAL_TOOL_NAMES:
                unknown_tool_calls += 1
                logger.warning(
                    "Teacher Judge ignored unknown tool call: %s",
                    tool_name or "(missing name)",
                )
                chat_block = {
                    "error": _UNKNOWN_TOOL_ERROR.format(name=tool_name),
                    "reason_code": "unknown_tool",
                    "retryable": False,
                }
            elif chat_mode and awaiting_teacher.get(attempt_key) == json.dumps(
                arguments, ensure_ascii=False, sort_keys=True
            ):
                stop_tools = True
                chat_block = {
                    "error": _AWAITING_TEACHER_ERROR,
                    "reason_code": "teacher_input_required",
                    "retryable": False,
                }
            elif (
                chat_mode
                and staged_ops
                and (
                    tool_name == LIST_CHECKLIST_TOOL_NAME
                    or (
                        tool_name
                        in {GET_CHECKLIST_ITEM_TOOL_NAME, EDIT_CHECKLIST_ITEM_TOOL_NAME}
                        and str(arguments.get("id") or "")
                        in {str(entry["item"].id) for entry in staged_ops}
                    )
                )
            ):
                # Re-reading or re-editing this turn's own proposals only loops
                # (and invites guessed edits); the staged result is final.
                staged_revisit = True
                stop_tools = True
                chat_block = {
                    "error": _STAGED_REVISIT_ERROR,
                    "reason_code": "already_staged",
                    "retryable": False,
                }
            if chat_block is not None:
                # Not a proposal outcome: keep it out of tool_outcomes/pending
                # errors so the teacher never sees a fake per-item failure.
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tool_call["id"]),
                        "content": json.dumps(chat_block, ensure_ascii=False),
                    },
                )
                continue
            if attempt_key in terminal_errors or parsed_arguments is None:
                result = {
                    "error": "此項目的有限重試已結束。"
                    if attempt_key in terminal_errors
                    else "工具 arguments 必須是有效的 JSON 物件。",
                    "reason_code": "tool_retry_exhausted"
                    if attempt_key in terminal_errors
                    else "tool_arguments_invalid",
                    "retryable": attempt_key not in terminal_errors,
                    "repair_hint": "arguments 必須是符合該工具 schema 的 JSON 物件；修正 JSON 格式後重新呼叫。",
                }
                tool_outcomes.append(
                    {
                        "tool": tool_name,
                        "status": "error",
                        "item_id": arguments.get("id"),
                        "title": str(
                            arguments.get("title")
                            or arguments.get("id")
                            or "未命名項目"
                        ),
                        "reason": result["error"],
                        "reason_code": result["reason_code"],
                    }
                )
            else:
                result = execute_checklist_tool(tool_name, arguments, turn)
            if isinstance(result, dict) and result.get("error"):
                error_counts[attempt_key] = error_counts.get(attempt_key, 0) + 1
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
                error_fingerprints[fingerprint] = (
                    error_fingerprints.get(fingerprint, 0) + 1
                )
                retryable = (
                    bool(result.get("retryable", True))
                    and error_fingerprints[fingerprint] < 2
                    and error_counts[attempt_key] < 3
                )
                result.update(
                    {"retryable": retryable, "attempt": error_counts[attempt_key]}
                )
                outcome = tool_outcomes[-1]
                outcome.update(
                    {
                        "attempt_key": attempt_key,
                        "attempt": error_counts[attempt_key],
                        "retryable": retryable,
                    }
                )
                pending_errors[attempt_key] = {
                    **result,
                    "tool": tool_name,
                    "title": outcome.get("title"),
                    "item_id": outcome.get("item_id"),
                }
                if result.get("teacher_input_required"):
                    # Asking the teacher is the next step, not an AI retry.
                    pending_errors.pop(attempt_key)
                    if chat_mode:
                        # A changed retry may still fix the item; a second gap
                        # for the same item means only the teacher can.
                        if attempt_key in awaiting_teacher:
                            stop_tools = True
                        awaiting_teacher[attempt_key] = json.dumps(
                            arguments, ensure_ascii=False, sort_keys=True
                        )
                if not retryable and not result.get("teacher_input_required"):
                    terminal_errors.add(attempt_key)
                logger.warning(
                    "Teacher Judge tool %s failed argument validation: %s",
                    tool_name or "(missing name)",
                    result["error"],
                )
            else:
                if tool_name == LIST_CHECKLIST_TOOL_NAME:
                    # The initial index read is a prerequisite, not a permanent
                    # restriction on every subsequent model decision.
                    base_request["tool_choice"] = "auto"
                write_accepted = bool(result.get("staged") or result.get("unchanged"))
                for key, error in list(pending_errors.items()):
                    read_repaired = (
                        tool_name
                        in {LIST_CHECKLIST_TOOL_NAME, GET_CHECKLIST_ITEM_TOOL_NAME}
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
                        pending_errors.pop(key)
                        error_reply_reminders.discard(key)
                        for outcome in tool_outcomes:
                            if outcome.get("attempt_key") == key:
                                outcome["resolved"] = True
                if write_accepted:
                    for outcome in tool_outcomes:
                        if outcome.get("attempt_key") == attempt_key and outcome.get(
                            "reason"
                        ):
                            outcome["resolved"] = True
                logger.debug(
                    "Teacher Judge tool round executed: tool=%s staged=%d rejected=%d",
                    tool_name,
                    len(staged_ops),
                    len(rejected_ops),
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(tool_call["id"]),
                    "content": json.dumps(result, ensure_ascii=False),
                },
            )
        if pending_errors and all(
            not error.get("retryable") for error in pending_errors.values()
        ):
            break
        if chat_mode and (stop_tools or unknown_tool_calls >= 2):
            stop_tools = True
            logger.warning(
                "Teacher Judge chat tool phase stopped: repeated_teacher_input=%s "
                "staged_revisit=%s unknown_tool_calls=%d staged=%d rejected=%d",
                bool(awaiting_teacher),
                staged_revisit,
                unknown_tool_calls,
                len(staged_ops),
                len(rejected_ops),
            )
            break
    else:
        tools_exhausted = True
        logger.warning(
            "Teacher Judge tool round budget (%s) exhausted with staged=%d "
            "rejected=%d failed=%d",
            max_rounds,
            len(staged_ops),
            len(rejected_ops),
            len(pending_errors),
        )
    if tools_exhausted or stop_tools:
        # The model kept calling tools; force one plain reply round without
        # tools so the teacher always gets an answer.
        reply_payload = {
            **base_request,
            "messages": [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "本次工具階段已結束，請停止呼叫工具，依已取得的資料輸出非空的 reply "
                        "與 proposal_status。說明已建立的修改提案、需要補充的資訊或無須修改的依據。"
                        "若尚未完成細查，明確說明未完成；沒有修改候選不代表檢查通過。"
                    ),
                },
            ],
        }
        reply_payload.pop("tools", None)
        reply_payload.pop("tool_choice", None)
        if reply_format:
            reply_payload["response_format"] = reply_format
        remaining_tokens = main_completion_budget - int(
            metrics.get("completion_tokens") or 0
        )
        if remaining_tokens > 0 and not pending_errors:
            reply_payload["max_tokens"] = min(per_call_max_tokens, remaining_tokens)
            request = apply_thinking_control(
                reply_payload, chat_transport.settings.VLLM_ENABLE_THINKING
            )
            raw_message, round_metrics = await chat_transport.call_vllm_message(
                request, timeout=float(chat_transport.settings.VLLM_TIMEOUT)
            )
            round_metrics = charge_missing_completion_usage(
                round_metrics, int(reply_payload["max_tokens"])
            )
            metrics = merge_vllm_metrics(metrics, round_metrics)
            final_content = str(assistant_message(raw_message).get("content") or "")
    elif (
        reply_format
        and final_content.strip()
        and not pending_errors
        and reply_payload_object(final_content)[1] is None
    ):
        # Chat final reply came back as prose: one no-tool JSON-mode round
        # restates it so proposal_status / focus are not lost.
        remaining_tokens = main_completion_budget - int(
            metrics.get("completion_tokens") or 0
        )
        if remaining_tokens > 0:
            repair_payload = {
                **base_request,
                "messages": [
                    *messages,
                    {"role": "assistant", "content": final_content},
                    {"role": "system", "content": _JSON_REPLY_REPAIR_INSTRUCTION},
                ],
                "response_format": reply_format,
                "max_tokens": min(per_call_max_tokens, remaining_tokens),
            }
            repair_payload.pop("tools", None)
            repair_payload.pop("tool_choice", None)
            logger.warning("Teacher Judge chat final reply was not JSON; restating it")
            raw_message, round_metrics = await chat_transport.call_vllm_message(
                apply_thinking_control(
                    repair_payload, chat_transport.settings.VLLM_ENABLE_THINKING
                ),
                timeout=float(chat_transport.settings.VLLM_TIMEOUT),
            )
            round_metrics = charge_missing_completion_usage(
                round_metrics, int(repair_payload["max_tokens"])
            )
            metrics = merge_vllm_metrics(metrics, round_metrics)
            repaired = str(assistant_message(raw_message).get("content") or "")
            if reply_payload_object(repaired)[1] is not None:
                final_content = repaired

    if pending_errors:
        final_content = json.dumps(
            {
                "reply": tool_error_reply(
                    list(pending_errors.values()), staged=bool(staged_ops)
                ),
                "proposal_status": "ready" if staged_ops else "none",
            },
            ensure_ascii=False,
        )
    return final_content, metrics, staged_ops, rejected_ops, tool_outcomes
