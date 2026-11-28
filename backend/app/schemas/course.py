"""學生端課程 schemas：課表、提醒、每週任務、AI 導師檢查與課堂機器。

學生的「課程」就是他修的班級，回應裡的課程 id 一律是班級 id。
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ── 學生端 ─────────────────────────────────────────────────────────────────


class CourseClassStudent(BaseModel):
    """學生修的一門課：就是他所在的班級，``id`` 是班級 id、``title`` 是班級名稱。"""

    id: uuid.UUID
    title: str


class CourseScheduleStudent(BaseModel):
    """One real teaching-class session shown on the student's home page."""

    id: uuid.UUID
    title: str
    session_date: date
    start_at: datetime
    end_at: datetime
    teacher: str
    location: str | None = None
    state: Literal["now", "later", "available", "ended"]
    label: str


class CourseReminderStudent(BaseModel):
    """Derived reminder; read state remains a per-browser UI preference."""

    id: str
    kind: Literal["resource_expiry", "request_review", "class_task"]
    tone: Literal["warning", "success", "danger", "info"]
    icon: str
    title: str
    description: str
    time_label: str
    target: str
    occurred_at: datetime


class CourseAITaskItemStudent(BaseModel):
    """學生可見的 AI導師檢查要求；不包含命令、腳本與內部判分提示。"""

    id: str
    title: str
    description: str = ""
    detectable: Literal["auto", "partial", "manual"] = "manual"
    order: int = 0
    # 這個檢查點在哪台課堂機器上檢查（多機器的作業才有意義）
    machine_node_key: str | None = None


class CourseAICheckItemStudent(BaseModel):
    """AI導師檢查單一評分項目，僅包含學生需要的回饋。"""

    item_id: str = ""
    title: str = ""
    status: str = "unknown"
    score: int | None = None
    max_score: int | None = None
    comment: str = ""


class CourseAICheckStudent(BaseModel):
    """學生自己送出的 AI導師檢查狀態與安全化回饋。"""

    run_id: uuid.UUID
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    submitted_at: datetime
    finished_at: datetime | None = None
    score: int | None = None
    max_score: int | None = None
    summary: str = ""
    teacher_feedback: str = ""
    error: str = ""
    items: list[CourseAICheckItemStudent] = Field(default_factory=list)


class CourseAICompletionUpdate(BaseModel):
    """學生只回報作業是否已完成，不會觸發 AI導師檢查。

    ``item_id`` 留空時代表一次切換整份每週任務；保留單項模式供舊版
    用戶端相容使用。
    """

    item_id: str | None = Field(default=None, min_length=1, max_length=255)
    completed: bool


class CourseAICompletionStudent(BaseModel):
    completed: bool = False
    completed_item_ids: list[str] = Field(default_factory=list)
    ready_at: datetime | None = None


class CourseAISourceDocumentStudent(BaseModel):
    """學生可查看的老師任務文件；不公開內部檔案路徑。"""

    filename: str
    display_name: str
    media_type: Literal["application/pdf"] = "application/pdf"


class CourseAIAssignmentStudent(BaseModel):
    """老師核准後，公開給所屬學生的 AI導師檢查任務。"""

    id: uuid.UUID
    teaching_class_id: uuid.UUID
    teaching_class_name: str
    session_id: uuid.UUID | None = None
    teaching_class_week_id: uuid.UUID | None = None
    title: str
    summary: str = ""
    template_key: str
    version: int
    approved_at: datetime | None = None
    # 學生端僅公開製作並核准的腳本任務。
    check_available: bool = True
    items: list[CourseAITaskItemStudent]
    source_document: CourseAISourceDocumentStudent | None = None
    completion: CourseAICompletionStudent = Field(
        default_factory=CourseAICompletionStudent
    )
    latest_check: CourseAICheckStudent | None = None
    checkpoint_checks: dict[str, CourseAICheckStudent] = Field(default_factory=dict)
    # 老師給這位學生這週的回覆（沒回覆是空字串）；老師再回覆會覆蓋，這裡只有最新的
    teacher_reply: str = ""
    teacher_reply_at: datetime | None = None


class CourseWeeklyTaskFileStudent(BaseModel):
    """A teacher-provided PDF that an enrolled student may preview."""

    id: uuid.UUID
    filename: str
    media_type: Literal["application/pdf"] = "application/pdf"


class CourseWeeklyCheckpointStudent(BaseModel):
    id: str
    task_id: uuid.UUID
    assignment_id: uuid.UUID | None = None
    assignment_title: str
    check_available: bool = False
    title: str
    description: str = ""
    detectable: Literal["auto", "partial", "manual"] = "manual"
    order: int = 0
    machine_node_key: str | None = None
    latest_check: CourseAICheckStudent | None = None


class CourseWeeklySourceDocumentStudent(CourseAISourceDocumentStudent):
    """已核准 AI 任務的 PDF；透過作業身分驗證端點開啟。"""

    assignment_id: uuid.UUID


class CourseWeeklyTaskStudent(BaseModel):
    """Published weekly content from the teaching class linked to a path."""

    id: uuid.UUID
    teaching_class_id: uuid.UUID
    teaching_class_name: str
    week_number: int
    session_date: date
    title: str
    files: list[CourseWeeklyTaskFileStudent] = Field(default_factory=list)
    source_documents: list[CourseWeeklySourceDocumentStudent] = Field(
        default_factory=list
    )
    checkpoints: list[CourseWeeklyCheckpointStudent] = Field(default_factory=list)
    teacher_reply: str = ""
    teacher_reply_at: datetime | None = None


class ForwardEndpoint(BaseModel):
    """學生要連的對外入口：管理員沒設入口主機時 host 為 None，只給 port。"""

    host: str | None = None
    external_port: int
    internal_port: int
    protocol: str = "tcp"


class CoursePracticeMachineStudent(BaseModel):
    """學生在該課程可直接操作的班級機器。"""

    teaching_class_id: uuid.UUID
    teaching_class_name: str
    machine_node_id: uuid.UUID
    node_key: str
    name: str
    role: str
    resource_type: str
    vmid: int | None = None
    status: str
    public_url: str | None = None
    forward_endpoints: list[ForwardEndpoint] = Field(default_factory=list)


__all__ = [
    "CourseClassStudent",
    "CourseScheduleStudent",
    "CourseReminderStudent",
    "CourseAITaskItemStudent",
    "CourseAICheckItemStudent",
    "CourseAICheckStudent",
    "CourseAICompletionUpdate",
    "CourseAICompletionStudent",
    "CourseAISourceDocumentStudent",
    "CourseAIAssignmentStudent",
    "CourseWeeklyTaskFileStudent",
    "CourseWeeklyCheckpointStudent",
    "CourseWeeklyTaskStudent",
    "CoursePracticeMachineStudent",
]
