"""Coverage tests for app.services.course.course_service (student class views)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.exceptions import NotFoundError
from app.models import (
    TeachingClass,
    TeachingClassStatus,
    TeachingClassStudent,
    User,
    UserRole,
)
from app.services.course import course_service

OPENED_AT = datetime(2026, 8, 1, tzinfo=UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _user(session: Session, email: str, role: UserRole = UserRole.student) -> User:
    user = User(email=email, role=role, full_name=None, hashed_password="x")
    session.add(user)
    session.commit()
    return user


def _class(
    session: Session,
    *,
    owner_id: uuid.UUID,
    code: str,
    start_date: date,
    end_date: date,
    weekday: int,
    timezone: str = "Asia/Taipei",
    name: str = "Class",
    first_active_at: datetime | None = OPENED_AT,
    status: TeachingClassStatus = TeachingClassStatus.active,
    created_at: datetime | None = None,
) -> TeachingClass:
    item = TeachingClass(
        name=name,
        code=code,
        term="2026-1",
        location="Room A",
        owner_id=owner_id,
        start_date=start_date,
        end_date=end_date,
        weekday=weekday,
        start_time=time(9),
        end_time=time(11),
        timezone=timezone,
        status=status,
        first_active_at=first_active_at,
    )
    if created_at is not None:
        item.created_at = created_at
    session.add(item)
    session.commit()
    return item


def _enroll(session: Session, teaching_class: TeachingClass, user: User) -> None:
    session.add(TeachingClassStudent(class_id=teaching_class.id, user_id=user.id))
    session.commit()


def _term_class(session: Session, owner: User, code: str, **kwargs) -> TeachingClass:
    return _class(
        session,
        owner_id=owner.id,
        code=code,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 12, 31),
        weekday=0,
        **kwargs,
    )


# ── Which classes a student can see ────────────────────────────────────────


def test_list_student_classes_newest_first_and_only_opened(session: Session) -> None:
    teacher = _user(session, "t@example.edu", UserRole.teacher)
    student = _user(session, "s@example.edu")
    older = _term_class(
        session, teacher, "older", name="Linux", created_at=datetime(2026, 7, 1, tzinfo=UTC)
    )
    newer = _term_class(
        session, teacher, "newer", name="Network", created_at=datetime(2026, 7, 20, tzinfo=UTC)
    )
    not_opened = _term_class(
        session,
        teacher,
        "planning",
        first_active_at=None,
        status=TeachingClassStatus.provisioning,
    )
    not_enrolled = _term_class(session, teacher, "other")
    for item in (older, newer, not_opened):
        _enroll(session, item, student)

    rows = course_service.list_student_classes(session, user_id=student.id)
    assert [(row.id, row.title) for row in rows] == [
        (newer.id, "Network"),
        (older.id, "Linux"),
    ]
    assert not_enrolled.id not in {row.id for row in rows}


def test_opened_class_stays_visible_after_its_status_changes(session: Session) -> None:
    """補機器、部分失敗或封存都不會讓學生的課消失。"""
    teacher = _user(session, "t@example.edu", UserRole.teacher)
    student = _user(session, "s@example.edu")
    for index, status in enumerate(
        (
            TeachingClassStatus.provisioning,
            TeachingClassStatus.partial_failed,
            TeachingClassStatus.archived,
        )
    ):
        _enroll(session, _term_class(session, teacher, f"c{index}", status=status), student)

    assert len(course_service.list_student_classes(session, user_id=student.id)) == 3


def test_get_student_class_guards(session: Session) -> None:
    teacher = _user(session, "t@example.edu", UserRole.teacher)
    student = _user(session, "s@example.edu")
    outsider = _user(session, "o@example.edu")
    opened = _term_class(session, teacher, "opened", name="Linux")
    not_opened = _term_class(session, teacher, "planning", first_active_at=None)
    _enroll(session, opened, student)
    _enroll(session, not_opened, student)

    found = course_service.get_student_class_or_404(
        session, user_id=student.id, class_id=opened.id
    )
    assert found.id == opened.id
    detail = course_service.get_student_class_detail(
        session, user_id=student.id, class_id=opened.id
    )
    assert (detail.id, detail.title) == (opened.id, "Linux")

    for user_id, class_id in (
        (student.id, uuid.uuid4()),  # 不存在
        (student.id, not_opened.id),  # 還沒開放給學生
        (outsider.id, opened.id),  # 不在名單上
    ):
        with pytest.raises(NotFoundError):
            course_service.get_student_class_or_404(
                session, user_id=user_id, class_id=class_id
            )

    enrollment = session.get(TeachingClassStudent, _enrollment_id(session, opened, student))
    assert enrollment is not None
    enrollment.status = "removed"
    session.add(enrollment)
    session.commit()
    with pytest.raises(NotFoundError):
        course_service.get_student_class_detail(
            session, user_id=student.id, class_id=opened.id
        )


def _enrollment_id(
    session: Session, teaching_class: TeachingClass, user: User
) -> uuid.UUID:
    from sqlmodel import select

    return session.exec(
        select(TeachingClassStudent.id).where(
            TeachingClassStudent.class_id == teaching_class.id,
            TeachingClassStudent.user_id == user.id,
        )
    ).one()


# ── Schedule ───────────────────────────────────────────────────────────────


def test_list_student_schedule_states(session: Session) -> None:
    teacher = _user(session, "t@example.edu", UserRole.teacher)
    student = _user(session, "s@example.edu")
    today = date(2026, 8, 26)
    # 00:00 UTC == 08:00 Asia/Taipei: before a 09:00 session today.
    morning = datetime(2026, 8, 26, 0, 0, tzinfo=UTC)

    later_cls = _class(
        session,
        owner_id=teacher.id,
        code="later",
        start_date=today - timedelta(days=7),
        end_date=today + timedelta(days=30),
        weekday=today.weekday(),
        name="Later",
    )
    # Ends today; its weekday was yesterday, so next session is past end_date
    # and the schedule falls back to the most recent session.
    past_cls = _class(
        session,
        owner_id=teacher.id,
        code="past",
        start_date=today - timedelta(days=30),
        end_date=today,
        weekday=(today.weekday() - 1) % 7,
    )
    # Term has not started yet → skipped.
    future_cls = _class(
        session,
        owner_id=teacher.id,
        code="future",
        start_date=today + timedelta(days=10),
        end_date=today + timedelta(days=60),
        weekday=today.weekday(),
    )
    # Unknown timezone + owner without a user row → teacher fallback text.
    orphan_cls = _class(
        session,
        owner_id=uuid.uuid4(),
        code="orphan",
        start_date=today - timedelta(days=7),
        end_date=today + timedelta(days=30),
        weekday=today.weekday(),
        timezone="Not/AZone",
    )
    # Opened once but no longer active (re-provisioning) → not on the schedule.
    paused_cls = _class(
        session,
        owner_id=teacher.id,
        code="paused",
        start_date=today - timedelta(days=7),
        end_date=today + timedelta(days=30),
        weekday=today.weekday(),
        status=TeachingClassStatus.provisioning,
    )
    # Active but never recorded as opened → students do not see it yet.
    unopened_cls = _class(
        session,
        owner_id=teacher.id,
        code="unopened",
        start_date=today - timedelta(days=7),
        end_date=today + timedelta(days=30),
        weekday=today.weekday(),
        first_active_at=None,
    )
    for cls in (later_cls, past_cls, future_cls, orphan_cls, paused_cls, unopened_cls):
        _enroll(session, cls, student)

    rows = course_service.list_student_schedule(
        session, user_id=student.id, now=morning
    )
    by_class = {row.id: row for row in rows}
    assert set(by_class) == {later_cls.id, orphan_cls.id, past_cls.id}
    assert by_class[later_cls.id].title == "Later"
    assert by_class[later_cls.id].state == "later"
    assert by_class[later_cls.id].location == "Room A"
    assert by_class[orphan_cls.id].state == "later"
    assert by_class[past_cls.id].state == "available"
    assert by_class[past_cls.id].session_date == today - timedelta(days=1)
    assert by_class[later_cls.id].teacher == "t@example.edu"
    assert by_class[orphan_cls.id].teacher not in {"", "t@example.edu"}

    # 04:00 UTC == 12:00 Asia/Taipei: today's session already ended.
    afternoon = datetime(2026, 8, 26, 4, 0, tzinfo=UTC)
    rows = course_service.list_student_schedule(
        session, user_id=student.id, now=afternoon
    )
    states = {row.id: row.state for row in rows}
    assert states[later_cls.id] == "ended"

    # 02:00 UTC == 10:00 Asia/Taipei: in session.
    rows = course_service.list_student_schedule(
        session, user_id=student.id, now=datetime(2026, 8, 26, 2, 0, tzinfo=UTC)
    )
    assert {row.id: row.state for row in rows}[later_cls.id] == "now"
    assert rows[0].state == "now"

    # No enrolled class at all: nothing to look up, empty schedule.
    stranger = _user(session, "x@example.edu")
    assert (
        course_service.list_student_schedule(session, user_id=stranger.id, now=morning)
        == []
    )
