"""Class-scoped persistent Teacher Judge session APIs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Literal

import anyio
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from sqlalchemy import case, exists, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, desc, select

from app.ai.teacher_judge.attachment_itemwise import analyze_attachments_itemwise
from app.ai.teacher_judge.attachment_service import (
    MAX_ATTACHMENT_COUNT,
    attachment_public,
    create_attachment,
    delete_attachment,
)
from app.ai.teacher_judge.automation_support import (
    ensure_script_generation_supported,
    get_script_generation_blockers,
)
from app.ai.teacher_judge.config import settings as teacher_judge_settings
from app.ai.teacher_judge.file_service import create_blank_file
from app.ai.teacher_judge.machine_context import (
    load_class_machine_nodes,
)
from app.ai.teacher_judge.schemas import (
    TeacherJudgeRubricAnalysis,
    TeacherJudgeRunBatchPublic,
    TeacherJudgeRunBatchSummary,
    TeacherJudgeRunTargetPage,
    TeacherJudgeScriptRunCreateRequest,
    TeacherJudgeScriptRunPublic,
    TeacherJudgeScriptRunSummary,
    TeacherJudgeScriptSetPublic,
    TeacherJudgeScriptSetRunRequest,
    TeacherJudgeSessionAttachmentUploadResponse,
    TeacherJudgeSessionChatResponse,
    TeacherJudgeSessionCreateRequest,
    TeacherJudgeSessionForkRequest,
    TeacherJudgeSessionMessageCreateRequest,
    TeacherJudgeSessionMessagePublic,
    TeacherJudgeSessionProgressPublic,
    TeacherJudgeSessionPublic,
    TeacherJudgeSessionScriptCreateRequest,
    TeacherJudgeSessionUpdateRequest,
    TeacherJudgeStudentReplyPublic,
    TeacherJudgeStudentReplyRequest,
    TeacherJudgeTargetReviewUpdate,
)
from app.ai.teacher_judge.script_artifact_service import (
    create_artifact_set,
    get_artifact_set,
    list_artifact_sets,
)
from app.ai.teacher_judge.script_executor_service import (
    _mark_run_executor_failed,
    execute_script_run,
    execute_script_run_batch,
)
from app.ai.teacher_judge.script_run_service import (
    create_script_run,
    create_script_run_batch,
    get_script_run_batch_public,
    get_script_run_public,
    get_session_run_for_review,
    get_session_run_record,
    list_run_targets,
    list_session_batch_summaries,
    list_session_run_summaries,
)
from app.ai.teacher_judge.script_run_service import (
    update_target_review as save_target_review,
)
from app.ai.teacher_judge.service import chat_with_rubric
from app.ai.teacher_judge.session_chat_service import (
    ChatAdmission,
    ChatContext,
    ChatGeneration,
    admit_chat_message,
    build_chat_assistant,
    load_chat_context,
    persist_chat_reply,
    recover_chat_failure,
    save_workflow_message,
)
from app.ai.teacher_judge.session_service import (
    clear_session_messages,
    delete_session_data,
    ensure_active,
    ensure_selected_file_available,
    ensure_week_published,
    finalize_cleared_attachments,
    fork_session_data,
    get_session,
    message_attachments_by_message_ids,
    message_public,
    require_selected_file,
    script_blocker_workflow_message,
    session_public,
    session_public_many,
    validate_selected_file,
    workflow_error_message,
)
from app.ai.teacher_judge.template_command_service import get_enabled_template_commands
from app.api.deps import InstructorUser, SessionDep
from app.core.authorizers import require_teaching_access
from app.core.db import run_db_in_threadpool
from app.core.i18n import t
from app.infrastructure.worker import submit
from app.models import TeachingClass, TeachingClassWeek
from app.models.base import get_datetime_utc
from app.models.teacher_judge_attachment import (
    TeacherJudgeMessageAttachment,
    TeacherJudgeSessionAttachment,
)
from app.models.teacher_judge_script_artifact import TeacherJudgeScriptArtifact
from app.models.teacher_judge_script_run import TeacherJudgeScriptRunTargetScope
from app.models.teacher_judge_session import (
    TeacherJudgeMessageRole,
    TeacherJudgeSession,
    TeacherJudgeSessionMessage,
    TeacherJudgeSessionStatus,
)
from app.services.course import ai_assignment_service

router = APIRouter(
    prefix="/teaching-classes/{teaching_class_id}/judge/sessions",
    tags=["teacher-judge"],
)

logger = logging.getLogger(__name__)


def _is_selected_file_conflict(exc: IntegrityError) -> bool:
    message = str(exc.orig or exc).lower()
    return "uq_teacher_judge_sessions_selected_file" in message or (
        "teacher_judge_sessions" in message and "selected_file_id" in message
    )


def _selected_file_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "teacher_judge_file_in_use",
            "message": t("teacherJudgeSessions.selectedFileInUse"),
        },
    )


def _save_script_set_failure(
    session: SessionDep,
    item: TeacherJudgeSession,
    *,
    detail: Any,
    stage: str,
    status_code: int | None,
    source_file_id: uuid.UUID | str | None,
    analysis_revision: int | None,
    created_by: uuid.UUID | None,
) -> None:
    """Persist a bounded script-set failure for Chat/history projection."""
    detail_dict = detail if isinstance(detail, dict) else {}
    if detail_dict.get("code") == "teacher_judge_check_plan_invalid":
        detail_dict = {
            **detail_dict,
            "items": [
                {
                    "item_id": issue.get("item_id"),
                    "title": " / ".join(
                        str(issue[key]) for key in ("item_id", "step_id") if issue.get(key)
                    ) or "檢查計畫",
                    "status": "analysis_error",
                    "missing_information": [],
                    "reason_code": "check_plan_contract_invalid",
                    "detail": issue.get("message"),
                }
                for issue in detail_dict.get("issues", [])
                if isinstance(issue, dict)
            ],
        }
    if isinstance(detail_dict.get("items"), list):
        outcome = script_blocker_workflow_message(
            detail_dict["items"],
            source_file_id=source_file_id,
            analysis_revision=analysis_revision,
            stage=stage,
            reason_code=str(detail_dict.get("code") or "teacher_judge_script_not_ready"),
        )
    else:
        reason_code = detail_dict.get("code")
        if reason_code == "teacher_judge_analysis_revision_conflict":
            reason_code = "analysis_revision_conflict"
        outcome = workflow_error_message(
            stage=stage,
            status_code=status_code,
            source_file_id=source_file_id,
            analysis_revision=analysis_revision,
            reason_code=reason_code if isinstance(reason_code, str) else None,
        )
    save_workflow_message(
        session,
        item,
        content=outcome["content"],
        metadata=outcome["metadata"],
        created_by=created_by,
    )


def _access(db: SessionDep, class_id: uuid.UUID, user: InstructorUser) -> None:
    teaching_class = db.get(TeachingClass, class_id)
    if not teaching_class:
        raise HTTPException(
            status_code=404, detail=t("teacherJudgeSessions.classNotFound")
        )
    require_teaching_access(user, teaching_class.owner_id)


def _validate_week(
    db: SessionDep, class_id: uuid.UUID, week_id: uuid.UUID | None
) -> None:
    if week_id is None:
        return
    week = db.get(TeachingClassWeek, week_id)
    if week is None or week.class_id != class_id:
        raise HTTPException(
            status_code=400, detail=t("teacherJudgeSessions.weekNotInClass")
        )


def _week_session(
    db: SessionDep,
    week_id: uuid.UUID,
    *,
    exclude_session_id: uuid.UUID | None = None,
) -> TeacherJudgeSession | None:
    query = select(TeacherJudgeSession).where(
        TeacherJudgeSession.teaching_class_week_id == week_id
    )
    if exclude_session_id is not None:
        query = query.where(TeacherJudgeSession.id != exclude_session_id)
    return db.exec(query.order_by(TeacherJudgeSession.created_at)).first()


def _require_free_week(
    db: SessionDep,
    class_id: uuid.UUID,
    week_id: uuid.UUID | None,
    *,
    exclude_session_id: uuid.UUID | None = None,
) -> None:
    """一週只能有一個對話：週次必填、屬於這個班級，而且還沒有別的對話。"""
    if week_id is None:
        raise HTTPException(
            status_code=400, detail=t("teacherJudgeSessions.weekRequired")
        )
    _validate_week(db, class_id, week_id)
    if _week_session(db, week_id, exclude_session_id=exclude_session_id):
        raise HTTPException(
            status_code=409, detail=t("teacherJudgeSessions.weekTaken")
        )


@router.get("/", response_model=list[TeacherJudgeSessionPublic])
def list_sessions(
    teaching_class_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
    status: TeacherJudgeSessionStatus = TeacherJudgeSessionStatus.active,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[TeacherJudgeSessionPublic]:
    _access(session, teaching_class_id, current_user)
    rows = session.exec(
        select(TeacherJudgeSession)
        .where(
            TeacherJudgeSession.teaching_class_id == teaching_class_id,
            TeacherJudgeSession.status == status,
        )
        .order_by(
            desc(case((col(TeacherJudgeSession.pinned_at).is_not(None), 1), else_=0)),
            desc(TeacherJudgeSession.pinned_at),
            desc(TeacherJudgeSession.last_activity_at),
            desc(TeacherJudgeSession.id),
        )
        .offset(skip)
        .limit(limit)
    ).all()
    return session_public_many(session, list(rows))


@router.post("/", response_model=TeacherJudgeSessionPublic)
def create_session(
    teaching_class_id: uuid.UUID,
    payload: TeacherJudgeSessionCreateRequest,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeSessionPublic:
    _access(session, teaching_class_id, current_user)
    try:
        _require_free_week(session, teaching_class_id, payload.teaching_class_week_id)
        selected_file_id = payload.selected_file_id
        if payload.creation_mode == "blank":
            rubric = create_blank_file(
                session=session,
                teaching_class_id=teaching_class_id,
                created_by=current_user.id,
                display_name=payload.rubric_name or "檢查表",
                environment_keys=payload.environment_keys or [],
            )
            selected_file_id = rubric.id
        else:
            validate_selected_file(session, teaching_class_id, selected_file_id)
            if selected_file_id is not None:
                ensure_selected_file_available(session, selected_file_id)
        item = TeacherJudgeSession(
            teaching_class_id=teaching_class_id,
            teaching_class_week_id=payload.teaching_class_week_id,
            title=payload.title.strip(),
            selected_file_id=selected_file_id,
            created_by=current_user.id,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return session_public(session, item)
    except IntegrityError as exc:
        session.rollback()
        if not _is_selected_file_conflict(exc):
            raise
        raise _selected_file_conflict() from exc
    except Exception:
        session.rollback()
        raise


@router.post("/{session_id}/fork", response_model=TeacherJudgeSessionPublic)
def fork_session(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    payload: TeacherJudgeSessionForkRequest,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeSessionPublic:
    _access(session, teaching_class_id, current_user)
    source = get_session(session, teaching_class_id, session_id)
    _require_free_week(session, teaching_class_id, payload.teaching_class_week_id)
    cloned = fork_session_data(
        session,
        source,
        title=payload.title,
        created_by=current_user.id,
        week_id=payload.teaching_class_week_id,
    )
    return session_public(session, cloned)


@router.put("/weeks/{week_id}", response_model=TeacherJudgeSessionPublic)
def ensure_week_session(
    teaching_class_id: uuid.UUID,
    week_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeSessionPublic:
    """取得這一週的對話，還沒有就建立一個空白的。

    老師點到一週、送出第一則訊息時才呼叫；同時按兩次也只會有一個對話。
    """
    _access(session, teaching_class_id, current_user)
    _validate_week(session, teaching_class_id, week_id)
    existing = _week_session(session, week_id)
    if existing is not None:
        return session_public(session, existing)
    week = session.get(TeachingClassWeek, week_id)
    title = (week.title or "").strip() or t(
        "teacherJudgeSessions.weekDefaultTitle", week=week.week_number
    )
    try:
        rubric = create_blank_file(
            session=session,
            teaching_class_id=teaching_class_id,
            created_by=current_user.id,
            display_name=title,
            environment_keys=[],
        )
        item = TeacherJudgeSession(
            teaching_class_id=teaching_class_id,
            teaching_class_week_id=week_id,
            title=title,
            selected_file_id=rubric.id,
            created_by=current_user.id,
        )
        session.add(item)
        session.commit()
    except IntegrityError:
        # 另一個請求剛好先建好了：回傳那一個，不要多一個對話
        session.rollback()
        existing = _week_session(session, week_id)
        if existing is None:
            raise
        return session_public(session, existing)
    session.refresh(item)
    return session_public(session, item)


@router.get("/{session_id}", response_model=TeacherJudgeSessionPublic)
def get_session_detail(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeSessionPublic:
    _access(session, teaching_class_id, current_user)
    return session_public(session, get_session(session, teaching_class_id, session_id))


@router.patch("/{session_id}", response_model=TeacherJudgeSessionPublic)
def update_session(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    payload: TeacherJudgeSessionUpdateRequest,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeSessionPublic:
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    changes = payload.model_fields_set
    if item.status == TeacherJudgeSessionStatus.archived and changes - {"status"}:
        raise HTTPException(
            status_code=409, detail=t("teacherJudgeSessions.archivedReadOnly")
        )
    if "title" in changes and payload.title is not None:
        item.title = payload.title.strip()
    if "teaching_class_week_id" in changes:
        _require_free_week(
            session,
            teaching_class_id,
            payload.teaching_class_week_id,
            exclude_session_id=item.id,
        )
        item.teaching_class_week_id = payload.teaching_class_week_id
    cleared_attachments: list[TeacherJudgeSessionAttachment] = []
    if "selected_file_id" in changes:
        validate_selected_file(session, teaching_class_id, payload.selected_file_id)
        if payload.selected_file_id is not None:
            ensure_selected_file_available(
                session,
                payload.selected_file_id,
                exclude_session_id=item.id,
            )
        if payload.selected_file_id != item.selected_file_id:
            cleared_attachments = clear_session_messages(session, item, commit=False)
        item.selected_file_id = payload.selected_file_id
    if payload.status is not None:
        item.status = TeacherJudgeSessionStatus(payload.status)
        if item.status == TeacherJudgeSessionStatus.archived:
            item.pinned_at = None
    if payload.is_pinned is not None:
        if item.status == TeacherJudgeSessionStatus.archived and payload.is_pinned:
            raise HTTPException(
                status_code=409, detail=t("teacherJudgeSessions.archivedCannotPin")
            )
        item.pinned_at = get_datetime_utc() if payload.is_pinned else None

    item.updated_at = get_datetime_utc()
    item.last_activity_at = item.updated_at
    session.add(item)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if not _is_selected_file_conflict(exc):
            raise
        raise _selected_file_conflict() from exc
    session.refresh(item)
    if cleared_attachments:
        finalize_cleared_attachments(cleared_attachments)
    return session_public(session, item)


@router.post("/{session_id}/archive", response_model=TeacherJudgeSessionPublic)
def archive_session(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeSessionPublic:
    return update_session(
        teaching_class_id,
        session_id,
        TeacherJudgeSessionUpdateRequest(status="archived"),
        session,
        current_user,
    )


@router.delete("/{session_id}", status_code=204)
def delete_session(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> None:
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    delete_session_data(session, item)


@router.post(
    "/{session_id}/attachments",
    response_model=TeacherJudgeSessionAttachmentUploadResponse,
)
def upload_session_attachment(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
    file: UploadFile = File(...),
) -> TeacherJudgeSessionAttachmentUploadResponse:
    # 刻意寫成同步 route：附件解析（pdfplumber 最多 200 頁、.doc 走 LibreOffice
    # 最長 30 秒）、寫檔與 DB commit 都是阻塞工作，交給 FastAPI 的 threadpool
    # 跑整個 handler，才不會卡住 event loop 上的其他請求與 VNC／教室 WebSocket。
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    ensure_active(item)
    pending_count = session.exec(
        select(func.count())
        .select_from(TeacherJudgeSessionAttachment)
        .where(
            TeacherJudgeSessionAttachment.session_id == item.id,
            ~exists().where(
                col(TeacherJudgeMessageAttachment.attachment_id)
                == col(TeacherJudgeSessionAttachment.id)
            ),
        )
    ).one()
    if pending_count >= MAX_ATTACHMENT_COUNT:
        raise HTTPException(
            status_code=400,
            detail=t(
                "teacherJudgeSessions.attachmentLimit", count=MAX_ATTACHMENT_COUNT
            ),
        )
    # 有上限地讀取：多讀 1 byte 即可讓 create_attachment 判定超限，
    # 不必先把整個（可能超大的）上傳檔載入記憶體
    max_upload_bytes = teacher_judge_settings.VLLM_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    file_bytes = file.file.read(max_upload_bytes + 1)
    try:
        attachment = create_attachment(
            session,
            session_id=item.id,
            uploaded_by=current_user.id,
            filename=file.filename,
            media_type=file.content_type,
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return TeacherJudgeSessionAttachmentUploadResponse(
        attachment=attachment_public(attachment)
    )


@router.delete("/{session_id}/attachments/{attachment_id}", status_code=204)
def delete_session_attachment(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    attachment_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> None:
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    ensure_active(item)
    attachment = session.get(TeacherJudgeSessionAttachment, attachment_id)
    if not attachment or attachment.session_id != item.id:
        raise HTTPException(
            status_code=404, detail=t("teacherJudgeSessions.attachmentNotFound")
        )
    delete_attachment(session, attachment)


@router.get(
    "/{session_id}/messages", response_model=list[TeacherJudgeSessionMessagePublic]
)
def list_messages(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
    before: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> list[TeacherJudgeSessionMessagePublic]:
    _access(session, teaching_class_id, current_user)
    get_session(session, teaching_class_id, session_id)
    query = select(TeacherJudgeSessionMessage).where(
        TeacherJudgeSessionMessage.session_id == session_id
    )
    if before:
        cursor = session.get(TeacherJudgeSessionMessage, before)
        if not cursor or cursor.session_id != session_id:
            raise HTTPException(
                status_code=400, detail=t("teacherJudgeSessions.invalidMessageCursor")
            )
        query = query.where(
            (TeacherJudgeSessionMessage.created_at < cursor.created_at)
            | (
                (TeacherJudgeSessionMessage.created_at == cursor.created_at)
                & (TeacherJudgeSessionMessage.id < cursor.id)
            )
        )
    rows = list(
        session.exec(
            query.order_by(
                desc(TeacherJudgeSessionMessage.created_at),
                desc(TeacherJudgeSessionMessage.id),
            ).limit(limit)
        )
    )
    rows.reverse()
    attachments_by_message_id = message_attachments_by_message_ids(
        session, [row.id for row in rows]
    )
    return [
        message_public(row, attachments_by_message_id.get(row.id, [])) for row in rows
    ]


@router.delete("/{session_id}/messages", response_model=TeacherJudgeSessionPublic)
def clear_messages(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeSessionPublic:
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    ensure_active(item)
    clear_session_messages(session, item)
    return session_public(session, item)


@router.delete("/{session_id}/messages/{message_id}/proposal", status_code=204)
def dismiss_message_proposal(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    message_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> None:
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    ensure_active(item)
    message = session.exec(
        select(TeacherJudgeSessionMessage).where(
            TeacherJudgeSessionMessage.id == message_id,
            TeacherJudgeSessionMessage.session_id == item.id,
            TeacherJudgeSessionMessage.role == TeacherJudgeMessageRole.assistant,
        )
    ).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Proposal message not found")
    message.metadata_json = {
        **(message.metadata_json or {}),
        "proposal_dismissed": True,
    }
    session.add(message)
    session.commit()


async def _generate_chat_reply(
    admission: ChatAdmission, context: ChatContext, *, is_refine: bool
) -> ChatGeneration:
    """Run the model for one admitted chat turn (attachments go itemwise)."""
    if context.use_itemwise:
        # Attachment analysis runs itemwise: extract source rows first, then
        # judge each row through the same isolated single-item chat core so
        # one row's Ready reasoning cannot leak into the other rows.
        itemwise = await analyze_attachments_itemwise(
            teacher_message=context.teacher_message_content,
            rubric_context=context.rubric_context,
            template_key=context.template_key,
            template_commands=context.template_commands,
            environment_keys=context.environment_keys,
            machine_context=context.machine_context,
            machine_entries=context.machine_entries,
            attachment_context=context.prompt_attachment_context,
            analysis_revision=admission.base_revision,
            rubric_available=admission.file is not None,
        )
        return ChatGeneration(
            reply=itemwise.reply,
            proposal=itemwise.proposal,
            metrics=itemwise.metrics,
            item_results=itemwise.item_results,
            itemwise_error=getattr(itemwise, "error", None),
        )
    chat_result = await chat_with_rubric(
        context.history or [],
        context.rubric_context,
        is_refine=is_refine,
        template_key=context.template_key,
        template_commands=context.template_commands,
        environment_keys=context.environment_keys,
        machine_context=context.machine_context,
        machine_entries=context.machine_entries,
        attachment_context=context.prompt_attachment_context,
        analysis_revision=admission.base_revision,
        rubric_available=admission.file is not None,
    )
    reply, proposal, metrics = chat_result
    focus = getattr(chat_result, "conversation_focus", None)
    return ChatGeneration(
        reply=reply,
        proposal=proposal,
        metrics=metrics,
        conversation_focus=focus if isinstance(focus, dict) else None,
        tool_calls=getattr(chat_result, "tool_calls", None),
    )


@router.post("/{session_id}/messages", response_model=TeacherJudgeSessionChatResponse)
async def create_message(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    payload: TeacherJudgeSessionMessageCreateRequest,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeSessionChatResponse:
    user_id = current_user.id
    staged: list[ChatAdmission] = []

    def recover_failure(status_code: int | None, error_message: str):
        return recover_chat_failure(
            session,
            staged[0] if staged else None,
            user_id=user_id,
            status_code=status_code,
            error_message=error_message,
        )

    def admit() -> ChatAdmission:
        _access(session, teaching_class_id, current_user)
        return admit_chat_message(
            session,
            teaching_class_id=teaching_class_id,
            session_id=session_id,
            payload=payload,
            user_id=user_id,
            on_staged=staged.append,
        )

    try:
        admission = await run_db_in_threadpool(admit)
        context = await run_db_in_threadpool(
            load_chat_context,
            session,
            admission,
            teaching_class_id=teaching_class_id,
            payload=payload,
        )
        try:
            generation = await asyncio.wait_for(
                _generate_chat_reply(admission, context, is_refine=payload.is_refine),
                timeout=admission.remaining_seconds(),
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504, detail="teacher_judge_workflow_timeout"
            ) from exc
        assistant, proposal = await run_db_in_threadpool(
            build_chat_assistant,
            session,
            admission,
            generation,
            teaching_class_id=teaching_class_id,
            is_refine=payload.is_refine,
            template_commands=context.template_commands,
        )
        return await run_db_in_threadpool(
            persist_chat_reply,
            session,
            admission,
            assistant,
            user_id=user_id,
            is_refine=payload.is_refine,
            proposal=proposal,
            metrics=generation.metrics,
        )
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await run_db_in_threadpool(recover_failure, 499, "client_disconnected")
        raise
    except HTTPException as exc:
        failure = await run_db_in_threadpool(
            recover_failure,
            exc.status_code,
            "workflow_timeout"
            if exc.detail == "teacher_judge_workflow_timeout"
            else f"http_{exc.status_code}",
        )
        if failure is None:
            raise
        raise HTTPException(
            status_code=exc.status_code,
            detail=failure["content"],
            headers=exc.headers,
        ) from exc
    except Exception as exc:
        logger.exception(
            "Teacher Judge message processing failed for session %s", session_id
        )
        await run_db_in_threadpool(recover_failure, None, str(exc))
        raise


def _session_rubric_for_script_set(
    *,
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
    expected_revision: int | None,
) -> tuple[TeacherJudgeSession, Any, TeacherJudgeRubricAnalysis]:
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    ensure_active(item)
    file = require_selected_file(session, item)
    if expected_revision is not None and expected_revision != file.analysis_revision:
        conflict = HTTPException(
            status_code=409,
            detail={
                "code": "teacher_judge_analysis_revision_conflict",
                "message": t("teacherJudgeSessions.analysisRevisionConflict"),
                "analysis_revision": file.analysis_revision,
            },
        )
        _save_script_set_failure(
            session,
            item,
            detail=conflict.detail,
            stage="persistence",
            status_code=conflict.status_code,
            source_file_id=file.id,
            analysis_revision=file.analysis_revision,
            created_by=current_user.id,
        )
        raise conflict
    rubric_analysis = TeacherJudgeRubricAnalysis.model_validate(file.analysis_json)
    commands = get_enabled_template_commands(
        session,
        file.template_key,
        include_cross_template=True,
    )
    if not rubric_analysis.items:
        not_ready = HTTPException(
            status_code=422,
            detail={
                "code": "teacher_judge_script_not_ready",
                "message": t("teacherJudgeSessions.noScriptableItems"),
                "items": get_script_generation_blockers(
                    rubric_analysis,
                    commands,
                    require_target_node=bool(
                        load_class_machine_nodes(session, teaching_class_id)
                    ),
                ),
            },
        )
        _save_script_set_failure(
            session,
            item,
            detail=not_ready.detail,
            stage="script_preflight",
            status_code=not_ready.status_code,
            source_file_id=file.id,
            analysis_revision=file.analysis_revision,
            created_by=current_user.id,
        )
        raise not_ready
    try:
        ensure_script_generation_supported(
            rubric_analysis,
            commands,
            require_target_node=bool(
                load_class_machine_nodes(session, teaching_class_id)
            ),
            require_typed_plan=True,
        )
    except HTTPException as exc:
        _save_script_set_failure(
            session,
            item,
            detail=exc.detail,
            stage="script_preflight",
            status_code=exc.status_code,
            source_file_id=file.id,
            analysis_revision=file.analysis_revision,
            created_by=current_user.id,
        )
        raise
    return item, file, rubric_analysis


@router.post(
    "/{session_id}/script-sets",
    response_model=TeacherJudgeScriptSetPublic,
)
async def create_session_script_set(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
    payload: TeacherJudgeSessionScriptCreateRequest | None = None,
) -> TeacherJudgeScriptSetPublic:
    def persist() -> TeacherJudgeScriptSetPublic:
        item, file, rubric_analysis = _session_rubric_for_script_set(
            teaching_class_id=teaching_class_id,
            session_id=session_id,
            session=session,
            current_user=current_user,
            expected_revision=payload.analysis_revision if payload else None,
        )
        return _generate_script_set(
            session=session,
            teaching_class_id=teaching_class_id,
            session_id=session_id,
            item=item,
            file=file,
            rubric_analysis=rubric_analysis,
            current_user=current_user,
            log_label="creation",
        )

    return await run_db_in_threadpool(persist)


def _generate_script_set(
    *,
    session: SessionDep,
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    item: Any,
    file: Any,
    rubric_analysis: TeacherJudgeRubricAnalysis,
    current_user: InstructorUser,
    log_label: str,
    artifact_set_id: uuid.UUID | None = None,
) -> TeacherJudgeScriptSetPublic:
    """產生（或重新產生）script set；失敗一律回滾並在 session 上留下失敗紀錄。"""
    try:
        script_set = create_artifact_set(
            session=session,
            teaching_class_id=teaching_class_id,
            session_id=session_id,
            name=item.title,
            template_key=file.template_key,
            rubric_analysis=rubric_analysis,
            source_analysis_revision=file.analysis_revision,
            created_by=current_user.id,
            source_file_id=file.id,
            artifact_set_id=artifact_set_id,
        )
    except HTTPException as exc:
        session.rollback()
        _save_script_set_failure(
            session,
            item,
            detail=exc.detail,
            stage="script_generation",
            status_code=exc.status_code,
            source_file_id=file.id,
            analysis_revision=file.analysis_revision,
            created_by=current_user.id,
        )
        raise
    except Exception:
        session.rollback()
        logger.exception(
            "Teacher Judge script set %s failed for session %s", log_label, item.id
        )
        _save_script_set_failure(
            session,
            item,
            detail=None,
            stage="script_generation",
            status_code=None,
            source_file_id=file.id,
            analysis_revision=file.analysis_revision,
            created_by=current_user.id,
        )
        raise
    return script_set


@router.get(
    "/{session_id}/script-sets",
    response_model=list[TeacherJudgeScriptSetPublic],
)
def list_session_script_sets(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> list[TeacherJudgeScriptSetPublic]:
    _access(session, teaching_class_id, current_user)
    get_session(session, teaching_class_id, session_id)
    return list_artifact_sets(
        session=session,
        teaching_class_id=teaching_class_id,
        session_id=session_id,
    )


@router.get(
    "/{session_id}/script-sets/{artifact_set_id}",
    response_model=TeacherJudgeScriptSetPublic,
)
def get_session_script_set(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    artifact_set_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeScriptSetPublic:
    _access(session, teaching_class_id, current_user)
    get_session(session, teaching_class_id, session_id)
    return get_artifact_set(
        session=session,
        teaching_class_id=teaching_class_id,
        artifact_set_id=artifact_set_id,
        session_id=session_id,
    )


@router.post(
    "/{session_id}/script-sets/{artifact_set_id}/regenerate",
    response_model=TeacherJudgeScriptSetPublic,
)
async def regenerate_session_script_set(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    artifact_set_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
    payload: TeacherJudgeSessionScriptCreateRequest | None = None,
) -> TeacherJudgeScriptSetPublic:
    def persist() -> TeacherJudgeScriptSetPublic:
        item, file, rubric_analysis = _session_rubric_for_script_set(
            teaching_class_id=teaching_class_id,
            session_id=session_id,
            session=session,
            current_user=current_user,
            expected_revision=payload.analysis_revision if payload else None,
        )
        existing = get_artifact_set(
            session=session,
            teaching_class_id=teaching_class_id,
            artifact_set_id=artifact_set_id,
            session_id=session_id,
        )
        if existing.source_file_id != str(file.id):
            mismatch = HTTPException(
                status_code=409,
                detail={
                    "code": "teacher_judge_script_set_source_mismatch",
                    "message": t("teacherJudgeSessions.scriptSetSourceMismatch"),
                },
            )
            _save_script_set_failure(
                session,
                item,
                detail=mismatch.detail,
                stage="persistence",
                status_code=mismatch.status_code,
                source_file_id=file.id,
                analysis_revision=file.analysis_revision,
                created_by=current_user.id,
            )
            raise mismatch
        return _generate_script_set(
            session=session,
            teaching_class_id=teaching_class_id,
            session_id=session_id,
            item=item,
            file=file,
            rubric_analysis=rubric_analysis,
            current_user=current_user,
            log_label="regeneration",
            artifact_set_id=artifact_set_id,
        )

    return await run_db_in_threadpool(persist)


@router.post(
    "/{session_id}/script-sets/{artifact_set_id}/runs",
    response_model=TeacherJudgeRunBatchPublic,
)
def create_session_script_set_run(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    artifact_set_id: uuid.UUID,
    payload: TeacherJudgeScriptSetRunRequest,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeRunBatchPublic:
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    ensure_active(item)
    ensure_week_published(session, item)
    get_artifact_set(
        session=session,
        teaching_class_id=teaching_class_id,
        artifact_set_id=artifact_set_id,
        session_id=session_id,
    )
    if payload.target_scope not in {"all_students_in_set", "students"}:
        raise HTTPException(
            status_code=422, detail=t("teacherJudgeSessions.unsupportedRunScope")
        )
    batch = create_script_run_batch(
        session=session,
        teaching_class_id=teaching_class_id,
        artifact_set_id=artifact_set_id,
        started_by=current_user.id,
        session_id=session_id,
        user_ids=payload.user_ids if payload.target_scope == "students" else None,
        run_batch_id=payload.run_batch_id,
    )
    execution = execute_script_run_batch(uuid.UUID(batch.run_batch_id))
    try:
        task_id = submit(
            execution,
            name=f"teacher_judge_script_run_batch:{batch.run_batch_id}",
            task_id=f"teacher_judge_script_run_batch:{batch.run_batch_id}",
        )
    except Exception:
        execution.close()
        logger.exception("Teacher Judge batch dispatch failed batch=%s", batch.run_batch_id)
        task_id = ""
    if task_id == "":
        for node in batch.nodes:
            _mark_run_executor_failed(uuid.UUID(node.run_id), "背景執行器未接受任務。", reason_code="executor_unavailable")
        session.expire_all()
        return get_script_run_batch_public(
            session=session, teaching_class_id=teaching_class_id,
            run_batch_id=uuid.UUID(batch.run_batch_id), session_id=session_id,
        )
    return batch


@router.get(
    "/{session_id}/run-batches/{run_batch_id}",
    response_model=TeacherJudgeRunBatchPublic,
)
def get_session_script_run_batch(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    run_batch_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeRunBatchPublic:
    _access(session, teaching_class_id, current_user)
    get_session(session, teaching_class_id, session_id)
    return get_script_run_batch_public(
        session=session,
        teaching_class_id=teaching_class_id,
        run_batch_id=run_batch_id,
        session_id=session_id,
    )


@router.put(
    "/{session_id}/students/{student_id}/reply",
    response_model=TeacherJudgeStudentReplyPublic,
)
def save_student_reply(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    student_id: uuid.UUID,
    payload: TeacherJudgeStudentReplyRequest,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeStudentReplyPublic:
    """老師給一位學生這週的回覆；再回覆覆蓋前一則，空白＝不回覆。"""
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    ensure_active(item)
    return TeacherJudgeStudentReplyPublic(
        **ai_assignment_service.save_student_reply(
            session,
            item,
            student_id=student_id,
            feedback=payload.feedback,
            teacher_id=current_user.id,
        )
    )


@router.get("/{session_id}/progress", response_model=TeacherJudgeSessionProgressPublic)
def get_session_progress(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeSessionProgressPublic:
    """全班每位學生在這週檢查回報完成到哪裡；執行結果另由 run-batches 提供。"""
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    return TeacherJudgeSessionProgressPublic.model_validate(
        ai_assignment_service.session_progress(session, item)
    )


@router.get("/{session_id}/run-batches", response_model=list[TeacherJudgeRunBatchSummary])
def list_session_batches(
    teaching_class_id: uuid.UUID, session_id: uuid.UUID,
    session: SessionDep, current_user: InstructorUser,
    skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
    artifact_set_id: uuid.UUID | None = None,
) -> list[TeacherJudgeRunBatchSummary]:
    _access(session, teaching_class_id, current_user)
    get_session(session, teaching_class_id, session_id)
    return list_session_batch_summaries(session, teaching_class_id, session_id, skip, limit, artifact_set_id)


@router.get("/{session_id}/runs/{run_id}/targets", response_model=TeacherJudgeRunTargetPage)
def list_session_run_targets(
    teaching_class_id: uuid.UUID, session_id: uuid.UUID, run_id: uuid.UUID,
    session: SessionDep, current_user: InstructorUser,
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
    status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = None,
    student_id: uuid.UUID | None = None, vmid: int | None = Query(None, ge=1),
) -> TeacherJudgeRunTargetPage:
    _access(session, teaching_class_id, current_user)
    run = get_session_run_record(session, teaching_class_id, session_id, run_id)
    return list_run_targets(session, run, skip=skip, limit=limit, status=status, student_id=student_id, vmid=vmid)


@router.get("/{session_id}/runs", response_model=list[TeacherJudgeScriptRunSummary])
def list_session_runs(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    artifact_set_id: uuid.UUID | None = None,
) -> list[TeacherJudgeScriptRunSummary]:
    _access(session, teaching_class_id, current_user)
    get_session(session, teaching_class_id, session_id)
    return list_session_run_summaries(
        session, teaching_class_id, session_id, skip, limit, artifact_set_id
    )


@router.get("/{session_id}/runs/{run_id}", response_model=TeacherJudgeScriptRunPublic)
def get_session_run(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeScriptRunPublic:
    _access(session, teaching_class_id, current_user)
    get_session(session, teaching_class_id, session_id)
    return get_session_run_for_review(session, teaching_class_id, session_id, run_id)


def _update_target_review(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: TeacherJudgeTargetReviewUpdate,
    session: SessionDep,
    current_user: InstructorUser,
    *,
    vmid: int | None = None,
    student_id: str | None = None,
) -> TeacherJudgeScriptRunPublic:
    _access(session, teaching_class_id, current_user)
    get_session(session, teaching_class_id, session_id)
    run = get_session_run_record(session, teaching_class_id, session_id, run_id)
    return save_target_review(
        session,
        run,
        vmid=vmid,
        student_id=student_id,
        feedback=payload.feedback,
        decisions=dict(payload.decisions),
        reviewer_id=current_user.id,
    )


@router.patch(
    "/{session_id}/runs/{run_id}/targets/{vmid}/review",
    response_model=TeacherJudgeScriptRunPublic,
)
def update_target_review(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    vmid: int,
    payload: TeacherJudgeTargetReviewUpdate,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeScriptRunPublic:
    """Save a review for a target that has an assigned VM."""

    return _update_target_review(
        teaching_class_id,
        session_id,
        run_id,
        payload,
        session,
        current_user,
        vmid=vmid,
    )


@router.patch(
    "/{session_id}/runs/{run_id}/students/{student_id}/review",
    response_model=TeacherJudgeScriptRunPublic,
)
def update_student_target_review(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    student_id: str,
    payload: TeacherJudgeTargetReviewUpdate,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeScriptRunPublic:
    """Save a review when preflight failed before a VMID was available."""

    return _update_target_review(
        teaching_class_id,
        session_id,
        run_id,
        payload,
        session,
        current_user,
        student_id=student_id,
    )


@router.post(
    "/{session_id}/scripts/{artifact_id}/runs",
    response_model=TeacherJudgeScriptRunPublic,
)
def create_session_run(
    teaching_class_id: uuid.UUID,
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    payload: TeacherJudgeScriptRunCreateRequest,
    session: SessionDep,
    current_user: InstructorUser,
) -> TeacherJudgeScriptRunPublic:
    _access(session, teaching_class_id, current_user)
    item = get_session(session, teaching_class_id, session_id)
    ensure_active(item)
    artifact = session.get(TeacherJudgeScriptArtifact, artifact_id)
    if (
        not artifact
        or artifact.teaching_class_id != teaching_class_id
        or artifact.session_id != session_id
    ):
        raise HTTPException(
            status_code=404, detail=t("teacherJudgeSessions.scriptNotFound")
        )
    ensure_week_published(session, item)
    run = create_script_run(
        session=session,
        teaching_class_id=teaching_class_id,
        artifact_id=artifact_id,
        target_scope=TeacherJudgeScriptRunTargetScope(payload.target_scope),
        target_vmids=payload.target_vmids,
        started_by=current_user.id,
        target_node_key=payload.target_node_key,
    )
    item.last_activity_at = get_datetime_utc()
    item.updated_at = item.last_activity_at
    session.add(item)
    session.commit()
    task_id = submit(
        execute_script_run(uuid.UUID(run.id)),
        name=f"teacher_judge_script_run:{run.id}",
        task_id=f"teacher_judge_script_run:{run.id}",
    )
    if task_id == "":
        _mark_run_executor_failed(uuid.UUID(run.id), "背景執行器未接受任務。", reason_code="executor_unavailable")
        session.expire_all()
    return get_script_run_public(
        session=session,
        teaching_class_id=teaching_class_id,
        artifact_id=artifact_id,
        run_id=uuid.UUID(run.id),
    )
