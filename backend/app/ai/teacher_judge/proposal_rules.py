"""Proposal candidate validation rules and Finalizer completion blockers (package-internal)."""

from __future__ import annotations

import uuid
from typing import Any

from app.ai.teacher_judge.automation_support import (
    get_script_generation_blockers,
    missing_step_information,
)
from app.ai.teacher_judge.check_plan_contract import (
    TYPED_STEP_REPAIR_HINT,
    typed_item_issues,
)
from app.ai.teacher_judge.machine_context import (
    canonicalize_machine_node_key,
    rubric_item_machine_issues,
)
from app.ai.teacher_judge.rubric_normalization import (
    raw_item_detectable,
    raw_items_by_id,
)
from app.ai.teacher_judge.schemas import (
    TeacherJudgeRubricAnalysis,
    TeacherJudgeRubricItem,
)
from app.models.teacher_judge_template_command import TeacherJudgeTemplateCommand


def finalizer_completion_blockers(
    snapshot_items: Any,
    staged_ops: list[dict[str, Any]],
    *,
    template_commands: list[TeacherJudgeTemplateCommand] | None,
    machine_entries: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Validate the effective Finalizer candidate before accepting prose."""

    items: list[TeacherJudgeRubricItem] = []
    for raw in snapshot_items if isinstance(snapshot_items, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            items.append(TeacherJudgeRubricItem.model_validate(raw))
        except ValueError:
            # This in-loop repair gate is best-effort. The route-level
            # readiness check remains the fail-closed source of truth.
            continue
    index_by_id = {item.id: index for index, item in enumerate(items)}
    for entry in staged_ops:
        candidate = entry.get("item")
        if not isinstance(candidate, TeacherJudgeRubricItem):
            continue
        index = index_by_id.get(candidate.id)
        if index is None:
            index_by_id[candidate.id] = len(items)
            items.append(candidate)
        else:
            items[index] = candidate

    analysis = TeacherJudgeRubricAnalysis(items=items)
    return [
        dict(blocker)
        for blocker in get_script_generation_blockers(
            analysis,
            template_commands or [],
            require_target_node=bool(machine_entries),
            require_typed_plan=True,
        )
    ]


def mint_proposal_item_id(existing_ids: set[str]) -> str:
    """Mint a collision-free server-owned item ID for a create proposal."""
    while True:
        candidate = f"item-{uuid.uuid4().hex[:8]}"
        if candidate not in existing_ids:
            return candidate


def normalized_title_key(title: Any) -> str:
    """Case/whitespace-insensitive key for duplicate item title checks."""
    return " ".join(str(title or "").split()).casefold()


def duplicate_title_owner(
    title: str,
    snapshot_items: Any,
    staged_ops: list[dict[str, Any]],
) -> tuple[str, str] | None:
    """Return (id, title) of the first same-title item already present.

    Checks the current server-side rubric snapshot plus every operation staged
    this turn, so a create call cannot duplicate an existing item or another
    candidate staged earlier in the same conversation turn.
    """
    key = normalized_title_key(title)
    if not key:
        return None
    snapshot = snapshot_items if isinstance(snapshot_items, list) else []
    for item in snapshot:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        existing_title = str(item.get("title") or "")
        if item_id and normalized_title_key(existing_title) == key:
            return item_id, existing_title
    for entry in staged_ops:
        staged_item = entry.get("item")
        if staged_item is None:
            continue
        staged_id = str(getattr(staged_item, "id", "") or "").strip()
        staged_title = str(getattr(staged_item, "title", "") or "")
        if staged_id and normalized_title_key(staged_title) == key:
            return staged_id, staged_title
    return None


_PARAMETER_GAP_FIELD_HINTS: dict[str, str] = {
    "要檢查的檔案、服務或記錄範圍": "argv（單一非空的命令字串 list）",
    "實際 Python 命令與參數": "argv（python.run_entrypoint 的完整命令 list）",
}


def _recoverable_parameter_gaps(item: TeacherJudgeRubricItem) -> list[str]:
    """Return step-parameter gaps the model can fix itself by re-calling the tool."""
    gaps: list[str] = []
    for step in item.check_steps:
        gaps.extend(
            gap
            for gap in missing_step_information(step)
            if not has_gap_marker(gap, ("工作目錄", "路徑"))
        )
    return list(dict.fromkeys(gaps))


def proposal_candidate_rejection(
    normalized: TeacherJudgeRubricItem,
    raw: dict[str, Any],
    *,
    capability_declared: bool,
    ready_only: bool,
    template_commands: list[TeacherJudgeTemplateCommand] | None,
) -> str | None:
    """Return why a tool-submitted candidate cannot become a Ready proposal."""
    machine_issues = rubric_item_machine_issues(normalized.model_dump(mode="json"))
    if machine_issues:
        return f"「{normalized.title}」的機器目標無效：{'；'.join(machine_issues)}。"
    if not ready_only:
        # Refine (full-table polish) may stage non-auto candidates; the polish
        # itself is the fix for downgraded detectability.
        return None
    # Below here only chat/attachment proposals (ready_only) are checked; the
    # messages never mention partial/manual because chat tools no longer expose them.
    if invalid_auto_item_titles([normalized], [raw]):
        return (
            f"「{normalized.title}」的 check_steps 沒有通過驗證；"
            "請改用 typed collector（command 需單一非空 argv），補齊必要參數後重新呼叫。"
        )
    if capability_declared and _manual_candidates_needing_capability_review(
        [normalized], [raw], template_commands
    ):
        return (
            f"「{normalized.title}」缺少可執行的 check_steps；"
            "請補上完整的 check_steps 後重新呼叫。"
        )
    if normalized.detectable != "auto":
        missing = list(normalized.missing_information)
        parameter_gaps = _recoverable_parameter_gaps(normalized)
        if missing and parameter_gaps and set(missing) <= set(parameter_gaps):
            hints = "；".join(
                _PARAMETER_GAP_FIELD_HINTS.get(gap, gap) for gap in missing
            )
            return (
                f"「{normalized.title}」的提案只缺少可由你自行補齊的欄位：{hints}。"
                "請重新呼叫 create_checklist_item（修改既有項目則用 "
                "edit_checklist_item），把上述欄位填進 check_steps[].collector "
                "後重試；這些欄位由你依需求語意判斷即可，不需要老師補充，"
                "也不要改在 reply 中說明缺少內容。"
            )
        missing_text = "、".join(missing) or "缺少可自動取證的完整檢查步驟"
        return (
            f"「{normalized.title}」目前無法形成可套用的提案：{missing_text}。"
            "不要猜測，本輪不要再為此項呼叫工具，請在 reply 詢問老師，"
            "proposal_status 設為 needs_information。"
        )
    return None


PROPOSAL_COMPARE_FIELDS = (
    "title",
    "target_node_key",
    "peer_node_key",
    "checked",
    "detectable",
    "judgement_mode",
    "detection_method",
    "fallback",
    "missing_information",
    "check_steps",
)


def proposal_item_value(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item.get(key) for key in PROPOSAL_COMPARE_FIELDS}


def proposal_status_claims_ready(status: Any) -> bool:
    """Use only the structured machine field; teacher-facing prose is not control flow."""
    return str(status or "").strip().lower() == "ready"


def invalid_auto_item_titles(
    normalized_items: list[TeacherJudgeRubricItem],
    raw_items: Any,
) -> list[str]:
    """Return model-declared auto items rejected by command/schema validation."""
    raw_by_id = raw_items_by_id(raw_items)
    return [
        item.title
        for item in normalized_items
        if item.detectable == "manual"
        and raw_item_detectable(raw_by_id.get(item.id)) == "auto"
    ]


def _manual_candidates_needing_capability_review(
    normalized_items: list[TeacherJudgeRubricItem],
    raw_items: Any,
    template_commands: list[TeacherJudgeTemplateCommand] | None,
) -> list[str]:
    """Find complete model candidates that skipped an available generic capability."""
    if not any(
        command.command_key == "system.run_command"
        for command in template_commands or []
    ):
        return []
    raw_by_id = raw_items_by_id(raw_items)
    return [
        item.title
        for item in normalized_items
        if item.detectable == "manual"
        and not item.check_steps
        and not item.missing_information
        and raw_item_detectable(raw_by_id.get(item.id)) == "manual"
    ]


TEACHER_LOCATION_GAP_MARKERS = (
    "位置",
    "路徑",
    "目錄",
    "工作目錄",
    "檔案",
    "程式位置",
    "服務名稱",
    "連接埠",
    "Port",
    "記錄",
    "日誌",
    "範圍",
    "對象",
)


TEACHER_RESULT_GAP_MARKERS = (
    "預期答案",
    "預期結果",
    "預期內容",
    "通過方式",
)


TEACHER_INTERNAL_GAP_MARKERS = (
    "取證",
    "command_key",
    "argv",
    "check_steps",
    "檢查步驟",
    "檢查能力",
    "命令與參數",
    "唯讀命令",
    "逾時",
    "timeout",
    "可執行",
    "judgement_mode",
    "proposal_status",
    "detection_method",
    "missing_information",
    "template_key",
    "parameters",
    "客觀答案",
    "AI",
)


def has_gap_marker(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker.casefold() in value.casefold() for marker in markers)


def canonicalize_proposal_machine_fields(
    raw_item: dict[str, Any],
    machine_entries: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if machine_entries is None:
        return raw_item
    result = dict(raw_item)
    for field_name in ("target_node_key", "peer_node_key"):
        if field_name in result:
            result[field_name] = canonicalize_machine_node_key(
                result.get(field_name), machine_entries
            )
    return result


def contract_tool_error(
    issues: list[dict[str, Any]], *, item_id: str
) -> dict[str, Any]:
    error_messages = []
    for issue in issues[:8]:
        message = str(issue.get("message") or "typed contract 無效")
        field = str(issue.get("field") or "").strip()
        error_messages.append(f"{field}: {message}" if field else message)
    return {
        "error": "；".join(error_messages),
        "reason_code": "check_plan_contract_invalid",
        "teacher_input_required": False,
        "item_id": item_id,
        "issues": issues[:16],
        "repair_hint": TYPED_STEP_REPAIR_HINT,
    }


def candidate_contract_error(
    candidate: TeacherJudgeRubricItem,
    *,
    other_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Use the same location/typed verdict for create and edit proposals."""
    issues = typed_item_issues(candidate, other_items=other_items)
    if not issues:
        return None
    result = contract_tool_error(issues, item_id=candidate.id)
    repair_hint = next(
        (issue["repair_hint"] for issue in issues if issue.get("repair_hint")), None
    )
    if repair_hint:
        result.update(
            repair_hint=repair_hint,
            candidate_check_steps=[
                step.model_dump(mode="json") for step in candidate.check_steps
            ],
        )
    return result
