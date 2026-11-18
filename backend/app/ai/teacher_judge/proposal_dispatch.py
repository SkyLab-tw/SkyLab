"""Execution of checklist proposal tools against per-turn staged state (package-internal)."""

from __future__ import annotations

from typing import Any

from app.ai.teacher_judge.check_plan_contract import (
    reconcile_finalizer_locations,
    typed_step_issues,
)
from app.ai.teacher_judge.proposal_rules import (
    PROPOSAL_COMPARE_FIELDS,
    candidate_contract_error,
    canonicalize_proposal_machine_fields,
    contract_tool_error,
    duplicate_title_owner,
    finalizer_completion_blockers,
    mint_proposal_item_id,
    proposal_candidate_rejection,
    proposal_item_value,
)
from app.ai.teacher_judge.proposal_tools import (
    CREATE_CHECKLIST_ITEM_TOOL_NAME,
    EDIT_CHECKLIST_ITEM_TOOL_NAME,
    GET_CHECKLIST_ITEM_TOOL_NAME,
    LIST_CHECKLIST_TOOL_NAME,
    PROPOSAL_FILL_PROPERTIES,
)
from app.ai.teacher_judge.rubric_normalization import normalize_rubric_items
from app.ai.teacher_judge.schemas import TeacherJudgeRubricItem
from app.models.teacher_judge_template_command import TeacherJudgeTemplateCommand


def execute_checklist_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    snapshot_items: Any,
    analysis_revision: int | None,
    template_key: str,
    template_commands: list[TeacherJudgeTemplateCommand] | None,
    machine_entries: list[dict[str, Any]] | None = None,
    ready_only: bool,
    finalizer: bool = False,
    read_ids: set[str],
    staged_ops: list[dict[str, Any]],
    rejected_ops: list[tuple[TeacherJudgeRubricItem, dict[str, Any], str]],
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Record early schema/argument errors as well as normalized rejections."""
    before = len(tool_calls)
    result = _dispatch_checklist_tool(
        name,
        arguments,
        snapshot_items=snapshot_items,
        analysis_revision=analysis_revision,
        template_key=template_key,
        template_commands=template_commands,
        machine_entries=machine_entries,
        ready_only=ready_only,
        finalizer=finalizer,
        read_ids=read_ids,
        staged_ops=staged_ops,
        rejected_ops=rejected_ops,
        tool_calls=tool_calls,
    )
    if result.get("error"):
        recorded = tool_calls[-1] if len(tool_calls) > before else {}
        item_id = str(
            result.get("item_id")
            or arguments.get("id")
            or recorded.get("item_id")
            or ""
        )
        snapshot = snapshot_items if isinstance(snapshot_items, list) else []
        current = next(
            (
                item
                for item in snapshot
                if isinstance(item, dict) and item.get("id") == item_id
            ),
            {},
        )
        title = str(
            arguments.get("title")
            or current.get("title")
            or recorded.get("title")
            or ""
        ).strip()
        error = str(result["error"])
        if title and title not in error:
            result["error"] = f"「{title}」：{error}"
        result.setdefault("reason_code", "tool_arguments_invalid")
        result.setdefault("retryable", True)
        result.setdefault("repair_hint", str(result["error"]))
        outcome = {
            "tool": name,
            "status": "error",
            "item_id": item_id or None,
            "title": str(
                arguments.get("title")
                or current.get("title")
                or recorded.get("title")
                or item_id
                or "未命名項目"
            ),
            "reason": str(result["error"]),
            "reason_code": result["reason_code"],
            "issues": result.get("issues", []),
        }
        if len(tool_calls) == before:
            tool_calls.append(outcome)
        else:
            tool_calls[-1].update(
                {key: value for key, value in outcome.items() if key != "status"}
            )
    return result


def _dispatch_checklist_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    snapshot_items: Any,
    analysis_revision: int | None,
    template_key: str,
    template_commands: list[TeacherJudgeTemplateCommand] | None,
    machine_entries: list[dict[str, Any]] | None = None,
    ready_only: bool,
    finalizer: bool = False,
    read_ids: set[str],
    staged_ops: list[dict[str, Any]],
    rejected_ops: list[tuple[TeacherJudgeRubricItem, dict[str, Any], str]],
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Dispatch one checklist tool call; stage proposal candidates server-side.

    Every invocation appends a teacher-facing outcome entry to ``tool_calls``
    so the frontend can render what the tools actually did, independent of
    the model's prose reply.
    """
    snapshot = snapshot_items if isinstance(snapshot_items, list) else []
    current_raw_by_id = {
        str(item.get("id") or "").strip(): item
        for item in snapshot
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    candidate_items_by_id = {
        **current_raw_by_id,
        **{
            entry["item"].id: entry["item"].model_dump(mode="json")
            for entry in staged_ops
        },
    }

    if name == LIST_CHECKLIST_TOOL_NAME:
        if arguments:
            return {"error": "不支援的工具或參數"}
        listing = [
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "detectable": str(item.get("detectable") or "manual"),
                "judgement_mode": str(item.get("judgement_mode") or "ai"),
            }
            for item in candidate_items_by_id.values()
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ]
        tool_calls.append({"tool": name, "status": "read", "item_count": len(listing)})
        return {"analysis_revision": analysis_revision, "items": listing}

    if name == GET_CHECKLIST_ITEM_TOOL_NAME:
        if set(arguments) - {"id"}:
            return {"error": "不支援的工具或參數"}
        item_id = str(arguments.get("id") or "").strip()
        if not item_id:
            return {"error": "請提供要查詢的項目 ID。"}
        current_raw = candidate_items_by_id.get(item_id)
        if current_raw is None:
            return {
                "error": (
                    f"找不到檢查項目 {item_id}；"
                    "請先呼叫 list_checklist 取得有效的項目 ID。"
                ),
            }
        read_ids.add(item_id)
        tool_calls.append(
            {
                "tool": name,
                "status": "read",
                "item_id": item_id,
                "title": str(current_raw.get("title") or ""),
            },
        )
        blockers = finalizer_completion_blockers(
            [current_raw],
            [],
            template_commands=template_commands,
            machine_entries=machine_entries,
        )
        return {
            "analysis_revision": analysis_revision,
            "item": current_raw,
            "execution_readiness": {"ready": not blockers, "blockers": blockers},
        }

    if name == CREATE_CHECKLIST_ITEM_TOOL_NAME:
        if set(arguments) - set(PROPOSAL_FILL_PROPERTIES):
            return {"error": "不支援的工具或參數"}
        title = str(arguments.get("title") or "").strip()
        if not title:
            return {"error": "title 不可空白；請重新呼叫 create_checklist_item。"}
        duplicate_owner = duplicate_title_owner(title, snapshot, staged_ops)
        if duplicate_owner is not None:
            existing_id, existing_title = duplicate_owner
            tool_calls.append(
                {
                    "tool": name,
                    "status": "duplicate",
                    "item_id": existing_id,
                    "title": title,
                },
            )
            return {
                "error": (
                    f"檢查表已有同標題項目 id={existing_id}「{existing_title}」，"
                    "未建立重複的新增提案；"
                    f"若要調整該項目內容，請改呼叫 edit_checklist_item 並提供 id={existing_id}；"
                    "若確實是另一個不同項目，請改用更精確的標題後重新呼叫 create_checklist_item。"
                ),
            }
        existing_ids = set(current_raw_by_id) | {
            entry["item"].id for entry in staged_ops
        }
        item_id = mint_proposal_item_id(existing_ids)
        # Chat tools hide detectability: a chat create is a complete (auto)
        # request, and normalization still downgrades it when steps have gaps.
        chat_defaults = {"detectable": "auto"} if ready_only and not finalizer else {}
        try:
            raw_item = canonicalize_proposal_machine_fields(
                {**chat_defaults, **arguments, "id": item_id, "title": title},
                machine_entries,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        if "check_steps" in raw_item:
            issues = typed_step_issues(raw_item["check_steps"], item_id=item_id)
            if issues:
                return contract_tool_error(issues, item_id=item_id)
        candidate_list = normalize_rubric_items(
            [raw_item],
            template_key=template_key,
            template_commands=template_commands,
        )
        if not candidate_list:
            return {"error": "無法解析 create_checklist_item 的欄位，請重新呼叫。"}
        candidate = candidate_list[0]
        contract_error = candidate_contract_error(
            candidate,
            other_items=list(candidate_items_by_id.values()),
        )
        if contract_error:
            return contract_error
        rejection = proposal_candidate_rejection(
            candidate,
            raw_item,
            capability_declared=True,
            ready_only=ready_only,
            template_commands=template_commands,
        )
        if rejection is not None:
            rejected_ops.append((candidate, raw_item, rejection))
            tool_calls.append(
                {
                    "tool": name,
                    "status": "rejected",
                    "item_id": item_id,
                    "title": title,
                    "reason": rejection,
                },
            )
            return {
                "error": rejection,
                "reason_code": "information_missing"
                if candidate.missing_information
                else "proposal_rejected",
                "teacher_input_required": bool(candidate.missing_information),
                "retryable": not bool(candidate.missing_information),
            }
        staged_ops.append({"item": candidate, "operation": "add", "raw": raw_item})
        tool_calls.append(
            {
                "tool": name,
                "status": "staged",
                "operation": "add",
                "item_id": item_id,
                "title": title,
                "detectable": candidate.detectable,
                "judgement_mode": candidate.judgement_mode,
            },
        )
        return {
            "staged": "add",
            "item_id": item_id,
            "title": title,
            "detectable": candidate.detectable,
            "judgement_mode": candidate.judgement_mode,
            "note": "新增提案候選已建立；老師確認套用後才會寫入檢查表。",
        }

    if name == EDIT_CHECKLIST_ITEM_TOOL_NAME:
        if set(arguments) - {"id", *PROPOSAL_FILL_PROPERTIES}:
            return {"error": "不支援的工具或參數"}
        item_id = str(arguments.get("id") or "").strip()
        if not item_id:
            return {"error": "請提供要修改的項目 ID。"}
        current_raw = candidate_items_by_id.get(item_id)
        if current_raw is None:
            return {
                "error": (
                    f"找不到檢查項目 {item_id}；"
                    "請先呼叫 list_checklist 取得有效的項目 ID。"
                ),
            }
        if item_id not in read_ids:
            return {
                "error": (
                    f"修改 {item_id} 前，必須呼叫 get_checklist_item 讀取完整步驟與 execution_readiness；清單摘要不含路徑。"
                ),
                "reason_code": "checklist_item_not_read",
                "teacher_input_required": False,
                "retryable": True,
            }
        patch = {
            key: arguments[key]
            for key in arguments
            if key in PROPOSAL_COMPARE_FIELDS and key != "id"
        }
        if not patch:
            return {
                "staged": None,
                "item_id": item_id,
                "note": "沒有提供任何變更欄位，未建立修改提案。",
            }
        if ready_only and not finalizer:
            # Chat edits target a complete item; recorded gaps are kept unless
            # the model clears them, so normalization still downgrades it.
            patch = {"detectable": "auto", **patch}
        try:
            raw_candidate = canonicalize_proposal_machine_fields(
                {**current_raw, **patch}, machine_entries
            )
        except ValueError as exc:
            return {"error": str(exc)}
        if "check_steps" in arguments:
            issues = typed_step_issues(
                raw_candidate.get("check_steps"), item_id=item_id
            )
            if issues:
                return contract_tool_error(issues, item_id=item_id)
        if finalizer:
            raw_candidate, issues = reconcile_finalizer_locations(
                current_raw, raw_candidate
            )
            if issues:
                return {
                    **contract_tool_error(issues, item_id=item_id),
                    "teacher_input_required": False,
                    "repair_hint": "保留此項目既有的絕對路徑與全部步驟。若未改變檢查內容，可省略修改；不要新增 cwd。",
                    "current_check_steps": current_raw.get("check_steps"),
                }
        candidate_list = normalize_rubric_items(
            [raw_candidate],
            template_key=template_key,
            template_commands=template_commands,
        )
        if not candidate_list:
            return {"error": "無法解析 edit_checklist_item 的欄位，請重新呼叫。"}
        candidate = candidate_list[0]
        contract_error = candidate_contract_error(
            candidate,
            other_items=list(candidate_items_by_id.values()),
        )
        if contract_error:
            return contract_error
        current_normalized = normalize_rubric_items(
            [current_raw_by_id[item_id]] if item_id in current_raw_by_id else [],
            template_key=template_key,
            template_commands=template_commands,
            strip_auto_fallback=False,
        )
        if current_normalized and proposal_item_value(
            current_normalized[0].model_dump()
        ) == proposal_item_value(candidate.model_dump()):
            # Returning to the saved contract also supersedes an earlier
            # staged edit for this item; otherwise an old downgrade survives.
            staged_ops[:] = [
                entry for entry in staged_ops if entry["item"].id != item_id
            ]
            tool_calls.append(
                {
                    "tool": name,
                    "status": "no_change",
                    "item_id": item_id,
                    "title": str(candidate.title),
                },
            )
            return {
                "staged": None,
                "item_id": item_id,
                "unchanged": True,
                "note": "內容與目前檢查表相同，未建立修改提案。",
            }
        rejection = proposal_candidate_rejection(
            candidate,
            raw_candidate,
            capability_declared="detectable" in arguments,
            ready_only=ready_only,
            template_commands=template_commands,
        )
        if rejection is not None:
            rejected_ops.append((candidate, raw_candidate, rejection))
            tool_calls.append(
                {
                    "tool": name,
                    "status": "rejected",
                    "item_id": item_id,
                    "title": str(candidate.title),
                    "reason": rejection,
                },
            )
            return {
                "error": rejection,
                "reason_code": "information_missing"
                if candidate.missing_information
                else "proposal_rejected",
                "teacher_input_required": bool(candidate.missing_information),
                "retryable": not bool(candidate.missing_information),
            }
        operation = "update" if item_id in current_raw_by_id else "add"
        staged_ops[:] = [entry for entry in staged_ops if entry["item"].id != item_id]
        staged_ops.append(
            {
                "item": candidate,
                "operation": operation,
                "raw": raw_candidate,
            },
        )
        tool_calls.append(
            {
                "tool": name,
                "status": "staged",
                "operation": operation,
                "item_id": item_id,
                "title": str(candidate.title),
                "detectable": candidate.detectable,
                "judgement_mode": candidate.judgement_mode,
            },
        )
        return {
            "staged": operation,
            "item_id": item_id,
            "title": str(candidate.title),
            "detectable": candidate.detectable,
            "judgement_mode": candidate.judgement_mode,
            "note": "修改提案候選已建立；老師確認套用後才會寫入檢查表。",
        }

    return {"error": "不支援的工具或參數"}
