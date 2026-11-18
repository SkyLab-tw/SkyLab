"""Teacher Judge 對話訊息流程中與 HTTP 無關的步驟。

``POST /teaching-classes/{id}/judge/sessions/{id}/messages`` 的路由只負責
存取檢查、呼叫模型與例外對應；這裡放它用到的受理、脈絡、保存與回收步驟：

- 受理：鎖定 session、檢查進行中的請求與 revision、落地使用者訊息（``admit_chat_message``）
- 脈絡：把餵給模型的資料全部讀出後結束讀取交易（``load_chat_context``）
- 舊版檢查表是否仍靠範本指令（決定要不要把指令清單餵給模型）
- 模型提案的執行節點／觀察節點是否屬於本班機器
- refine 回合的腳本就緒檢查
- 助理訊息的 metadata（含附件逐項核查的整體狀態）與助理訊息組裝
- 回覆保存、失敗紀錄與失敗回收
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, desc, select

from app.ai.monitoring import new_ai_request_id, record_ai_template_call, usage_metrics
from app.ai.teacher_judge._types import VLLMMetrics
from app.ai.teacher_judge.attachment_service import (
    attachment_context,
    bind_attachments_to_message,
    get_pending_attachments,
)
from app.ai.teacher_judge.automation_support import get_script_generation_blockers
from app.ai.teacher_judge.config import settings as teacher_judge_settings
from app.ai.teacher_judge.machine_context import (
    format_machine_context,
    load_class_machine_nodes,
    machine_context_entries,
    rubric_item_machine_issues,
)
from app.ai.teacher_judge.schemas import (
    TeacherJudgeRubricAnalysis,
    TeacherJudgeRubricChatMessage,
    TeacherJudgeSessionChatResponse,
    TeacherJudgeSessionMessageCreateRequest,
)
from app.ai.teacher_judge.session_service import (
    WorkflowMessage,
    apply_proposal_operations_to_analysis,
    bounded_history,
    conversation_focus_from_item_results,
    ensure_active,
    get_session,
    message_public,
    normalize_workflow_item_results,
    reanalysis_workflow_message,
    redact_message_content,
    schedule_summary,
    selected_file_for_chat,
    workflow_error_message,
)
from app.ai.teacher_judge.template_command_service import get_enabled_template_commands
from app.core.db import end_read_transaction
from app.core.i18n import t
from app.models.base import get_datetime_utc
from app.models.teacher_judge_attachment import TeacherJudgeSessionAttachment
from app.models.teacher_judge_file import TeacherJudgeFile
from app.models.teacher_judge_session import (
    TeacherJudgeMessageRole,
    TeacherJudgeMessageType,
    TeacherJudgeSession,
    TeacherJudgeSessionMessage,
)
from app.models.teacher_judge_template_command import TeacherJudgeTemplateCommand

logger = logging.getLogger(__name__)

_UNNAMED_ITEM = "未命名項目"


def uses_legacy_command_context(analysis: dict[str, Any] | None) -> bool:
    """舊版檢查表的 check_steps 會帶 template_key／command_key，需要範本指令清單。"""
    return any(
        isinstance(step, dict)
        and (step.get("template_key") or step.get("command_key"))
        for raw_item in ((analysis or {}).get("items") or [])
        if isinstance(raw_item, dict)
        for step in (raw_item.get("check_steps") or [])
    )


def prompt_template_scope(
    file: TeacherJudgeFile | None, legacy_command_context: bool
) -> tuple[str, list[str] | None]:
    """回傳餵給模型的 (template_key, environment_keys)。

    只有舊版指令情境才沿用檢查表自己的範本與環境；其餘一律視為 linux、無環境限制。
    """
    if file is None or not legacy_command_context:
        return "linux", None
    return file.template_key, file.environment_keys


def _proposal_item_label(candidate: dict[str, Any]) -> str:
    return str(candidate.get("id") or candidate.get("title") or _UNNAMED_ITEM)


def validate_proposal_machine_nodes(
    session: Session,
    teaching_class_id: uuid.UUID,
    proposal: list[dict[str, Any]],
) -> None:
    """模型提案裡的 target／peer 節點必須屬於本班，且自動檢查項目要指定執行節點。

    違反時丟 422，依序檢查：節點不屬於本班 → 缺執行節點 → 節點／peer token 契約不一致。
    """
    class_nodes = load_class_machine_nodes(session, teaching_class_id)
    valid_node_keys = {node.node_key for node in class_nodes}
    invalid_node_keys: set[str] = set()
    missing_target_item_ids: list[str] = []
    machine_contract_issues: dict[str, list[str]] = {}
    for raw in proposal:
        if not isinstance(raw, dict):
            continue
        candidate = raw.get("item")
        candidate = candidate if isinstance(candidate, dict) else raw
        node_key = str(candidate.get("target_node_key") or "").strip()
        if node_key and node_key not in valid_node_keys:
            invalid_node_keys.add(node_key)
        peer_node_key = str(candidate.get("peer_node_key") or "").strip()
        if peer_node_key and peer_node_key not in valid_node_keys:
            invalid_node_keys.add(peer_node_key)
        item_issues = rubric_item_machine_issues(candidate)
        if item_issues:
            machine_contract_issues[_proposal_item_label(candidate)] = item_issues
        if (
            class_nodes
            and str(candidate.get("detectable") or "").strip().lower() == "auto"
            and not node_key
        ):
            missing_target_item_ids.append(_proposal_item_label(candidate))
    if invalid_node_keys:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "teacher_judge_target_node_not_in_class",
                "message": t("teacherJudgeSessions.proposalTargetNodeNotInClass"),
                "target_node_keys": sorted(invalid_node_keys),
            },
        )
    if missing_target_item_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "teacher_judge_target_node_required",
                "message": t("teacherJudgeSessions.proposalTargetNodeRequired"),
                "item_ids": list(dict.fromkeys(missing_target_item_ids)),
            },
        )
    if machine_contract_issues:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "teacher_judge_machine_contract_invalid",
                "message": t("teacherJudgeSessions.proposalMachineContractInvalid"),
                "items": machine_contract_issues,
            },
        )


def refine_readiness_workflow(
    session: Session,
    *,
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    file: TeacherJudgeFile,
    proposal: list[dict[str, Any]] | None,
    template_commands: list[TeacherJudgeTemplateCommand],
    analysis_revision: int | None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> WorkflowMessage:
    """refine 回合：以「套用提案後」的伺服器端檢查表判斷能否進入腳本製作。

    就緒與否不看模型的文字，也不靠前端各自推算。
    """
    base_analysis = TeacherJudgeRubricAnalysis.model_validate(file.analysis_json)
    candidate_analysis = apply_proposal_operations_to_analysis(base_analysis, proposal)
    readiness_nodes = load_class_machine_nodes(session, teaching_class_id)
    blockers = get_script_generation_blockers(
        candidate_analysis,
        template_commands,
        require_target_node=bool(readiness_nodes),
        require_typed_plan=True,
    )
    failed_tools = {
        str(outcome.get("item_id") or outcome.get("title") or outcome.get("tool")): outcome
        for outcome in (tool_calls or [])
        if outcome.get("status") in {"error", "rejected", "duplicate"} and not outcome.get("resolved")
    }
    for outcome in failed_tools.values():
        blockers.append({
            "item_id": outcome.get("item_id"),
            "title": str(outcome.get("title") or "檢查項目"),
            "status": "analysis_error",
            "missing_information": [],
            "reason_code": str(outcome.get("reason_code") or "tool_arguments_invalid"),
            "detail": "本次修改未通過驗證，修正已停止；請調整檢查方式後重新提交",
            "issues": [
                {"step_id": issue.get("step_id"), "step_index": issue.get("step_index"),
                 "detail": str(issue.get("message") or "檢查步驟驗證失敗")}
                for issue in outcome.get("issues", []) if isinstance(issue, dict)
            ][:16],
        })
    if blockers:
        logger.warning(
            "Teacher Judge script readiness blocked: session=%s source_file=%s "
            "revision=%s blockers=%s",
            session_id,
            file.id,
            analysis_revision,
            [
                {
                    "item_id": blocker.get("item_id"),
                    "status": blocker.get("status"),
                    "reason_code": blocker.get("reason_code"),
                }
                for blocker in blockers
            ],
        )
    return reanalysis_workflow_message(
        blockers,
        source_file_id=file.id,
        analysis_revision=analysis_revision,
        proposal=proposal,
    )


def attachment_analysis_status(item_results: list[dict[str, Any]]) -> str:
    """附件逐項核查的整體狀態：analysis_error > needs_information > unsupported > resolved。"""
    statuses = {row.get("status") for row in item_results}
    for status in ("analysis_error", "needs_information", "unsupported"):
        if status in statuses:
            return status
    return "resolved"


def build_assistant_metadata(
    *,
    metrics: Mapping[str, object],
    workflow: WorkflowMessage | None,
    item_results: list[dict[str, Any]] | None,
    itemwise_error: str | None,
    conversation_focus: dict[str, Any] | None,
    tool_calls: Any,
    source_file_id: uuid.UUID | None,
    analysis_revision: int | None,
    proposal: list[dict[str, Any]] | None = None,
    is_refine: bool = False,
) -> dict[str, Any]:
    """組出助理訊息的 metadata_json。

    優先序：refine 的 workflow 結果 → 附件逐項核查結果 → 一般對話的 focus。
    """
    metadata: dict[str, Any] = {"metrics": metrics}
    source_file = str(source_file_id) if source_file_id else None
    if workflow is not None:
        metadata.update(workflow["metadata"])
    elif item_results is not None:
        item_results = normalize_workflow_item_results(item_results)
        if itemwise_error:
            item_results = [
                {
                    "item_id": "attachment-analysis",
                    "title": "附件逐項核查",
                    "status": "analysis_error",
                    "missing_information": [],
                    "reason_code": "teacher_judge_attachment_analysis_failed",
                    "detail": itemwise_error,
                }
            ]
        metadata["item_results"] = item_results
        metadata["conversation_focus"] = conversation_focus_from_item_results(
            item_results,
            source_file_id=source_file_id,
            analysis_revision=analysis_revision,
            turn_kind="follow_up",
        )
        metadata.update(
            {
                "status": attachment_analysis_status(item_results),
                "stage": "attachment_analysis",
                "source_file_id": source_file,
                "analysis_revision": analysis_revision,
            }
        )
    elif conversation_focus is not None:
        metadata["conversation_focus"] = {
            **conversation_focus,
            "source_file_id": source_file,
            "analysis_revision": analysis_revision,
        }
    if tool_calls:
        metadata["tool_calls"] = tool_calls
    if proposal and source_file_id is not None and analysis_revision is not None:
        metadata.update(
            rubric_proposal=proposal,
            source_file_id=source_file,
            analysis_revision=analysis_revision,
            is_refine=is_refine,
        )
    return metadata


@dataclass
class ChatAdmission:
    """An admitted chat request: the durable user message plus what failure recovery needs."""

    item: TeacherJudgeSession
    item_id: uuid.UUID
    file: TeacherJudgeFile | None
    base_revision: int | None
    attachments: list[TeacherJudgeSessionAttachment]
    ai_started: float
    ai_started_at: datetime
    deadline: float
    user_message: TeacherJudgeSessionMessage
    request_message_id: uuid.UUID
    source_file_id: uuid.UUID | None
    ai_request_id: str

    def remaining_seconds(self) -> float:
        return max(0, self.deadline - perf_counter())

    def deadline_exceeded(self) -> bool:
        return perf_counter() >= self.deadline


@dataclass
class ChatContext:
    """Everything the model call needs, already read from the database."""

    template_commands: list[TeacherJudgeTemplateCommand]
    rubric_context: str
    machine_entries: list[dict[str, Any]]
    machine_context: str
    template_key: str
    environment_keys: list[str] | None
    prompt_attachment_context: str
    teacher_message_content: str
    use_itemwise: bool
    history: list[TeacherJudgeRubricChatMessage] | None


@dataclass
class ChatGeneration:
    """What one model run produced for this chat turn."""

    reply: str
    proposal: list[dict[str, Any]] | None
    metrics: VLLMMetrics
    item_results: list[dict[str, Any]] | None = None
    itemwise_error: str | None = None
    conversation_focus: dict[str, Any] | None = None
    tool_calls: Any = None


def save_workflow_message(
    session: Session,
    item: TeacherJudgeSession,
    *,
    content: str,
    metadata: dict[str, Any],
    created_by: uuid.UUID | None = None,
) -> TeacherJudgeSessionMessage | None:
    """Best-effort persistence for a safe, teacher-facing workflow outcome."""
    assistant = TeacherJudgeSessionMessage(
        session_id=item.id,
        role=TeacherJudgeMessageRole.assistant,
        content=redact_message_content(content),
        message_type=TeacherJudgeMessageType.chat,
        metadata_json=metadata,
        created_by=created_by,
    )
    try:
        session.add(assistant)
        session.commit()
        session.refresh(assistant)
    except Exception:
        session.rollback()
        logger.exception(
            "Unable to persist Teacher Judge workflow message for session %s",
            item.id,
        )
        return None
    try:
        schedule_summary(session, item, boundary_message_id=assistant.id)
    except Exception:
        # The message is already durable; a summary scheduling failure must not
        # turn a successful workflow response into an API error.
        logger.exception(
            "Unable to schedule Teacher Judge summary for workflow message %s",
            assistant.id,
        )
    return assistant


def record_chat_failure(
    session: Session,
    item: TeacherJudgeSession,
    *,
    user_id: uuid.UUID,
    source_file_id: uuid.UUID | None,
    analysis_revision: int | None,
    ai_request_id: str,
    ai_started: float,
    ai_started_at: datetime,
    status_code: int | None,
    error_message: str,
    request_message_id: uuid.UUID | None = None,
) -> WorkflowMessage:
    """對話處理失敗時：留一則給老師看的失敗訊息，並記一筆失敗的 AI 呼叫。

    只負責記錄；要怎麼往外丟例外由呼叫端決定。
    """
    failure = workflow_error_message(
        stage="reanalysis",
        status_code=status_code,
        source_file_id=source_file_id,
        analysis_revision=analysis_revision,
        reason_code=(
            "teacher_judge_workflow_timeout"
            if error_message == "workflow_timeout"
            else None
        ),
    )
    # A cleared conversation must stay cleared even if its pending AI call fails.
    origin = (
        session.exec(
            select(TeacherJudgeSessionMessage).where(
                TeacherJudgeSessionMessage.id == request_message_id
            )
        ).first()
        if request_message_id is not None
        else None
    )
    if origin is not None:
        origin.metadata_json = {**(origin.metadata_json or {}), "processing": False}
        session.add(origin)
    if request_message_id is None or origin is not None:
        save_workflow_message(
            session,
            item,
            content=failure["content"],
            metadata=failure["metadata"],
            created_by=user_id,
        )
    record_ai_template_call(
        session=session,
        user_id=user_id,
        call_type="teacher_judge_chat",
        model_name=teacher_judge_settings.VLLM_MODEL_NAME,
        metrics=usage_metrics(
            {},
            perf_counter() - ai_started,
            request_id=ai_request_id,
            started_at=ai_started_at,
        ),
        status="error",
        error_message=error_message,
    )
    return failure


def recover_chat_failure(
    session: Session,
    admission: ChatAdmission | None,
    *,
    user_id: uuid.UUID,
    status_code: int | None,
    error_message: str,
) -> WorkflowMessage | None:
    """Leave a failure message for an admitted request that is still processing."""
    # Roll back partial persistence before checking the durable admission.
    session.rollback()
    if admission is None:
        return None
    origin = session.get(TeacherJudgeSessionMessage, admission.request_message_id)
    if origin is None or not (origin.metadata_json or {}).get("processing"):
        return None
    admitted_item = session.get(TeacherJudgeSession, admission.item_id)
    if admitted_item is None:
        return None
    return record_chat_failure(
        session,
        admitted_item,
        user_id=user_id,
        source_file_id=admission.source_file_id,
        analysis_revision=admission.base_revision,
        ai_request_id=admission.ai_request_id,
        ai_started=admission.ai_started,
        ai_started_at=admission.ai_started_at,
        status_code=status_code,
        error_message=error_message,
        request_message_id=admission.request_message_id,
    )


def admit_chat_message(
    session: Session,
    *,
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    payload: TeacherJudgeSessionMessageCreateRequest,
    user_id: uuid.UUID,
    on_staged: Callable[[ChatAdmission], None],
) -> ChatAdmission:
    """Lock the session, reject conflicting requests, and commit the user message.

    ``on_staged`` receives the admission just before the commit so failure
    recovery can still find the request if the commit or refresh itself fails.
    """
    item = get_session(session, teaching_class_id, session_id)
    # Serialize admission across backend workers, then release before model I/O.
    session.exec(
        select(TeacherJudgeSession.id)
        .where(TeacherJudgeSession.id == item.id)
        .with_for_update()
    ).one()
    session.refresh(item)
    ensure_active(item)
    latest_user = session.exec(
        select(TeacherJudgeSessionMessage)
        .where(
            TeacherJudgeSessionMessage.session_id == item.id,
            TeacherJudgeSessionMessage.role == TeacherJudgeMessageRole.user,
        )
        .order_by(
            desc(TeacherJudgeSessionMessage.created_at),
            desc(TeacherJudgeSessionMessage.id),
        )
        .limit(1)
    ).first()
    pending = (latest_user.metadata_json or {}) if latest_user else {}
    if (
        pending.get("processing")
        and pending.get("processing_deadline", 0)
        > datetime.now(timezone.utc).timestamp()
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "teacher_judge_request_in_progress",
                "message": "這個檢查仍有 AI 分析進行中，請等待並重新整理回覆後再送出。",
            },
        )
    file = selected_file_for_chat(session, item)
    base_revision = file.analysis_revision if file else None
    if (
        file
        and payload.analysis_revision is not None
        and payload.analysis_revision != file.analysis_revision
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "teacher_judge_analysis_revision_conflict",
                "message": t("teacherJudgeSessions.analysisRevisionConflict"),
                "analysis_revision": file.analysis_revision,
            },
        )
    if not payload.content.strip() and not payload.attachment_ids:
        raise HTTPException(
            status_code=422,
            detail=t("teacherJudgeSessions.messageOrAttachmentRequired"),
        )
    attachments = get_pending_attachments(session, item.id, payload.attachment_ids)
    ai_started = perf_counter()
    ai_started_at = datetime.now(timezone.utc)
    deadline = ai_started + teacher_judge_settings.REQUEST_TIMEOUT_SECONDS
    user_message = TeacherJudgeSessionMessage(
        session_id=item.id,
        role=TeacherJudgeMessageRole.user,
        content=redact_message_content(payload.content.strip()),
        metadata_json={
            **({"ui_hidden": True} if payload.is_refine else {}),
            "processing": True,
            "processing_deadline": ai_started_at.timestamp()
            + teacher_judge_settings.REQUEST_TIMEOUT_SECONDS,
        },
        created_by=user_id,
    )
    session.add(user_message)
    session.flush()
    bind_attachments_to_message(session, attachments, user_message.id)
    request_message_id = user_message.id
    source_file_id = file.id if file else None
    ai_request_id = new_ai_request_id()
    item_id = item.id
    admission = ChatAdmission(
        item=item,
        item_id=item_id,
        file=file,
        base_revision=base_revision,
        attachments=attachments,
        ai_started=ai_started,
        ai_started_at=ai_started_at,
        deadline=deadline,
        user_message=user_message,
        request_message_id=request_message_id,
        source_file_id=source_file_id,
        ai_request_id=ai_request_id,
    )
    on_staged(admission)
    session.commit()
    session.refresh(user_message)
    return admission


def load_chat_context(
    session: Session,
    admission: ChatAdmission,
    *,
    teaching_class_id: uuid.UUID,
    payload: TeacherJudgeSessionMessageCreateRequest,
) -> ChatContext:
    """Read every model input from the database, then end the read transaction."""
    file = admission.file
    item = admission.item
    legacy_command_context = uses_legacy_command_context(
        file.analysis_json if file else None
    )
    template_commands = (
        get_enabled_template_commands(
            session,
            file.template_key if file else "linux",
            include_cross_template=True,
        )
        if legacy_command_context
        else []
    )
    rubric_context = (
        json.dumps(file.analysis_json, ensure_ascii=False) if file else "{}"
    )
    machine_entries = machine_context_entries(session, teaching_class_id)
    machine_context = format_machine_context(machine_entries)
    # 所有要餵給模型的資料都先從 DB 讀成區域變數，再結束讀取交易才開始等
    # 模型；否則這條連線會 idle in transaction 整段 LLM 呼叫（可能數分鐘），
    # PgBouncer transaction pooling 下每個請求都佔住一條 server 連線。
    template_key, environment_keys = prompt_template_scope(file, legacy_command_context)
    prompt_attachment_context = attachment_context(admission.attachments)
    teacher_message_content = admission.user_message.content
    use_itemwise = bool(admission.attachments) and not payload.is_refine
    history = (
        None
        if use_itemwise
        else bounded_history(
            session,
            item.id,
            exclude_attachments_for_message_id=admission.request_message_id,
            summary=item.summary,
            source_file_id=admission.source_file_id,
            analysis_revision=admission.base_revision,
            summary_through_message_id=item.summary_through_message_id,
        )
    )
    end_read_transaction(session)
    return ChatContext(
        template_commands=template_commands,
        rubric_context=rubric_context,
        machine_entries=machine_entries,
        machine_context=machine_context,
        template_key=template_key,
        environment_keys=environment_keys,
        prompt_attachment_context=prompt_attachment_context,
        teacher_message_content=teacher_message_content,
        use_itemwise=use_itemwise,
        history=history,
    )


def build_chat_assistant(
    session: Session,
    admission: ChatAdmission,
    generation: ChatGeneration,
    *,
    teaching_class_id: uuid.UUID,
    is_refine: bool,
    template_commands: list[TeacherJudgeTemplateCommand],
) -> tuple[TeacherJudgeSessionMessage, list[dict[str, Any]] | None]:
    """Assemble the assistant message; returns it with the proposal that survives checks."""
    file = admission.file
    reply = generation.reply
    proposal = generation.proposal
    # Without a selected rubric the conversation is general assistance only;
    # do not let an unconstrained model response create an unreviewed proposal.
    if file is None and proposal:
        reply = (
            "這項需求已具備自動檢查條件，但目前尚未選擇檢查表來源，"
            "因此無法建立可套用提案。請先選擇來源後再送出需求。"
        )
        proposal = None
    if proposal and file is not None:
        validate_proposal_machine_nodes(session, teaching_class_id, proposal)
    workflow: WorkflowMessage | None = None
    if is_refine and file is not None:
        workflow = refine_readiness_workflow(
            session,
            teaching_class_id=teaching_class_id,
            session_id=admission.item.id,
            file=file,
            proposal=proposal,
            template_commands=template_commands,
            analysis_revision=admission.base_revision,
            tool_calls=generation.tool_calls,
        )
        reply = workflow["content"]
    if admission.deadline_exceeded():
        raise HTTPException(status_code=504, detail="teacher_judge_workflow_timeout")
    assistant = TeacherJudgeSessionMessage(
        session_id=admission.item.id,
        role=TeacherJudgeMessageRole.assistant,
        content=redact_message_content(reply),
        message_type=TeacherJudgeMessageType.chat,
        metadata_json=build_assistant_metadata(
            metrics={**generation.metrics, "request_id": admission.ai_request_id},
            workflow=workflow,
            item_results=generation.item_results,
            itemwise_error=generation.itemwise_error,
            conversation_focus=generation.conversation_focus,
            tool_calls=generation.tool_calls,
            source_file_id=admission.source_file_id,
            analysis_revision=admission.base_revision,
            proposal=proposal,
            is_refine=is_refine,
        ),
    )
    return assistant, proposal


def persist_chat_reply(
    session: Session,
    admission: ChatAdmission,
    assistant: TeacherJudgeSessionMessage,
    *,
    user_id: uuid.UUID,
    is_refine: bool,
    proposal: list[dict[str, Any]] | None,
    metrics: VLLMMetrics,
) -> TeacherJudgeSessionChatResponse:
    """Revalidate the source, then save the answer, usage record and summary job."""
    item = admission.item
    user_message = admission.user_message
    # Source changes clear the conversation while this request may still be
    # waiting on the model.  Revalidate before saving the generated answer so
    # an old response cannot be attached to the new rubric context.
    session.refresh(item)
    ensure_active(item)
    current_file = selected_file_for_chat(session, item)
    if current_file is not None:
        session.refresh(current_file)
        current_file = selected_file_for_chat(session, item)
    request_exists = (
        session.exec(
            select(TeacherJudgeSessionMessage.id).where(
                TeacherJudgeSessionMessage.id == admission.request_message_id
            )
        ).first()
        is not None
    )
    if (
        not request_exists
        or (current_file.id if current_file else None) != admission.source_file_id
        or (current_file.analysis_revision if current_file else None)
        != admission.base_revision
    ):
        if request_exists:
            user_message.metadata_json = {
                **(user_message.metadata_json or {}),
                "processing": False,
            }
            session.add(user_message)
            session.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "teacher_judge_context_changed",
                "message": t("teacherJudgeSessions.analysisRevisionConflict"),
                "analysis_revision": current_file.analysis_revision
                if current_file
                else None,
            },
        )
    if admission.deadline_exceeded():
        failure = record_chat_failure(
            session,
            item,
            user_id=user_id,
            source_file_id=admission.source_file_id,
            analysis_revision=admission.base_revision,
            ai_request_id=admission.ai_request_id,
            ai_started=admission.ai_started,
            ai_started_at=admission.ai_started_at,
            status_code=504,
            error_message="workflow_timeout",
            request_message_id=admission.request_message_id,
        )
        raise HTTPException(status_code=504, detail=failure["content"])
    item.last_activity_at = get_datetime_utc()
    item.updated_at = item.last_activity_at
    user_message.metadata_json = {
        **(user_message.metadata_json or {}),
        "processing": False,
    }
    session.add_all([assistant, item, user_message])
    session.commit()
    session.refresh(assistant)
    record_ai_template_call(
        session=session,
        user_id=user_id,
        call_type="teacher_judge_chat",
        model_name=teacher_judge_settings.VLLM_MODEL_NAME,
        metrics={
            **metrics,
            "request_id": admission.ai_request_id,
            "usage_reported": bool(metrics.get("usage_reported", False)),
            "response_model": metrics.get("response_model"),
            "started_at": admission.ai_started_at,
            "completed_at": datetime.now(timezone.utc),
        },
    )
    try:
        schedule_summary(session, item, boundary_message_id=assistant.id)
    except Exception:
        logger.exception(
            "Unable to schedule Teacher Judge summary for %s", assistant.id
        )
    return TeacherJudgeSessionChatResponse(
        user_message=message_public(user_message, admission.attachments),
        assistant_message=message_public(assistant),
        rubric_proposal=([] if is_refine and proposal is None else proposal),
        base_revision=admission.base_revision,
    )
