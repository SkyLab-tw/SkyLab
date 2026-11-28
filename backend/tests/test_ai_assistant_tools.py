"""助手的工具：模型只挑 id，附在回覆下方的東西一律由伺服器依權限組出來。"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.assistant.catalog import can_access, get_routes_for_user
from app.ai.assistant.flows import all_flows, get_flows_for_user
from app.ai.assistant.knowledge import catalog_surfaces, page_target
from app.ai.assistant.schemas import GuideStep
from app.ai.assistant.surfaces import get_surfaces_for_user
from app.ai.assistant.tools import (
    MAX_HELP_PAGES,
    MAX_PAGE_BUTTONS,
    Toolbox,
    ToolOutcome,
)
from app.core.i18n import translate
from app.models.user import UserRole


def _user(role: UserRole) -> Any:
    return SimpleNamespace(id=None, role=role, is_superuser=False)


_REQUESTS = [{"name": "web-demo", "review_status": "approved"}]


def _toolbox(
    role: UserRole = UserRole.student,
    *,
    lang: str = "zh-TW",
    guide_steps: tuple[GuideStep, ...] = (),
    load_requests: Any = "default",
) -> Toolbox:
    user = _user(role)

    async def loader() -> list[dict[str, Any]]:
        return list(_REQUESTS)

    return Toolbox(
        role=role,
        lang=lang,
        surfaces=catalog_surfaces(get_surfaces_for_user(user)),
        routes=get_routes_for_user(user),
        flows=get_flows_for_user(user),
        guide_steps=guide_steps,
        load_requests=loader if load_requests == "default" else load_requests,
    )


def _definition(toolbox: Toolbox, name: str) -> dict[str, Any]:
    return next(
        tool["function"]
        for tool in toolbox.definitions()
        if tool["function"]["name"] == name
    )


def _names(toolbox: Toolbox) -> list[str]:
    return [tool["function"]["name"] for tool in toolbox.definitions()]


# ------------------------------------------------------------ 定義


def test_definitions_are_closed_function_schemas() -> None:
    toolbox = _toolbox(guide_steps=(GuideStep(id="0", title="標題列"),))
    assert _names(toolbox) == [
        "read_help",
        "show_pages",
        "start_flow",
        "plan_machine",
        "get_my_requests",
        "point_at",
    ]
    for tool in toolbox.definitions():
        assert tool["type"] == "function"
        function = tool["function"]
        assert function["description"].strip()
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        assert set(parameters["required"]) <= set(parameters["properties"])
    assert _definition(toolbox, "read_help")["parameters"]["required"] == ["page_ids"]
    assert _definition(toolbox, "plan_machine")["parameters"]["required"] == []
    assert _definition(toolbox, "get_my_requests")["parameters"]["properties"] == {}


def test_optional_tools_only_exist_when_they_can_do_something() -> None:
    assert "point_at" not in _names(_toolbox())
    assert "get_my_requests" not in _names(_toolbox(load_requests=None))
    bare = Toolbox(
        role=UserRole.student, lang="zh-TW", surfaces=(), routes=(), flows=()
    )
    # 沒有任何頁面與流程時，只剩不需要目錄的工具
    assert _names(bare) == ["plan_machine"]


def test_tool_enums_only_offer_what_the_user_may_see() -> None:
    student = _toolbox(UserRole.student)
    teacher = _toolbox(UserRole.teacher)
    admin = _toolbox(UserRole.admin)

    def enum(toolbox: Toolbox, name: str, field: str = "page_ids") -> list[str]:
        schema = _definition(toolbox, name)["parameters"]["properties"][field]
        return schema.get("enum") or schema["items"]["enum"]

    student_ids = {
        surface.id for surface in get_surfaces_for_user(_user(UserRole.student))
    }
    assert set(enum(student, "read_help")) <= student_ids
    assert set(enum(student, "show_pages")) <= set(enum(student, "read_help"))
    for forbidden in ("pve-connections", "class-setup", "request-review", "templates"):
        assert forbidden not in enum(student, "read_help")
        assert forbidden not in enum(student, "show_pages")
    assert "class-setup" in enum(teacher, "read_help")
    assert "pve-connections" not in enum(teacher, "read_help")
    assert "pve-connections" in enum(admin, "read_help")

    for toolbox, role in (
        (student, UserRole.student),
        (teacher, UserRole.teacher),
        (admin, UserRole.admin),
    ):
        assert set(enum(toolbox, "start_flow", "flow_id")) == {
            flow.flow_id for flow in all_flows() if can_access(flow.access, role)
        }
    assert set(enum(admin, "start_flow", "flow_id")) == {
        flow.flow_id for flow in all_flows()
    }
    assert "open_class" in enum(teacher, "start_flow", "flow_id")
    assert "open_class" not in enum(student, "start_flow", "flow_id")
    # 學生的課程頁：學生可以讀，老師連讀都不行
    assert "courses" in enum(student, "read_help")
    assert "courses" not in enum(teacher, "read_help")
    assert "courses" not in enum(teacher, "show_pages")

    # 去不了的畫面可以讀說明，但不會出現在按鈕的選項裡
    student_user = _user(UserRole.student)
    routes = get_routes_for_user(student_user)
    for surface in catalog_surfaces(get_surfaces_for_user(student_user)):
        assert surface.id in enum(student, "read_help")
        reachable = page_target(surface, routes) is not None
        assert (surface.id in enum(student, "show_pages")) is reachable
    assert (
        _definition(student, "read_help")["parameters"]["properties"]["page_ids"][
            "maxItems"
        ]
        == MAX_HELP_PAGES
    )
    assert (
        _definition(student, "show_pages")["parameters"]["properties"]["page_ids"][
            "maxItems"
        ]
        == MAX_PAGE_BUTTONS
    )


# ------------------------------------------------------------ read_help


async def test_read_help_returns_the_rendered_help_and_needs_a_reply() -> None:
    toolbox = _toolbox()
    outcome = await toolbox.run(
        "read_help", {"page_ids": ["resource-detail", "account", "resource-detail"]}
    )
    assert outcome.needs_reply is True
    pages = outcome.result["pages"]
    assert [page["page_id"] for page in pages] == ["resource-detail", "account"]
    assert pages[0]["help"].startswith("【")
    assert "（頁面 id：resource-detail）" in pages[0]["help"]
    assert toolbox.help_read == ["resource-detail", "account"]
    # 再讀一次不重複記錄
    await toolbox.run("read_help", {"page_ids": ["account"]})
    assert toolbox.help_read == ["resource-detail", "account"]
    assert toolbox.called == ["read_help", "read_help"]


async def test_read_help_reads_at_most_three_pages_per_call() -> None:
    toolbox = _toolbox()
    outcome = await toolbox.run(
        "read_help",
        {"page_ids": ["dashboard", "account", "jobs", "firewall", "ai-api"]},
    )
    assert [page["page_id"] for page in outcome.result["pages"]] == [
        "dashboard",
        "account",
        "jobs",
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"page_ids": "account"},
        {"page_ids": []},
        {"page_ids": [1, None, {"id": "account"}]},
        {"page_ids": ["pve-connections"]},
        {"page_ids": ["does-not-exist"]},
    ],
)
async def test_read_help_reports_bad_ids_instead_of_leaking_or_raising(
    arguments: dict[str, Any],
) -> None:
    """學生點名管理頁時拿到的是錯誤，不是那一頁的說明。"""
    toolbox = _toolbox(UserRole.student)
    outcome = await toolbox.run("read_help", arguments)
    assert outcome.needs_reply is True
    assert set(outcome.result) == {"error"}
    assert toolbox.help_read == []


async def test_read_help_skips_forbidden_ids_but_answers_the_rest() -> None:
    toolbox = _toolbox(UserRole.student)
    outcome = await toolbox.run(
        "read_help", {"page_ids": ["pve-connections", "account"]}
    )
    assert [page["page_id"] for page in outcome.result["pages"]] == ["account"]


# ------------------------------------------------------------ show_pages


async def test_show_pages_attaches_server_built_buttons() -> None:
    toolbox = _toolbox()
    outcome = await toolbox.run(
        "show_pages", {"page_ids": ["firewall", "request-form"]}
    )
    assert outcome == ToolOutcome(
        {"attached_buttons": [page.title for page in toolbox.pages]}, needs_reply=False
    )
    assert [(page.path, page.state) for page in toolbox.pages] == [
        ("/firewall", None),
        ("/my-requests", {"create": True}),
    ]


async def test_show_pages_does_not_repeat_the_same_destination() -> None:
    toolbox = _toolbox()
    # 機器詳細頁去不了，會退到「我的資源」；跟直接附「我的資源」是同一顆按鈕
    await toolbox.run("show_pages", {"page_ids": ["my-resources", "resource-detail"]})
    assert [page.path for page in toolbox.pages] == ["/my-resources"]
    await toolbox.run("show_pages", {"page_ids": ["my-resources"]})
    assert len(toolbox.pages) == 1
    # 同一個路徑但開啟方式不同（列表與表單）是兩顆
    await toolbox.run("show_pages", {"page_ids": ["my-requests", "request-form"]})
    assert [(page.path, page.state) for page in toolbox.pages] == [
        ("/my-resources", None),
        ("/my-requests", None),
        ("/my-requests", {"create": True}),
    ]


def test_the_page_the_user_is_on_is_not_offered_as_a_button() -> None:
    """選不到就不會附：模型附了指向目前這一頁的按鈕，寫好的回答就得收回重寫。"""

    def offered(toolbox: Toolbox) -> list[str]:
        schema = _definition(toolbox, "show_pages")["parameters"]["properties"]
        return schema["page_ids"]["items"]["enum"]

    elsewhere = _toolbox()
    assert "firewall" in offered(elsewhere)
    assert {"my-requests", "request-form"} <= set(offered(elsewhere))

    on_firewall = _toolbox()
    on_firewall.current_path = "/firewall/?tab=rules"
    assert "firewall" not in offered(on_firewall)
    assert set(offered(on_firewall)) == set(offered(elsewhere)) - {"firewall"}
    # 說明還是讀得到：使用者問的常常就是眼前這一頁
    read = _definition(on_firewall, "read_help")["parameters"]["properties"]
    assert "firewall" in read["page_ids"]["items"]["enum"]

    # 同一頁但帶開啟方式的按鈕會做事（在「我的申請」直接開申請表單），照樣列出來
    on_requests = _toolbox()
    on_requests.current_path = "/my-requests"
    assert "my-requests" not in offered(on_requests)
    assert "request-form" in offered(on_requests)


async def test_show_pages_never_points_at_the_page_the_user_is_on() -> None:
    """模型不照清單、還是挑了目前這一頁時：不附，並告訴模型改用眼前的說明回答。"""
    toolbox = _toolbox()
    toolbox.current_path = "/firewall/?tab=rules"

    # 要不要再講一次看同一則訊息有沒有寫出完整回答（unless_answered）：只有一句
    # 「帶你過去」時回答靠那顆按鈕，要重來；已經寫好整段說明就不必收回重寫
    only_here = await toolbox.run("show_pages", {"page_ids": ["firewall"]})
    assert toolbox.pages == []
    assert (only_here.needs_reply, only_here.unless_answered) == (True, True)
    assert only_here.result["already_on_page"] == ["防火牆"]
    assert "attached_buttons" not in only_here.result

    mixed = await toolbox.run("show_pages", {"page_ids": ["firewall", "my-resources"]})
    assert [page.path for page in toolbox.pages] == ["/my-resources"]
    assert (mixed.needs_reply, mixed.unless_answered) == (True, True)
    assert mixed.result["already_on_page"] == ["防火牆"]
    assert mixed.result["attached_buttons"] == [toolbox.pages[0].title]

    # 其他情況照舊：成功不必再講，出錯一定要講
    elsewhere = await toolbox.run("show_pages", {"page_ids": ["my-requests"]})
    assert (elsewhere.needs_reply, elsewhere.unless_answered) == (False, False)
    unknown = await toolbox.run("show_pages", {"page_ids": ["nope"]})
    assert (unknown.needs_reply, unknown.unless_answered) == (True, False)


async def test_show_pages_keeps_a_button_that_opens_something_on_the_same_page() -> (
    None
):
    """同一頁但帶開啟方式的按鈕（在「我的申請」直接開申請表單）會做事，照樣附上。"""
    toolbox = _toolbox()
    toolbox.current_path = "/my-requests"

    outcome = await toolbox.run(
        "show_pages", {"page_ids": ["my-requests", "request-form"]}
    )
    assert [(page.path, page.state) for page in toolbox.pages] == [
        ("/my-requests", {"create": True}),
    ]
    assert (outcome.needs_reply, outcome.unless_answered) == (True, True)
    assert len(outcome.result["already_on_page"]) == 1
    assert len(outcome.result["attached_buttons"]) == 1


async def test_show_pages_stops_at_four_buttons_and_says_so() -> None:
    toolbox = _toolbox()
    first = await toolbox.run(
        "show_pages",
        {
            "page_ids": [
                "dashboard",
                "my-resources",
                "my-requests",
                "firewall",
                "account",
            ]
        },
    )
    # 一次呼叫最多取前四個 id
    assert len(first.result["attached_buttons"]) == MAX_PAGE_BUTTONS
    assert [page.path for page in toolbox.pages] == [
        "/dashboard",
        "/my-resources",
        "/my-requests",
        "/firewall",
    ]
    # 滿了之後再要新的：照實說沒附上，模型才不會提到一顆不存在的按鈕
    over = await toolbox.run("show_pages", {"page_ids": ["account"]})
    assert over.needs_reply is True
    assert "error" in over.result and str(MAX_PAGE_BUTTONS) in over.result["error"]
    assert len(toolbox.pages) == MAX_PAGE_BUTTONS
    # 已經附過的再講一次不算錯
    again = await toolbox.run("show_pages", {"page_ids": ["firewall", "account"]})
    assert again.result == {"attached_buttons": [toolbox.pages[3].title]}
    assert again.needs_reply is False


@pytest.mark.parametrize(
    "page_ids",
    [["pve-connections"], ["does-not-exist"], [], [""], [None]],
)
async def test_show_pages_refuses_pages_the_user_cannot_be_sent_to(
    page_ids: list[str],
) -> None:
    toolbox = _toolbox(UserRole.student)
    outcome = await toolbox.run("show_pages", {"page_ids": page_ids})
    assert outcome.needs_reply is True
    assert set(outcome.result) == {"error"}
    assert toolbox.pages == []


# ------------------------------------------------------------ start_flow


async def test_start_flow_builds_the_card_from_the_server_definition() -> None:
    toolbox = _toolbox()
    outcome = await toolbox.run("start_flow", {"flow_id": "request_machine"})
    assert outcome.needs_reply is False
    card = toolbox.flow
    assert card is not None and card.flow_id == "request_machine"
    assert [step.index for step in card.steps] == list(range(len(card.steps)))
    assert outcome.result["attached_flow"] == card.title
    assert outcome.result["steps"] == [
        f"{step.title}：{step.detail}" for step in card.steps
    ]
    # 卡片的每一步都照伺服器端的流程定義：標題、說明、去哪一頁、帶什麼狀態、
    # 是不是由助手就地完成（action）
    definition = next(flow for flow in all_flows() if flow.flow_id == "request_machine")
    assert card.title == definition.title
    assert [
        (step.title, step.detail, step.path, step.state, step.action)
        for step in card.steps
    ] == [
        (step.title, step.detail, step.path, step.state, step.action)
        for step in definition.steps
    ]


@pytest.mark.parametrize("flow_id", ["open_class", "review_requests", "nope", "", None])
async def test_start_flow_rejects_flows_the_user_may_not_use(flow_id: Any) -> None:
    toolbox = _toolbox(UserRole.student)
    outcome = await toolbox.run("start_flow", {"flow_id": flow_id})
    assert outcome.needs_reply is True
    assert set(outcome.result) == {"error"}
    assert toolbox.flow is None


async def test_a_later_flow_replaces_the_earlier_card() -> None:
    toolbox = _toolbox()
    await toolbox.run("start_flow", {"flow_id": "request_machine"})
    await toolbox.run("start_flow", {"flow_id": "publish_service"})
    assert toolbox.flow is not None and toolbox.flow.flow_id == "publish_service"


# ------------------------------------------------------------ plan_machine


async def test_plan_machine_asks_the_next_question_through_the_model() -> None:
    toolbox = _toolbox()
    outcome = await toolbox.run("plan_machine", {"purpose": "架 Flask 網站"})
    assert outcome.needs_reply is True
    assert toolbox.plan is not None and toolbox.plan.status == "ask"
    assert toolbox.plan.question is not None
    assert outcome.result["status"] == "need_answer"
    assert outcome.result["ask_user"] == toolbox.plan.question.text
    assert outcome.result["options_shown_as_buttons"] == toolbox.plan.question.options


async def test_plan_machine_is_done_once_everything_is_known() -> None:
    toolbox = _toolbox()
    outcome = await toolbox.run(
        "plan_machine",
        {
            "purpose": "架 Flask 網站",
            "gpu": "no",
            "display": "cli",
            "duration_days": 30,
        },
    )
    assert outcome.needs_reply is False
    assert outcome.result["status"] == "ready"
    assert toolbox.plan is not None and toolbox.plan.status == "ready"
    assert toolbox.plan.question is None


async def test_plan_machine_questions_follow_the_interface_language() -> None:
    english = _toolbox(lang="en")
    await english.run("plan_machine", {})
    chinese = _toolbox(lang="zh-TW")
    await chinese.run("plan_machine", {})
    assert english.plan is not None and chinese.plan is not None
    assert english.plan.question is not None and chinese.plan.question is not None
    assert english.plan.question.text == translate(
        "aiAssistant.plan.purpose.question", "en"
    )
    assert chinese.plan.question.text == translate(
        "aiAssistant.plan.purpose.question", "zh-TW"
    )
    assert english.plan.question.text != chinese.plan.question.text


# ------------------------------------------------------------ point_at


async def test_point_at_only_accepts_steps_the_page_reported() -> None:
    steps = (GuideStep(id="0", title="標題列"), GuideStep(id="1", title="新增申請"))
    toolbox = _toolbox(guide_steps=steps)
    assert _definition(toolbox, "point_at")["parameters"]["properties"]["target_id"][
        "enum"
    ] == ["0", "1"]

    outcome = await toolbox.run("point_at", {"target_id": "1"})
    assert outcome == ToolOutcome({"pointing_at": "新增申請"}, needs_reply=False)
    assert toolbox.spotlight is not None and toolbox.spotlight.target_id == "1"

    for bad in ("2", "", None, 7, '[data-guide="x"]'):
        fresh = _toolbox(guide_steps=steps)
        rejected = await fresh.run("point_at", {"target_id": bad})
        assert rejected.needs_reply is True
        assert set(rejected.result) == {"error"}
        assert fresh.spotlight is None

    # id 是步驟索引字串；模型把它寫成數字時照樣認得
    numeric = _toolbox(guide_steps=steps)
    await numeric.run("point_at", {"target_id": 1})
    assert numeric.spotlight is not None and numeric.spotlight.target_id == "1"


async def test_point_at_without_reported_steps_points_nowhere() -> None:
    toolbox = _toolbox()
    outcome = await toolbox.run("point_at", {"target_id": "0"})
    assert set(outcome.result) == {"error"}
    assert toolbox.spotlight is None


# ------------------------------------------------------------ get_my_requests


async def test_get_my_requests_hands_the_data_back_to_the_model() -> None:
    toolbox = _toolbox()
    outcome = await toolbox.run("get_my_requests", {})
    assert outcome == ToolOutcome({"requests": _REQUESTS}, needs_reply=True)


async def test_failed_lookup_is_an_error_not_an_empty_list(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """查不到不能當成「沒有申請」：模型會照著告訴使用者他沒有申請過。"""

    async def broken() -> list[dict[str, Any]]:
        raise RuntimeError("db is down")

    toolbox = _toolbox(load_requests=broken)
    with caplog.at_level(logging.ERROR, logger="app.ai.assistant.tools"):
        outcome = await toolbox.run("get_my_requests", {})
    assert outcome.needs_reply is True
    assert set(outcome.result) == {"error"}
    assert "requests" not in outcome.result
    assert "我的申請" in outcome.result["error"]
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1 and errors[0].exc_info is not None


async def test_get_my_requests_is_unknown_when_no_loader_is_wired() -> None:
    toolbox = _toolbox(load_requests=None)
    outcome = await toolbox.run("get_my_requests", {})
    assert set(outcome.result) == {"error"}
    assert outcome.needs_reply is True


# ------------------------------------------------------------ 其他


async def test_unknown_tools_are_reported_back_and_still_recorded() -> None:
    toolbox = _toolbox()
    outcome = await toolbox.run("delete_everything", {"confirm": True})
    assert outcome.needs_reply is True
    assert "delete_everything" in outcome.result["error"]
    assert toolbox.called == ["delete_everything"]
    assert toolbox.pages == [] and toolbox.flow is None and toolbox.plan is None
