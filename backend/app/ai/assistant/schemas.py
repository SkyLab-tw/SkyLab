"""助手的 API 形狀。"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.ai.assistant.specs import MAX_STATE_ELEMENTS, ElementState
from app.ai.utils import clean_prompt_text

# 一次對話最多帶幾則進 prompt。前端保存整段對話，但只送最近的這幾則。
MAX_MESSAGES = 24
MAX_MESSAGE_CHARS = 4000
MAX_GUIDE_STEPS = 20

AssistantLocale = Literal["zh-TW", "en", "ja"]

# path 會進 system prompt；只收得下網址路徑的字元，免得被拿來塞指令。
_PATH_RE = re.compile(r"/[A-Za-z0-9_\-./?=&%:+]*")
_GUIDE_STEP_ID_RE = re.compile(r"[A-Za-z0-9_.:\-]{1,40}")


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=MAX_MESSAGE_CHARS)

    @field_validator("content")
    @classmethod
    def _clean(cls, text: str) -> str:
        return clean_prompt_text(text)


class GuideStep(BaseModel):
    """目前頁面聚光燈導覽的一個步驟。位置只有前端知道，這裡只有名稱。"""

    id: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=120)

    @field_validator("id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        if not _GUIDE_STEP_ID_RE.fullmatch(value):
            raise ValueError("guide step id contains unsupported characters")
        return value

    @field_validator("title")
    @classmethod
    def _clean_title(cls, text: str) -> str:
        # 這段會接進 system prompt；壓成一行，才開不出新的段落或標題冒充指令
        cleaned = " ".join(clean_prompt_text(text).split())
        if not cleaned:
            raise ValueError("guide step title is empty after cleaning")
        return cleaned


class ScreenContext(BaseModel):
    """使用者眼前的畫面。全部是脈絡，不代表任何工作已完成。"""

    path: str | None = Field(default=None, max_length=300)
    surface_id: str | None = Field(default=None, max_length=100)
    active_target: str | None = Field(default=None, max_length=100)
    state: dict[str, ElementState] = Field(
        default_factory=dict, max_length=MAX_STATE_ELEMENTS
    )
    guide_steps: list[GuideStep] = Field(
        default_factory=list, max_length=MAX_GUIDE_STEPS
    )

    @field_validator("path")
    @classmethod
    def _path_only(cls, path: str | None) -> str | None:
        # 不像路徑就當作沒給：路徑只是脈絡，丟掉不影響回答。
        return path if path and _PATH_RE.fullmatch(path) else None


class AssistantChatRequest(BaseModel):
    messages: list[AssistantMessage] = Field(..., min_length=1, max_length=MAX_MESSAGES)
    locale: AssistantLocale = "zh-TW"
    screen: ScreenContext = Field(default_factory=ScreenContext)

    @model_validator(mode="after")
    def _ends_with_a_question(self) -> AssistantChatRequest:
        last = self.messages[-1]
        if last.role != "user" or not last.content.strip():
            raise ValueError("the last message must be a non-empty user message")
        return self


class PageTarget(BaseModel):
    """回覆下方可以點的頁面按鈕；只會是使用者有權限的頁面。"""

    title: str
    path: str
    reason: str = ""
    # 交給 react-router 的 location state，例如 {"create": true} 會讓
    # /my-requests 直接開啟申請表單，而不是只停在列表。
    state: dict[str, Any] | None = None


class FlowStepPublic(BaseModel):
    index: int
    title: str
    detail: str = ""
    path: str
    state: dict[str, Any] | None = None
    # "recommend" 代表這一步由助手就地完成（規劃配置），而不是導到某一頁
    action: str | None = None


class FlowCard(BaseModel):
    flow_id: str
    title: str
    steps: list[FlowStepPublic] = Field(default_factory=list)


PlanKey = Literal["purpose", "gpu", "display", "duration"]


class PlanFacts(BaseModel):
    """申請機器前問到的答案；欄位與推薦規劃的 ``IntakeFactsContext`` 相同。"""

    purpose: str | None = None
    gpu: str | None = None
    display: str | None = None
    duration: str | None = None
    # 哪幾項是助手推斷、不是使用者明講的
    inferred: list[PlanKey] = Field(default_factory=list)


class PlanQuestion(BaseModel):
    key: PlanKey
    text: str
    # 可以直接點的答案，讓使用者不用打字
    options: list[str] = Field(default_factory=list)


class PlanState(BaseModel):
    # ask：還缺一項，question 是要問的；ready：問齊了，前端可以呼叫推薦規劃
    status: Literal["ask", "ready"]
    facts: PlanFacts = Field(default_factory=PlanFacts)
    question: PlanQuestion | None = None
    answered: int = 0
    total: int = 4


class Spotlight(BaseModel):
    """要在畫面上打光的步驟，對應 request 的 ``screen.guide_steps[].id``。"""

    target_id: str


class AssistantChatResponse(BaseModel):
    request_id: str
    reply: str
    pages: list[PageTarget] = Field(default_factory=list)
    flow: FlowCard | None = None
    plan: PlanState | None = None
    spotlight: Spotlight | None = None
    # 快速回覆晶片：點一下就等於送出那句話
    choices: list[str] = Field(default_factory=list)
    # 模型不可用或回答被擋下，reply 是伺服器的固定文字
    degraded: bool = False


class SurfacePublic(BaseModel):
    """給前端做「目前路徑對應哪個畫面」的對照表。不含欄位定義：
    那些只在回答時進 prompt，沒有必要整包送到瀏覽器。"""

    id: str
    path: str
    title: str
    purpose: str = ""
    when_to_use: str = ""
    # 這個畫面有沒有宣告欄位；沒有的話前端不必註冊動態狀態
    has_fields: bool = False
