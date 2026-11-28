"""課程學習 API（學生端）。

學生的「課程」就是他修的班級：路徑裡的 ``class_id`` 是班級 id。班級不存在、
還沒開放給學生或學生不在名單上，一律回 404。
"""

import uuid

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models.teaching_class import (
    TeachingClass,
    TeachingClassMachineNode,
    TeachingClassStudent,
    TeachingClassStudentMachine,
)
from app.schemas.course import (
    CourseAIAssignmentStudent,
    CourseAICheckStudent,
    CourseAICompletionStudent,
    CourseAICompletionUpdate,
    CourseClassStudent,
    CoursePracticeMachineStudent,
    CourseReminderStudent,
    CourseScheduleStudent,
    CourseWeeklyTaskStudent,
)
from app.services.course import (
    ai_assignment_service,
    course_service,
    reminder_service,
    weekly_task_service,
)
from app.services.teaching import course_publication_service

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("/schedule", response_model=list[CourseScheduleStudent])
def list_schedule(
    session: SessionDep,
    current_user: CurrentUser,
) -> list[CourseScheduleStudent]:
    """Return this student's active-term classes with today's session state."""

    return course_service.list_student_schedule(
        session,
        user_id=current_user.id,
    )


@router.get("/reminders", response_model=list[CourseReminderStudent])
def list_reminders(
    session: SessionDep,
    current_user: CurrentUser,
) -> list[CourseReminderStudent]:
    """Build the student's actionable reminders from current platform data."""

    return reminder_service.list_student_reminders(
        session,
        user_id=current_user.id,
    )


@router.get("/classes", response_model=list[CourseClassStudent])
def list_classes(
    session: SessionDep, current_user: CurrentUser
) -> list[CourseClassStudent]:
    return course_service.list_student_classes(session, user_id=current_user.id)


@router.get("/classes/{class_id}", response_model=CourseClassStudent)
def get_class(
    session: SessionDep, current_user: CurrentUser, class_id: uuid.UUID
) -> CourseClassStudent:
    return course_service.get_student_class_detail(
        session, user_id=current_user.id, class_id=class_id
    )


@router.get(
    "/classes/{class_id}/ai-assignments",
    response_model=list[CourseAIAssignmentStudent],
)
def list_ai_assignments(
    session: SessionDep, current_user: CurrentUser, class_id: uuid.UUID
) -> list[CourseAIAssignmentStudent]:
    return ai_assignment_service.list_student_ai_assignments(
        session,
        user_id=current_user.id,
        class_id=class_id,
    )


@router.get(
    "/classes/{class_id}/weekly-tasks",
    response_model=list[CourseWeeklyTaskStudent],
)
def list_weekly_tasks(
    session: SessionDep, current_user: CurrentUser, class_id: uuid.UUID
) -> list[CourseWeeklyTaskStudent]:
    return weekly_task_service.list_student_weekly_tasks(
        session,
        user_id=current_user.id,
        class_id=class_id,
    )


@router.get(
    "/classes/{class_id}/weekly-tasks/{week_id}/files/{file_id}",
    response_class=FileResponse,
)
def get_weekly_task_pdf(
    session: SessionDep,
    current_user: CurrentUser,
    class_id: uuid.UUID,
    week_id: uuid.UUID,
    file_id: uuid.UUID,
) -> FileResponse:
    path, filename = weekly_task_service.get_student_weekly_task_pdf(
        session,
        user_id=current_user.id,
        class_id=class_id,
        week_id=week_id,
        file_id=file_id,
    )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
        content_disposition_type="inline",
    )


@router.get(
    "/classes/{class_id}/practice-machines",
    response_model=list[CoursePracticeMachineStudent],
)
def list_practice_machines(
    session: SessionDep,
    current_user: CurrentUser,
    class_id: uuid.UUID,
) -> list[CoursePracticeMachineStudent]:
    """List the machines assigned to this student in one of their classes."""

    teaching_class = course_service.get_student_class_or_404(
        session,
        user_id=current_user.id,
        class_id=class_id,
    )
    rows = session.exec(
        select(
            TeachingClass,
            TeachingClassStudentMachine,
            TeachingClassMachineNode,
        )
        .join(
            TeachingClassStudent,
            TeachingClassStudent.class_id == TeachingClass.id,
        )
        .join(
            TeachingClassStudentMachine,
            TeachingClassStudentMachine.class_student_id == TeachingClassStudent.id,
        )
        .join(
            TeachingClassMachineNode,
            TeachingClassStudentMachine.machine_node_id == TeachingClassMachineNode.id,
        )
        .where(
            TeachingClass.id == teaching_class.id,
            TeachingClassStudent.user_id == current_user.id,
            TeachingClassStudent.status == "active",
        )
        .order_by(TeachingClass.name, TeachingClassMachineNode.sort_order)
    ).all()
    vmids = [machine.vmid for _teaching_class, machine, _node in rows if machine.vmid]
    public_urls = course_publication_service.public_urls_by_vmid(session, vmids)
    forward_endpoints = course_publication_service.forward_endpoints_by_vmid(
        session, vmids
    )
    return [
        CoursePracticeMachineStudent(
            teaching_class_id=teaching_class.id,
            teaching_class_name=teaching_class.name,
            machine_node_id=node.id,
            node_key=node.node_key,
            name=node.name,
            role=node.role,
            resource_type=node.resource_type,
            vmid=machine.vmid,
            status=machine.status,
            public_url=public_urls.get(machine.vmid) if machine.vmid else None,
            forward_endpoints=(
                forward_endpoints.get(machine.vmid, []) if machine.vmid else []
            ),
        )
        for teaching_class, machine, node in rows
    ]


@router.get(
    "/classes/{class_id}/ai-assignments/{assignment_id}/source-document",
    response_class=FileResponse,
)
def get_ai_assignment_source_document(
    session: SessionDep,
    current_user: CurrentUser,
    class_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> FileResponse:
    """Preview the uploaded PDF tied to an approved assignment."""

    path, filename = ai_assignment_service.get_student_ai_assignment_source_document(
        session,
        user_id=current_user.id,
        class_id=class_id,
        assignment_id=assignment_id,
    )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
        content_disposition_type="inline",
    )


@router.put(
    "/classes/{class_id}/ai-assignments/{assignment_id}/completion",
    response_model=CourseAICompletionStudent,
)
def update_ai_assignment_completion(
    session: SessionDep,
    current_user: CurrentUser,
    class_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: CourseAICompletionUpdate,
) -> CourseAICompletionStudent:
    """Record completion only; teachers decide when to run the final check."""

    return ai_assignment_service.update_student_completion(
        session,
        user_id=current_user.id,
        class_id=class_id,
        assignment_id=assignment_id,
        item_id=body.item_id,
        completed=body.completed,
    )


@router.get(
    "/classes/{class_id}/ai-assignments/{assignment_id}/checks/{run_id}",
    response_model=CourseAICheckStudent,
)
def get_ai_check(
    session: SessionDep,
    current_user: CurrentUser,
    class_id: uuid.UUID,
    assignment_id: uuid.UUID,
    run_id: uuid.UUID,
) -> CourseAICheckStudent:
    return ai_assignment_service.get_student_ai_check(
        session,
        user_id=current_user.id,
        class_id=class_id,
        assignment_id=assignment_id,
        run_id=run_id,
    )
