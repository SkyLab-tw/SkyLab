from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Resource,
    TeachingClass,
    TeachingClassStatus,
    TeachingClassStudent,
    TeachingClassTaskFile,
    TeachingClassWeek,
    User,
    UserRole,
    VMRequest,
    VMRequestStatus,
)
from app.models.teacher_judge_file import TeacherJudgeFile
from app.models.teacher_judge_script_artifact import (
    TeacherJudgeScriptArtifact,
    TeacherJudgeScriptStatus,
)
from app.models.teacher_judge_session import TeacherJudgeSession
from app.services.course import ai_assignment_service, weekly_task_service
from app.services.course.course_service import (
    get_student_class_detail,
    list_student_classes,
    list_student_schedule,
)
from app.services.course.reminder_service import list_student_reminders


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _user(email: str, role: UserRole) -> User:
    return User(
        email=email,
        role=role,
        full_name="陳老師" if role == UserRole.teacher else "王同學",
        hashed_password="test",
    )


def _linked_class(
    session: Session,
    *,
    teacher: User,
    student: User,
    session_date: date,
) -> TeachingClass:
    """一個已經開放給學生（曾經可以上課）的班級，學生在名單上。"""
    teaching_class = TeachingClass(
        name="Linux 系統管理實務",
        code="linux-a",
        term="2026-1",
        location="電腦教室 A",
        owner_id=teacher.id,
        start_date=session_date - timedelta(days=7),
        end_date=session_date + timedelta(days=30),
        weekday=session_date.weekday(),
        start_time=time(9),
        end_time=time(11),
        status=TeachingClassStatus.active,
        first_active_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    session.add(teacher)
    session.add(student)
    session.add(teaching_class)
    session.commit()
    session.add(TeachingClassStudent(class_id=teaching_class.id, user_id=student.id))
    session.commit()
    return teaching_class


def test_course_list_only_includes_opened_classes_for_active_enrollments() -> None:
    with _session() as session:
        teacher = _user("teacher@example.edu", UserRole.teacher)
        student = _user("student@example.edu", UserRole.student)
        other_student = _user("other@example.edu", UserRole.student)
        teaching_class = _linked_class(
            session, teacher=teacher, student=student, session_date=date(2026, 8, 25)
        )
        session.refresh(teaching_class)
        other_class = TeachingClass(
            **{
                **teaching_class.model_dump(exclude={"id", "code"}),
                "code": "other-class",
            }
        )
        session.add(other_class)
        session.add(other_student)
        session.flush()
        session.add(
            TeachingClassStudent(class_id=other_class.id, user_id=other_student.id)
        )
        session.commit()

        own = list_student_classes(session, user_id=student.id)
        assert [(row.id, row.title) for row in own] == [
            (teaching_class.id, "Linux 系統管理實務")
        ]
        assert [
            row.id for row in list_student_classes(session, user_id=other_student.id)
        ] == [other_class.id]
        assert list_student_classes(session, user_id=teacher.id) == []

        # 班級還沒第一次可以上課：學生看不到這門課
        opened_at = teaching_class.first_active_at
        teaching_class.first_active_at = None
        session.add(teaching_class)
        session.commit()
        assert list_student_classes(session, user_id=student.id) == []
        teaching_class.first_active_at = opened_at
        session.add(teaching_class)
        session.commit()
        assert len(list_student_classes(session, user_id=student.id)) == 1

        enrollment = session.exec(
            select(TeachingClassStudent).where(
                TeachingClassStudent.user_id == student.id,
            )
        ).one()
        enrollment.status = "removed"
        session.add(enrollment)
        session.commit()
        assert list_student_classes(session, user_id=student.id) == []


def test_schedule_uses_real_class_time_teacher_and_location() -> None:
    session = _session()
    teacher = _user("teacher@example.edu", UserRole.teacher)
    student = _user("student@example.edu", UserRole.student)
    local_date = date(2026, 8, 25)
    teaching_class = _linked_class(
        session,
        teacher=teacher,
        student=student,
        session_date=local_date,
    )

    rows = list_student_schedule(
        session,
        user_id=student.id,
        now=datetime(2026, 8, 25, 1, 30, tzinfo=UTC),
    )

    assert len(rows) == 1
    assert rows[0].id == teaching_class.id
    assert rows[0].state == "now"
    assert rows[0].teacher == "陳老師"
    assert rows[0].location == "電腦教室 A"
    assert rows[0].start_at.hour == 9


def test_schedule_keeps_active_course_visible_outside_its_class_day() -> None:
    session = _session()
    teacher = _user("teacher@example.edu", UserRole.teacher)
    student = _user("student@example.edu", UserRole.student)
    monday = date(2026, 8, 24)
    teaching_class = _linked_class(
        session,
        teacher=teacher,
        student=student,
        session_date=monday,
    )
    teaching_class.weekday = 3
    session.add(teaching_class)
    session.commit()

    rows = list_student_schedule(
        session,
        user_id=student.id,
        now=datetime(2026, 8, 24, 2, 0, tzinfo=UTC),
    )

    assert len(rows) == 1
    assert rows[0].id == teaching_class.id
    assert rows[0].state == "available"
    assert rows[0].label == "可課後練習"
    assert rows[0].session_date == date(2026, 8, 27)


@pytest.mark.parametrize("active", [True, False], ids=["active-set", "no-active-set"])
def test_weekly_tasks_only_show_published_content_and_pdf(
    tmp_path, monkeypatch, active: bool
) -> None:
    session = _session()
    teacher = _user("teacher@example.edu", UserRole.teacher)
    student = _user("student@example.edu", UserRole.student)
    today = date(2026, 8, 25)
    teaching_class = _linked_class(
        session,
        teacher=teacher,
        student=student,
        session_date=today,
    )
    published = TeachingClassWeek(
        class_id=teaching_class.id,
        week_number=1,
        session_date=today,
        title="Linux 權限任務",
        target_node_key="main",
        status="published",
    )
    draft = TeachingClassWeek(
        class_id=teaching_class.id,
        week_number=2,
        session_date=today + timedelta(days=7),
        title="尚未公開任務",
        status="draft",
    )
    session.add(published)
    session.add(draft)
    session.commit()
    task_file = TeachingClassTaskFile(
        week_id=published.id,
        filename="permissions.pdf",
        storage_key="permissions.task",
    )
    session.add(task_file)
    artifact_set_id = uuid.uuid4()
    judge_session = TeacherJudgeSession(
        teaching_class_id=teaching_class.id,
        teaching_class_week_id=published.id,
        title="Linux 權限檢查",
        # 核准狀態不足以發布檢查點，對話必須明確指定生效腳本組。
        active_artifact_set_id=artifact_set_id if active else None,
    )
    session.add(judge_session)
    session.flush()
    session.add(
        TeacherJudgeScriptArtifact(
            teaching_class_id=teaching_class.id,
            session_id=judge_session.id,
            artifact_set_id=artifact_set_id,
            target_node_key="main",
            name="Linux 權限檢查",
            template_key="linux",
            rubric_snapshot_json={
                "items": [
                    {"id": "mode", "title": "確認權限模式", "detectable": "auto"},
                    {"id": "owner", "title": "確認檔案擁有者", "detectable": "auto"},
                ]
            },
            script_content="print('{}')",
            status=TeacherJudgeScriptStatus.approved,
        )
    )
    session.commit()
    (tmp_path / "permissions.task").write_bytes(b"%PDF-1.4 test")
    monkeypatch.setattr(weekly_task_service, "TASK_FILE_ROOT", tmp_path)

    rows = weekly_task_service.list_student_weekly_tasks(
        session,
        user_id=student.id,
        class_id=teaching_class.id,
    )
    stored_path, filename = weekly_task_service.get_student_weekly_task_pdf(
        session,
        user_id=student.id,
        class_id=teaching_class.id,
        week_id=published.id,
        file_id=task_file.id,
    )

    assert [row.title for row in rows] == ["Linux 權限任務"]
    assert not hasattr(rows[0], "target_node_key")
    assert rows[0].files[0].filename == "permissions.pdf"
    assert [item.title for item in rows[0].checkpoints] == (
        ["確認權限模式", "確認檔案擁有者"] if active else []
    )
    assignments = ai_assignment_service.list_student_ai_assignments(
        session, user_id=student.id, class_id=teaching_class.id
    )
    assert [item.title for row in assignments for item in row.items] == [
        item.title for item in rows[0].checkpoints
    ]
    assert [row.teaching_class_week_id for row in assignments] == (
        [rows[0].id] if active else []
    )
    for item in rows[0].checkpoints:
        assert item.assignment_id == judge_session.id
        assert item.check_available is True
        assert item.machine_node_key == "main"
    assert stored_path == tmp_path / "permissions.task"
    assert filename == "permissions.pdf"


def test_weekly_tasks_hide_ai_extracted_items_before_script_is_approved() -> None:
    session = _session()
    teacher = _user("teacher@example.edu", UserRole.teacher)
    student = _user("student@example.edu", UserRole.student)
    teaching_class = _linked_class(
        session,
        teacher=teacher,
        student=student,
        session_date=date(2026, 8, 25),
    )
    week = TeachingClassWeek(
        class_id=teaching_class.id,
        week_number=1,
        session_date=date(2026, 8, 25),
        title="Week one task",
        status="published",
    )
    source = TeacherJudgeFile(
        teaching_class_id=teaching_class.id,
        uploaded_by=teacher.id,
        original_filename="week-one.pdf",
        display_name="Week one AI task",
        template_key="linux",
        analysis_json={
            "items": [
                {
                    "id": "boot",
                    "title": "Boot the machine",
                    "description": "Start the assigned Linux machine.",
                    "detectable": "auto",
                }
            ]
        },
    )
    session.add(week)
    session.add(source)
    session.commit()
    judge = TeacherJudgeSession(
        teaching_class_id=teaching_class.id,
        teaching_class_week_id=week.id,
        selected_file_id=source.id,
        created_by=teacher.id,
        title="Week one AI check",
    )
    session.add(judge)
    session.commit()

    rows = weekly_task_service.list_student_weekly_tasks(
        session,
        user_id=student.id,
        class_id=teaching_class.id,
    )

    assert len(rows) == 1
    assert rows[0].checkpoints == []
    assert rows[0].source_documents == []


def test_weekly_tasks_show_published_pdf_without_ai_check() -> None:
    session = _session()
    teacher = _user("teacher@example.edu", UserRole.teacher)
    student = _user("student@example.edu", UserRole.student)
    teaching_class = _linked_class(
        session,
        teacher=teacher,
        student=student,
        session_date=date(2026, 8, 25),
    )
    week = TeachingClassWeek(
        class_id=teaching_class.id,
        week_number=1,
        session_date=date(2026, 8, 25),
        title="Week one reading",
        status="published",
    )
    session.add(week)
    session.commit()
    session.add(
        TeachingClassTaskFile(
            week_id=week.id,
            filename="week-one.pdf",
            storage_key="week-one.task",
        )
    )
    session.commit()

    rows = weekly_task_service.list_student_weekly_tasks(
        session,
        user_id=student.id,
        class_id=teaching_class.id,
    )

    assert len(rows) == 1
    assert rows[0].title == "Week one reading"
    assert [task_file.filename for task_file in rows[0].files] == ["week-one.pdf"]
    assert rows[0].checkpoints == []


def test_reminders_derive_expiry_review_and_class_task() -> None:
    session = _session()
    teacher = _user("teacher@example.edu", UserRole.teacher)
    student = _user("student@example.edu", UserRole.student)
    today = date(2026, 8, 25)
    teaching_class = _linked_class(
        session,
        teacher=teacher,
        student=student,
        session_date=today,
    )
    reviewed_at = datetime(2026, 8, 25, 0, 30, tzinfo=UTC)
    request = VMRequest(
        user_id=student.id,
        reason="研究",
        resource_type="lxc",
        hostname="student-lab",
        password="test-password",
        status=VMRequestStatus.approved,
        reviewed_at=reviewed_at,
        created_at=reviewed_at - timedelta(days=1),
    )
    session.add(request)
    session.commit()
    session.add(
        Resource(
            vmid=201,
            request_id=request.id,
            user_id=student.id,
            environment_type="LXC",
            expiry_date=today + timedelta(days=2),
            created_at=reviewed_at,
        )
    )
    session.add(
        TeachingClassWeek(
            class_id=teaching_class.id,
            week_number=1,
            session_date=today,
            title="完成檔案權限 Checkpoint",
            status="published",
        )
    )
    session.commit()

    rows = list_student_reminders(
        session,
        user_id=student.id,
        now=datetime(2026, 8, 25, 1, 0, tzinfo=UTC),
    )

    assert {row.kind for row in rows} == {
        "resource_expiry",
        "request_review",
        "class_task",
    }
    assert (
        next(row for row in rows if row.kind == "resource_expiry").target
        == "/my-resources"
    )
    assert next(row for row in rows if row.kind == "request_review").tone == "success"
    class_task = next(row for row in rows if row.kind == "class_task")
    assert "Checkpoint" in class_task.title
    assert class_task.target == f"/dashboard/course/{teaching_class.id}"


def test_class_content_requires_active_enrollment() -> None:
    """退選或別班的學生拿著班級 id 也讀不到課程、每週任務與 AI 作業。"""
    from app.exceptions import NotFoundError

    with _session() as session:
        teacher = _user("teacher@example.edu", UserRole.teacher)
        student = _user("student@example.edu", UserRole.student)
        outsider = _user("outsider@example.edu", UserRole.student)
        session.add(outsider)
        teaching_class = _linked_class(
            session, teacher=teacher, student=student, session_date=date(2026, 8, 25)
        )

        detail = get_student_class_detail(
            session, user_id=student.id, class_id=teaching_class.id
        )
        assert (detail.id, detail.title) == (teaching_class.id, teaching_class.name)

        readers = (
            get_student_class_detail,
            weekly_task_service.list_student_weekly_tasks,
            ai_assignment_service.list_student_ai_assignments,
        )
        for read in readers:
            with pytest.raises(NotFoundError):
                read(session, user_id=outsider.id, class_id=teaching_class.id)
        with pytest.raises(NotFoundError):
            get_student_class_detail(
                session, user_id=student.id, class_id=uuid.uuid4()
            )

        enrollment = session.exec(
            select(TeachingClassStudent).where(
                TeachingClassStudent.user_id == student.id,
            )
        ).one()
        enrollment.status = "removed"
        session.add(enrollment)
        session.commit()
        for read in readers:
            with pytest.raises(NotFoundError):
                read(session, user_id=student.id, class_id=teaching_class.id)
