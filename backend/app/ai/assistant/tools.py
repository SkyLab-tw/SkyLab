"""助手可以呼叫的工具。

分兩種：

- **讀**（``read_help``、``get_my_requests``）：把資料交回給模型，模型看完還要再講話。
- **動作**（``show_pages``、``start_flow``、``plan_machine``、``point_at``）：在回覆
  下方附上按鈕、流程卡、配置規劃，或在畫面上打光。模型只挑 id，顯示的內容一律
  由這裡依使用者權限組出來——模型寫不出一個不存在的網址，也帶不到沒權限的頁面。

工具定義是逐次請求產生的：能挑的 id 就是這個使用者看得到的那些，寫進 JSON
Schema 的 enum。模型仍可能回傳 enum 以外的值（不是每個後端都嚴格約束），所以
執行時再驗一次，不合法就把錯誤交回給模型，不當成例外。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.ai.assistant.catalog import NavigationRoute
from app.ai.assistant.flows import NavigationFlow, find_flow_by_id
from app.ai.assistant.knowledge import page_target, render_help
from app.ai.assistant.machine_plan import (
    DISPLAY_ANSWERS,
    GPU_ANSWERS,
    MAX_DURATION_DAYS,
    PLAN_KEYS,
    resolve_plan,
)
from app.ai.assistant.schemas import (
    FlowCard,
    FlowStepPublic,
    GuideStep,
    PageTarget,
    PlanState,
    Spotlight,
)
from app.ai.assistant.specs import SurfaceSpec
from app.models.user import UserRole

logger = logging.getLogger(__name__)

MAX_HELP_PAGES = 3
MAX_PAGE_BUTTONS = 4

RequestLoader = Callable[[], Awaitable[list[dict[str, Any]]]]


def _page_key(path: str) -> str:
    """比較兩個路徑是不是同一頁：不看查詢參數與結尾的斜線。"""
    return path.split("?")[0].rstrip("/") or "/"


@dataclass(frozen=True)
class ToolOutcome:
    """工具交回給模型的結果。

    ``needs_reply``：模型看完這個結果還得再講一次話（讀到了資料、要問使用者一題、
    或工具回報錯誤）。動作成功時是 False：同一則訊息已經寫好回答就不必再繞一輪。

    ``unless_answered``：這個結果只在「同一則訊息沒有寫出完整回答」時才需要再講
    一次。回答是邊寫邊顯示的，為了一顆沒附上的按鈕把寫好的整段收回重寫並不值得。
    """

    result: dict[str, Any]
    needs_reply: bool
    unless_answered: bool = False


def _function(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
                "additionalProperties": False,
            },
        },
    }


@dataclass
class Toolbox:
    """一次請求的工具集合，同時收集這一輪要附在回覆下方的東西。"""

    role: UserRole
    lang: str
    # 模型可以讀說明的畫面（已依身分過濾、去掉說明重複的）
    surfaces: Sequence[SurfaceSpec]
    routes: Sequence[NavigationRoute]
    flows: Sequence[NavigationFlow]
    guide_steps: Sequence[GuideStep] = ()
    load_requests: RequestLoader | None = None
    # 使用者眼前這一頁的路徑；show_pages 不會附一顆指向這一頁自己的按鈕
    current_path: str | None = None

    pages: list[PageTarget] = field(default_factory=list)
    flow: FlowCard | None = None
    plan: PlanState | None = None
    spotlight: Spotlight | None = None
    help_read: list[str] = field(default_factory=list)
    called: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._surface_by_id = {surface.id: surface for surface in self.surfaces}
        self._targets = {
            surface.id: target
            for surface in self.surfaces
            if (target := page_target(surface, self.routes)) is not None
        }

    # ------------------------------------------------------------ 定義

    def definitions(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        if self._surface_by_id:
            tools.append(
                _function(
                    "read_help",
                    "讀取頁面的完整使用說明（功能、會跳出的視窗、每個欄位怎麼填、相關頁面）。"
                    "回答「怎麼做」而目前畫面的說明不夠時，先讀相關頁面再回答。",
                    {
                        "page_ids": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": list(self._surface_by_id),
                            },
                            "minItems": 1,
                            "maxItems": MAX_HELP_PAGES,
                        }
                    },
                    ["page_ids"],
                )
            )
        # 使用者眼前這一頁不列進去：指向自己的按鈕點了沒有反應，模型一旦附了，
        # 已經寫給使用者看的回答就得收回重寫。選不到就不會發生。
        button_ids = [
            page_id
            for page_id, target in self._targets.items()
            if not self._points_here(target)
        ]
        if button_ids:
            tools.append(
                _function(
                    "show_pages",
                    "在回覆下方附上可以直接點的頁面按鈕。回答裡要使用者去某一頁時使用。"
                    "清單裡沒有使用者目前所在的那一頁：他已經在那裡，不需要按鈕。",
                    {
                        "page_ids": {
                            "type": "array",
                            "items": {"type": "string", "enum": button_ids},
                            "minItems": 1,
                            "maxItems": MAX_PAGE_BUTTONS,
                        }
                    },
                    ["page_ids"],
                )
            )
        if self.flows:
            tools.append(
                _function(
                    "start_flow",
                    "在回覆下方附上一張多步驟流程卡。使用者要完成的事跨好幾步、而且有對應流程時使用。",
                    {
                        "flow_id": {
                            "type": "string",
                            "enum": [flow.flow_id for flow in self.flows],
                        }
                    },
                    ["flow_id"],
                )
            )
        tools.append(
            _function(
                "plan_machine",
                "使用者要申請機器、要你推薦規格或幫忙填申請單時使用。把對話中已經知道的需求填進來；"
                "能從用途明確推斷的（例如一般網站不需要 GPU、用指令列就好）可以直接填，並列進 assumed；"
                "其餘不知道的不要填、不要猜，工具會告訴你還要問哪一題。問齊後系統會產生配置並填進申請單。",
                {
                    "purpose": {
                        "type": "string",
                        "description": "這台機器要拿來做什麼（用使用者的原話摘要）",
                    },
                    "gpu": {
                        "type": "string",
                        "enum": list(GPU_ANSWERS),
                        "description": "need=需要 GPU；no=不需要；unsure=使用者不確定、交給系統判斷",
                    },
                    "display": {
                        "type": "string",
                        "enum": list(DISPLAY_ANSWERS),
                        "description": "desktop=需要圖形桌面；windows=需要 Windows；cli=Linux 指令列就好",
                    },
                    "duration_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_DURATION_DAYS,
                        "description": "要用幾天（一個月算 30，一學期算 90）",
                    },
                    "assumed": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(PLAN_KEYS)},
                        "description": "哪幾項是你依用途推斷、不是使用者明講的",
                    },
                    "proceed": {
                        "type": "boolean",
                        "description": "使用者明講不用再問、直接產生配置時設為 true",
                    },
                },
            )
        )
        if self.load_requests is not None:
            tools.append(
                _function(
                    "get_my_requests",
                    "查詢使用者自己最近的機器申請與目前進度（審核狀態、開通狀態）。"
                    "使用者問申請過了沒、機器好了沒時使用。",
                    {},
                )
            )
        if self.guide_steps:
            tools.append(
                _function(
                    "point_at",
                    "在使用者目前的畫面上把某個區塊打光指出來。使用者問某個東西在哪裡、"
                    "或要你指給他看，而且「可以指出的位置」清單裡有對應項目時使用。",
                    {
                        "target_id": {
                            "type": "string",
                            "enum": [step.id for step in self.guide_steps],
                        }
                    },
                    ["target_id"],
                )
            )
        return tools

    # ------------------------------------------------------------ 執行

    async def run(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.called.append(name)
        handler = {
            "read_help": self._read_help,
            "show_pages": self._show_pages,
            "start_flow": self._start_flow,
            "plan_machine": self._plan_machine,
            "point_at": self._point_at,
        }.get(name)
        if handler is not None:
            return handler(arguments)
        if name == "get_my_requests" and self.load_requests is not None:
            return await self._get_my_requests()
        return ToolOutcome({"error": f"沒有 {name} 這個工具。"}, needs_reply=True)

    def _ids(self, arguments: dict[str, Any], limit: int) -> list[str]:
        raw = arguments.get("page_ids")
        if not isinstance(raw, list):
            return []
        ids = [item for item in raw if isinstance(item, str)]
        return list(dict.fromkeys(ids))[:limit]

    def _read_help(self, arguments: dict[str, Any]) -> ToolOutcome:
        pages = []
        for page_id in self._ids(arguments, MAX_HELP_PAGES):
            surface = self._surface_by_id.get(page_id)
            if surface is None:
                continue
            pages.append(
                {
                    "page_id": page_id,
                    "help": render_help(surface, role=self.role, routes=self.routes),
                }
            )
            if page_id not in self.help_read:
                self.help_read.append(page_id)
        if not pages:
            return ToolOutcome(
                {"error": "page_ids 必須是頁面目錄裡的 id。"}, needs_reply=True
            )
        return ToolOutcome({"pages": pages}, needs_reply=True)

    def _points_here(self, target: PageTarget) -> bool:
        """這顆按鈕是不是指向使用者已經在的那一頁。

        帶開啟方式的按鈕（例如在「我的申請」直接開申請表單）會做事，不算。
        """
        return (
            self.current_path is not None
            and target.state is None
            and _page_key(target.path) == _page_key(self.current_path)
        )

    def _show_pages(self, arguments: dict[str, Any]) -> ToolOutcome:
        attached = []
        already_here = []
        full = False
        for page_id in self._ids(arguments, MAX_PAGE_BUTTONS):
            target = self._targets.get(page_id)
            if target is None:
                continue
            # 工具清單裡本來就沒有這一頁；模型還是挑了（不照清單來）才會走到這裡
            if self._points_here(target):
                already_here.append(target.title)
                continue
            duplicate = any(
                item.path == target.path and item.state == target.state
                for item in self.pages
            )
            if not duplicate:
                if len(self.pages) >= MAX_PAGE_BUTTONS:
                    # 沒附上去的不能回報成已附上，否則回答會提到一顆不存在的按鈕
                    full = True
                    continue
                self.pages.append(target)
            attached.append(target.title)
        if already_here:
            # 模型只寫了一句「帶你過去，按鈕在下面」時，少了這顆按鈕回答就不成立，要再
            # 講一次；上一則寫的字會從畫面上收回，所以要明講「完整重寫」，否則模型只補
            # 一句、步驟就不見了。已經寫出完整回答時不必重來（unless_answered）。
            result: dict[str, Any] = {
                "already_on_page": already_here,
                "note": "使用者已經在這一頁，所以沒有附上前往這一頁的按鈕。"
                "你上一則的內容使用者看不到：請把完整的回答重新寫一次"
                "（原本的說明與步驟都要保留），先說他已經在這一頁，"
                "不要再提前往這一頁的按鈕。",
            }
            if attached:
                result["attached_buttons"] = attached
            return ToolOutcome(result, needs_reply=True, unless_answered=True)
        if not attached and full:
            return ToolOutcome(
                {"error": f"頁面按鈕最多 {MAX_PAGE_BUTTONS} 顆，已經附滿了。"},
                needs_reply=True,
            )
        if not attached:
            return ToolOutcome(
                {"error": "這些頁面沒有辦法直接前往，請改用頁面目錄裡的其他 id。"},
                needs_reply=True,
            )
        return ToolOutcome({"attached_buttons": attached}, needs_reply=False)

    def _start_flow(self, arguments: dict[str, Any]) -> ToolOutcome:
        flow = find_flow_by_id(str(arguments.get("flow_id") or ""), self.flows)
        if flow is None:
            return ToolOutcome(
                {"error": "flow_id 必須是流程清單裡的 id。"}, needs_reply=True
            )
        self.flow = FlowCard(
            flow_id=flow.flow_id,
            title=flow.title,
            steps=[
                FlowStepPublic(
                    index=index,
                    title=step.title,
                    detail=step.detail,
                    path=step.path,
                    state=step.state,
                    action=step.action,
                )
                for index, step in enumerate(flow.steps)
            ],
        )
        return ToolOutcome(
            {
                "attached_flow": flow.title,
                "steps": [f"{step.title}：{step.detail}" for step in flow.steps],
            },
            needs_reply=False,
        )

    def _plan_machine(self, arguments: dict[str, Any]) -> ToolOutcome:
        self.plan = resolve_plan(arguments, lang=self.lang)
        if self.plan.status == "ask" and self.plan.question is not None:
            return ToolOutcome(
                {
                    "status": "need_answer",
                    "ask_user": self.plan.question.text,
                    "options_shown_as_buttons": self.plan.question.options,
                    "note": "只問這一題。選項已經用按鈕顯示在回覆下方，不必在文字裡重列。",
                },
                needs_reply=True,
            )
        return ToolOutcome(
            {
                "status": "ready",
                "note": "系統接下來會產生配置並顯示給使用者。簡短告訴使用者你正依這些需求規劃，"
                "不要自己寫出核心數、記憶體等數字。",
            },
            needs_reply=False,
        )

    def _point_at(self, arguments: dict[str, Any]) -> ToolOutcome:
        target_id = str(arguments.get("target_id") or "")
        step = next((item for item in self.guide_steps if item.id == target_id), None)
        if step is None:
            return ToolOutcome(
                {"error": "target_id 必須是「可以指出的位置」清單裡的 id。"},
                needs_reply=True,
            )
        self.spotlight = Spotlight(target_id=step.id)
        return ToolOutcome({"pointing_at": step.title}, needs_reply=False)

    async def _get_my_requests(self) -> ToolOutcome:
        assert self.load_requests is not None
        try:
            requests = await self.load_requests()
        except Exception:
            # 查不到不能當成「沒有申請」：照實告訴模型，讓它請使用者自己去看。
            logger.exception("Assistant failed to load the user's machine requests")
            return ToolOutcome(
                {"error": "目前查不到申請資料，請使用者到「我的申請」頁面確認。"},
                needs_reply=True,
            )
        return ToolOutcome({"requests": requests}, needs_reply=True)
