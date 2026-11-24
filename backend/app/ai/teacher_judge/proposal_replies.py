"""Teacher-facing reply text for proposal outcomes (package-internal)."""

from __future__ import annotations

import re
from typing import Any

from app.ai.teacher_judge.proposal_rules import (
    TEACHER_INTERNAL_GAP_MARKERS,
    TEACHER_LOCATION_GAP_MARKERS,
    TEACHER_RESULT_GAP_MARKERS,
    has_gap_marker,
    invalid_auto_item_titles,
    normalized_title_key,
)
from app.ai.teacher_judge.schemas import TeacherJudgeRubricItem
from app.models.teacher_judge_template_command import TeacherJudgeTemplateCommand


def reply_claims_created(reply: str) -> bool:
    """Detect teacher-facing prose that claims a proposal was created.

    Used only when the server confirmed no proposal tool outcome exists, so a
    prose-only claim is by definition false under the tools-first contract.
    """
    return _REPLY_CREATION_CLAIM_RE.search(reply or "") is not None


NO_RUBRIC_READY_REPLY = (
    "這項需求已具備自動檢查條件，但目前尚未選擇檢查表來源，"
    "因此無法建立可套用提案。請先選擇來源後再送出需求。"
)


# Only completed (past-tense) claims count; a follow-up such as
# 「補充後我就整理成提案」 is a question, not a false creation claim.
_REPLY_CREATION_CLAIM_RE = re.compile(
    r"已建立提案|已送出修改提案|提案已建立|已新增提案|已整理成提案|已(?:把|將).{0,40}?整理成提案"
)


def _teacher_result_hints(item: TeacherJudgeRubricItem) -> list[str]:
    """Select only result examples relevant to this item's wording."""
    context = item.title
    hint_rules = (
        (("文字", "內容", "輸出", "字串", "包含"), "預期文字或內容"),
        (("行", "列"), "行數"),
        (("欄位", "欄"), "欄位值"),
        (("版本",), "版本"),
        (("port", "連接埠", "埠"), "Port"),
        (("狀態", "正常", "執行", "安裝"), "狀態"),
        (("數字", "數值", "門檻", "至少", "不低於"), "數字或門檻"),
    )
    return list(
        dict.fromkeys(
            label
            for markers, label in hint_rules
            if any(marker.casefold() in context.casefold() for marker in markers)
        )
    )


def teacher_missing_gap_reply(item: TeacherJudgeRubricItem) -> str:
    """Render a teacher-facing gap description without leaking schema details."""
    missing = [value.strip() for value in item.missing_information if value.strip()]
    location_gaps = [
        value
        for value in missing
        if has_gap_marker(value, TEACHER_LOCATION_GAP_MARKERS)
    ]
    result_gaps = [
        value for value in missing if has_gap_marker(value, TEACHER_RESULT_GAP_MARKERS)
    ]
    remaining = [
        value
        for value in missing
        if value not in location_gaps
        and value not in result_gaps
        and not has_gap_marker(value, TEACHER_INTERNAL_GAP_MARKERS)
    ]

    gap_labels: list[str] = []
    if location_gaps:
        gap_labels.append("檢查位置")
    if result_gaps:
        gap_labels.append("通過方式")
    if remaining:
        gap_labels.append("「" + "、".join(remaining) + "」")
    if not gap_labels:
        gap_labels.append("會影響檢查範圍或判定的資訊")

    if len(gap_labels) == 1:
        gap_text = gap_labels[0]
    else:
        gap_text = "、".join(gap_labels[:-1]) + "與" + gap_labels[-1]
    detail = f"「{item.title}」的檢查目標已確認，但目前還缺少{gap_text}。"

    requests: list[str] = []
    if location_gaps:
        location_text = " ".join(location_gaps)
        needs_path = has_gap_marker(
            location_text,
            (
                "位置",
                "路徑",
                "目錄",
                "工作目錄",
                "檔案位置",
                "檔案所在",
                "程式位置",
            ),
        )
        needs_scope = has_gap_marker(
            location_text,
            ("服務名稱", "連接埠", "Port", "範圍", "對象"),
        )
        if needs_path and needs_scope:
            requests.append("請補充檔案或程式的絕對路徑，以及服務、連接埠或記錄範圍")
        elif needs_path:
            requests.append("請補上檔案或程式的絕對路徑")
        else:
            requests.append("請補充要檢查的服務、檔案或記錄範圍")
    if result_gaps:
        hints = _teacher_result_hints(item)
        expected = "、".join(hints) if hints else "可直接比對的預期結果"
        requests.append(f"請補充{expected}")
        requests.append("沒有固定答案時，也可以先收集結果讓你查看")
    if remaining:
        requests.append("請補充「" + "、".join(remaining) + "」")
    if not requests:
        requests.append("請補充會改變檢查範圍或判定的具體資訊")

    return detail + "。".join(requests) + "。"


def proposal_unavailable_reply(
    normalized_items: list[TeacherJudgeRubricItem],
    raw_items: Any,
    template_commands: list[TeacherJudgeTemplateCommand] | None = None,
) -> str:
    """Give the teacher a short, actionable reason why no proposal was created."""
    incomplete = [item for item in normalized_items if item.detectable == "partial"]
    if incomplete:
        seen: set[str] = set()
        deduped_incomplete: list[TeacherJudgeRubricItem] = []
        for item in reversed(incomplete):
            key = normalized_title_key(item.title)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            deduped_incomplete.append(item)
        deduped_incomplete.reverse()
        return " ".join(teacher_missing_gap_reply(item) for item in deduped_incomplete)

    invalid_auto_items = invalid_auto_item_titles(normalized_items, raw_items)
    if invalid_auto_items:
        valid_command_keys = {
            (command.template_key, command.command_key)
            for command in template_commands or []
        }
        invalid_references: list[str] = []
        for raw_item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(raw_item, dict):
                continue
            for raw_step in raw_item.get("check_steps") or []:
                if not isinstance(raw_step, dict):
                    continue
                reference = (
                    str(raw_step.get("template_key") or "").strip(),
                    str(raw_step.get("command_key") or "").strip(),
                )
                if reference not in valid_command_keys:
                    invalid_references.append(
                        "/".join(value or "未提供" for value in reference)
                    )
        invalid_details = "、".join(f"「{title}」" for title in invalid_auto_items)
        reason = "AI 沒有提供可轉成單一受控指令的完整執行參數"
        if invalid_references:
            reason += (
                "（原始工具名稱：" + "、".join(dict.fromkeys(invalid_references)) + "）"
            )
        return (
            f"這次未建立提案：{invalid_details}缺少可執行的檢查內容；{reason}。"
            "已確認工具清單只是優先建議，不會限制提案；這次是 AI 沒有提供完整 argv，"
            "不是老師需要補充答案。請重新產生；若持續發生，請由管理員檢查 AI 輸出。"
        )

    unsupported = [
        item.title for item in normalized_items if item.detectable == "manual"
    ]
    if unsupported:
        return (
            "這次仍未建立提案：AI 重新核查後，仍未替"
            + "、".join(f"「{title}」" for title in unsupported)
            + "提供通過驗證的唯讀檢查步驟。平台已有一般系統資訊查詢能力，"
            "這不是老師需要補充答案；請重新產生，持續發生時由管理員檢查 AI 輸出。"
        )

    if normalized_items:
        return "目前檢查表已包含相同內容，沒有新的變更需要套用。"
    return "我這次沒有成功整理出可套用的提案，請再試一次。"


def dedupe_rejected_ops_keep_latest(
    rejected_ops: list[tuple[TeacherJudgeRubricItem, dict[str, Any], str]],
) -> list[tuple[TeacherJudgeRubricItem, dict[str, Any], str]]:
    """Deduplicate retry rejections by normalized title, keeping the latest.

    The model is instructed to retry a failed tool call once, so the same
    requirement can appear twice in ``rejected_ops`` with different minted
    item ids. Without dedup the teacher sees one error line and one reply
    sentence per retry. Keep the last occurrence and preserve its order.
    """
    latest_by_key: dict[str, tuple[TeacherJudgeRubricItem, dict[str, Any], str]] = {}
    order: list[str] = []
    for entry in rejected_ops:
        key = normalized_title_key(entry[0].title)
        if not key:
            # Untitled entries cannot be matched; keep them as-is with a unique key.
            key = f"__untitled__{len(order)}:{id(entry)}"
        if key not in latest_by_key:
            order.append(key)
        else:
            # Move the key to the end so order reflects the latest retry.
            order.remove(key)
            order.append(key)
        latest_by_key[key] = entry
    return [latest_by_key[key] for key in order]


def dedupe_tool_outcomes_keep_latest(
    tool_outcomes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collapse duplicate tool outcome lines, keeping the latest per title.

    Only ``rejected``/``duplicate`` entries are collapsed; ``staged``/``read``
    entries keep their original order because they represent distinct outcomes.
    """
    latest_index_by_key: dict[str, int] = {}
    result: list[dict[str, Any]] = []
    for entry in tool_outcomes:
        if not isinstance(entry, dict):
            result.append(entry)
            continue
        status = str(entry.get("status") or "")
        if status not in {"rejected", "duplicate"}:
            result.append(entry)
            continue
        key = normalized_title_key(entry.get("title"))
        if not key:
            result.append(entry)
            continue
        key = f"{status}:{key}"
        if key in latest_index_by_key:
            result[latest_index_by_key[key]] = entry
        else:
            latest_index_by_key[key] = len(result)
            result.append(entry)
    return result


def _title_covered_by_reply(reply_text: str, title: str) -> bool:
    """Check whether the model reply already explains this rejected title.

    Exact title match is the common case. Retry/paraphrase cases such as
    「取得 main.log 檔案內容」 vs 「要查看 main.log 的部分」 share only a
    distinctive token (``main.log``), so also match on long tokens or on at
    least two short tokens to avoid appending a duplicate server note.
    """
    reply_key = normalized_title_key(reply_text)
    title_key = normalized_title_key(title)
    if not title_key:
        return False
    if title_key and title_key in reply_key:
        return True
    title_tokens = [
        token
        for token in re.split(r"[\s\-_/：:「」『』（）()，。、,.;!?]+", title_key)
        if token
    ]
    if not title_tokens:
        return False
    if any(len(token) >= 4 and token in reply_key for token in title_tokens):
        return True
    matched_short = sum(
        1 for token in title_tokens if len(token) >= 2 and token in reply_key
    )
    return matched_short >= 2


def _titles_overlap(left: str, right: str) -> bool:
    left_key = normalized_title_key(left)
    right_key = normalized_title_key(right)
    return bool(
        left_key and right_key and (left_key in right_key or right_key in left_key)
    )


def proposal_summary_reply(
    reply_text: str,
    *,
    staged_ops: list[dict[str, Any]],
    rejected_ops: list[tuple[TeacherJudgeRubricItem, dict[str, Any], str]],
    conversation_focus: dict[str, Any] | None,
    template_commands: list[TeacherJudgeTemplateCommand] | None,
    error_titles: list[str] | None = None,
) -> str:
    """Add a server-owned proposal count and the items the teacher must look at.

    Counts come from staged tool outcomes, never from model prose. A single clean
    proposal keeps the model's own sentence untouched.
    """
    created: set[str] = set()
    updated: set[str] = set()
    teacher_review: dict[str, str] = {}
    for entry in staged_ops:
        item = entry["item"]
        key = normalized_title_key(item.title)
        (updated if entry["operation"] == "update" else created).add(key)
        if item.judgement_mode == "teacher":
            teacher_review[key] = item.title
    staged_keys = created | updated
    if not staged_keys:
        return reply_text

    unresolved = [
        (item, raw)
        for item, raw, _reason in dedupe_rejected_ops_keep_latest(rejected_ops)
        if normalized_title_key(item.title) not in staged_keys
    ]
    # Unresolved tool errors (already explained by the server-owned error reply)
    # still count as items that need follow-up; skip titles that later staged.
    unresolved_keys = {normalized_title_key(item.title) for item, _raw in unresolved}
    error_keys = {
        key
        for key in (normalized_title_key(title) for title in error_titles or [])
        if key and key not in staged_keys and key not in unresolved_keys
    }
    known_titles = [*staged_keys, *unresolved_keys, *error_keys]
    focus_gaps = [
        (label, requirement)
        for requirement in (conversation_focus or {}).get("requirements") or []
        if requirement.get("status") in {"needs_information", "unsupported"}
        and (label := str(requirement.get("focus_key") or "").strip())
        and not any(_titles_overlap(label, title) for title in known_titles)
    ]
    needs_follow_up = len(unresolved) + len(error_keys) + len(focus_gaps)

    attention = [
        f"「{title}」交給老師核查：執行後會顯示結果供你判斷。"
        for title in teacher_review.values()
        if not _title_covered_by_reply(reply_text, title)
    ]
    for item, raw in unresolved:
        if not _title_covered_by_reply(reply_text, item.title):
            attention.append(
                proposal_unavailable_reply([item], [raw], template_commands).strip()
            )
    for label, requirement in focus_gaps:
        if _title_covered_by_reply(reply_text, label):
            continue
        missing = "、".join(
            str(value) for value in requirement.get("missing_information") or []
        )
        attention.append(
            f"「{label}」還缺少：{missing}。"
            if missing
            else f"「{label}」目前無法安全取證。"
        )
    if len(staged_keys) == 1 and not needs_follow_up and not attention:
        return reply_text

    counts = []
    if created:
        counts.append(f"已建立 {len(created)} 項提案")
    if updated:
        counts.append(f"已送出 {len(updated)} 項修改提案")
    lines = ["、".join(counts) + "，請在下方提案清單確認後套用。"]
    if needs_follow_up or teacher_review:
        summary = f"摘要：共 {len(staged_keys) + needs_follow_up} 項需求，{len(staged_keys)} 項已建立提案"
        if teacher_review:
            summary += f"（其中 {len(teacher_review)} 項交給老師核查）"
        if needs_follow_up:
            summary += f"，{needs_follow_up} 項需要補資訊或調整"
        lines.append(summary + "。")
    lines.append(reply_text)
    if attention:
        lines.append("需要你注意：")
        lines.extend(f"- {line}" for line in attention)
    return "\n".join(lines)


def tool_error_reply(errors: list[dict[str, Any]], *, staged: bool = False) -> str:
    titles = "、".join(
        f"「{title}」"
        for title in dict.fromkeys(
            str(error.get("title") or error.get("item_id") or "檢查項目")
            for error in errors
        )
    )
    prefix = "已整理通過驗證的提案，請確認後套用。\n" if staged else ""
    return (
        prefix
        + f"{titles}的修改未通過驗證，本次修正已停止，沒有背景重試。檢查表已保留；請調整檢查方式後重新提交。"
    )
