"""Remove learning paths; a student's course is the teaching class itself.

Revision ID: cpathrm01_drop_learning_paths
Revises: pconn03_drop_dead_cols

學習路徑原本是一套闖關教材的最上層（路徑 › 房間 › 任務 › 題目），後來學生端
只剩把它當成「班級的發布開關與識別碼」：編輯內容的頁面已下架、學生也沒有
答題的畫面。這支 migration 把整套拿掉：

- ``teaching_classes.first_active_at``：班級第一次可以上課的時間，取代路徑的
  「已發布」。已發布的路徑所屬的班級，以及目前就是可上課狀態的班級，都補上值，
  學生原本看得到的課升級後照樣看得到。
- 刪掉 ``user_course_progress``、``course_questions``、``course_tasks``、
  ``course_rooms``、``course_paths`` 五張表與三個 enum 型別。**表裡的房間、
  任務、題目與作答紀錄會一起消失，降版救不回來。**

降版會把五張表建回來，並替每個班級補一條同名的路徑（開放過的班級是已發布），
讓舊版程式能繼續運作；房間、任務、題目與作答紀錄是空的。
"""

import sqlalchemy as sa
from alembic import op

revision = "cpathrm01_drop_learning_paths"
down_revision = "pconn03_drop_dead_cols"
branch_labels = None
depends_on = None

_ENUMS = {
    "coursepathstatus": ("draft", "published"),
    "coursedifficulty": ("easy", "medium", "hard"),
    "coursequestiontype": ("flag", "no_answer"),
}


def upgrade() -> None:
    op.add_column(
        "teaching_classes",
        sa.Column("first_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE teaching_classes AS c
        SET first_active_at = COALESCE(
            (
                SELECT p.updated_at
                FROM course_paths AS p
                WHERE p.teaching_class_id = c.id AND p.status = 'published'
            ),
            c.updated_at
        )
        WHERE c.status = 'active'
           OR EXISTS (
                SELECT 1
                FROM course_paths AS p
                WHERE p.teaching_class_id = c.id AND p.status = 'published'
           )
        """
    )
    for table in (
        "user_course_progress",
        "course_questions",
        "course_tasks",
        "course_rooms",
        "course_paths",
    ):
        op.drop_table(table)
    for name in _ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {name}")


def downgrade() -> None:
    bind = op.get_bind()
    enums = {
        name: sa.Enum(*labels, name=name, create_type=False)
        for name, labels in _ENUMS.items()
    }
    for name, labels in _ENUMS.items():
        sa.Enum(*labels, name=name).create(bind, checkfirst=True)

    op.create_table(
        "course_paths",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("status", enums["coursepathstatus"], nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "teaching_class_id",
            sa.Uuid(),
            sa.ForeignKey(
                "teaching_classes.id",
                name="fk_course_paths_teaching_class_id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_course_paths_status", "course_paths", ["status"])
    op.create_index(
        "ix_course_paths_teaching_class_id",
        "course_paths",
        ["teaching_class_id"],
        unique=True,
    )

    op.create_table(
        "course_rooms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "path_id",
            sa.Uuid(),
            sa.ForeignKey("course_paths.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("difficulty", enums["coursedifficulty"], nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_course_rooms_path_id", "course_rooms", ["path_id"])

    op.create_table(
        "course_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "room_id",
            sa.Uuid(),
            sa.ForeignKey("course_rooms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_course_tasks_room_id", "course_tasks", ["room_id"])

    op.create_table(
        "course_questions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id",
            sa.Uuid(),
            sa.ForeignKey("course_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt", sa.String(length=1000), nullable=False),
        sa.Column("question_type", enums["coursequestiontype"], nullable=False),
        sa.Column("flag_hash", sa.String(length=64), nullable=True),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_course_questions_task_id", "course_questions", ["task_id"])

    op.create_table(
        "user_course_progress",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Uuid(),
            sa.ForeignKey("course_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "question_id", name="uq_user_course_progress"),
    )
    op.create_index(
        "ix_user_course_progress_user_id", "user_course_progress", ["user_id"]
    )
    op.create_index(
        "ix_user_course_progress_question_id", "user_course_progress", ["question_id"]
    )

    # 舊版程式靠「班級有一條已發布的路徑」決定學生看不看得到課
    op.execute(
        """
        INSERT INTO course_paths
            (id, title, description, status, created_by, teaching_class_id,
             created_at, updated_at)
        SELECT
            gen_random_uuid(),
            c.name,
            NULL,
            CASE WHEN c.first_active_at IS NULL
                 THEN 'draft'::coursepathstatus
                 ELSE 'published'::coursepathstatus END,
            c.owner_id,
            c.id,
            c.created_at,
            COALESCE(c.first_active_at, c.updated_at)
        FROM teaching_classes AS c
        """
    )
    op.drop_column("teaching_classes", "first_active_at")
