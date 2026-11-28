"""學生端的課程視圖：學生的「課程」就是他修的班級。

班級第一次進入「可以上課」（``TeachingClass.first_active_at`` 有值）之後，名單上
的學生就看得到這門課；之後班級狀態怎麼變（補機器、部分失敗、封存）都不影響
可見性。以前另外有一層「學習路徑」當發布開關與識別碼，2026-11-28 已整套移除。
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel import Session, col, select
from sqlmodel.sql.expression import SelectOfScalar

from app.core.i18n import t
from app.exceptions import NotFoundError
from app.models import (
    TeachingClass,
    TeachingClassStatus,
    TeachingClassStudent,
    User,
)
from app.schemas.course import CourseClassStudent, CourseScheduleStudent


def _student_classes(user_id: uuid.UUID) -> SelectOfScalar[TeachingClass]:
    """這位學生看得到的班級：已開放給學生，而且他在名單上有效修課。"""
    return (
        select(TeachingClass)
        .join(
            TeachingClassStudent,
            col(TeachingClassStudent.class_id) == TeachingClass.id,
        )
        .where(
            col(TeachingClass.first_active_at).is_not(None),
            TeachingClassStudent.user_id == user_id,
            TeachingClassStudent.status == "active",
        )
    )


def list_student_classes(
    session: Session, *, user_id: uuid.UUID
) -> list[CourseClassStudent]:
    """學生修的課程清單，新建立的班級排前面。"""
    classes = session.exec(
        _student_classes(user_id).order_by(col(TeachingClass.created_at).desc())
    ).all()
    return [CourseClassStudent(id=item.id, title=item.name) for item in classes]


def get_student_class_or_404(
    session: Session, *, user_id: uuid.UUID, class_id: uuid.UUID
) -> TeachingClass:
    """學生開某一門課時的唯一入口。

    班級不存在、還沒開放給學生、學生不在名單上或已退選，一律當成不存在：
    每週任務、AI 作業、課堂機器都經過這裡，別班或退選的學生拿著 id 也讀不到。
    """
    item = session.exec(
        _student_classes(user_id).where(TeachingClass.id == class_id)
    ).first()
    if item is None:
        raise NotFoundError(t("course.not_found"))
    return item


def get_student_class_detail(
    session: Session, *, user_id: uuid.UUID, class_id: uuid.UUID
) -> CourseClassStudent:
    item = get_student_class_or_404(session, user_id=user_id, class_id=class_id)
    return CourseClassStudent(id=item.id, title=item.name)


def _class_timezone(item: TeachingClass) -> ZoneInfo:
    try:
        return ZoneInfo(item.timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Taipei")


def list_student_schedule(
    session: Session,
    *,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> list[CourseScheduleStudent]:
    """Return every active-term class, highlighting today's real session."""

    current = now or datetime.now(UTC)
    classes = session.exec(
        _student_classes(user_id).where(
            TeachingClass.status == TeachingClassStatus.active
        )
    ).all()

    teacher_ids = {teaching_class.owner_id for teaching_class in classes}
    teachers = (
        {
            teacher.id: teacher
            for teacher in session.exec(
                select(User).where(col(User.id).in_(teacher_ids))
            ).all()
        }
        if teacher_ids
        else {}
    )
    result: list[CourseScheduleStudent] = []
    for teaching_class in classes:
        timezone = _class_timezone(teaching_class)
        local_now = current.astimezone(timezone)
        local_date = local_now.date()
        if not teaching_class.start_date <= local_date <= teaching_class.end_date:
            continue
        days_until_session = (teaching_class.weekday - local_date.weekday()) % 7
        session_date = local_date + timedelta(days=days_until_session)
        if session_date > teaching_class.end_date:
            days_since_session = (local_date.weekday() - teaching_class.weekday) % 7
            session_date = local_date - timedelta(days=days_since_session)
        starts_at = datetime.combine(
            session_date,
            teaching_class.start_time,
            tzinfo=timezone,
        )
        ends_at = datetime.combine(
            session_date,
            teaching_class.end_time,
            tzinfo=timezone,
        )
        if session_date != local_date:
            state, label = "available", "可課後練習"
        elif local_now < starts_at:
            state, label = "later", "今天稍後"
        elif local_now <= ends_at:
            state, label = "now", "正在上課"
        else:
            state, label = "ended", "今天已結束"
        teacher = teachers.get(teaching_class.owner_id)
        result.append(
            CourseScheduleStudent(
                id=teaching_class.id,
                title=teaching_class.name,
                session_date=session_date,
                start_at=starts_at,
                end_at=ends_at,
                teacher=(
                    (teacher.full_name or teacher.email)
                    if teacher
                    else t("course.teacher_fallback")
                ),
                location=teaching_class.location,
                state=state,  # type: ignore[arg-type]
                label=label,
            )
        )
    state_order = {"now": 0, "later": 1, "available": 2, "ended": 3}
    return sorted(result, key=lambda row: (state_order[row.state], row.start_at))
