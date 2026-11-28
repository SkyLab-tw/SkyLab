"""The assistant's page catalogue must describe the router the frontend actually has.

Before this guard existed the catalogue still served paths like /applications and
/admin/domains, and the frontend carried a PATH_MAP translation table to patch
them up at runtime.  A stale entry is worse than a missing one: the assistant
confidently sends the user to a route that redirects them away.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.ai.assistant.catalog import all_routes, can_access
from app.ai.assistant.flows import all_flows
from app.models.user import UserRole

_APP_JSX = Path(__file__).resolve().parents[2] / "frontend" / "src" / "App.jsx"
_PATH_ATTR = re.compile(r'path="([^"]+)"')


def _router_paths() -> set[str]:
    source = _APP_JSX.read_text(encoding="utf-8")
    paths = set()
    for raw in _PATH_ATTR.findall(source):
        # 帶參數與萬用路由無法直接導覽，導覽目錄本來就不該收錄。
        if ":" in raw or "*" in raw:
            continue
        paths.add(raw)
    return paths


def test_app_jsx_is_readable() -> None:
    assert _APP_JSX.exists(), f"找不到前端路由表：{_APP_JSX}"
    assert _router_paths(), "沒有從 App.jsx 解析到任何路由，正則可能要更新"


@pytest.mark.parametrize("route", all_routes(), ids=lambda route: route.path)
def test_every_catalog_path_exists_in_the_router(route) -> None:
    assert route.path in _router_paths(), (
        f"導覽目錄的 {route.path} 不在 App.jsx 的路由表裡"
    )


@pytest.mark.parametrize("flow", all_flows(), ids=lambda flow: flow.flow_id)
def test_every_flow_step_points_at_a_catalog_route(flow) -> None:
    catalog_paths = {route.path for route in all_routes()}
    for step in flow.steps:
        assert step.path in catalog_paths, (
            f"流程 {flow.flow_id} 的步驟「{step.title}」指向未登錄的 {step.path}"
        )


@pytest.mark.parametrize("flow", all_flows(), ids=lambda flow: flow.flow_id)
def test_flow_steps_are_reachable_by_everyone_allowed_into_the_flow(flow) -> None:
    """流程不能包含使用者打不開的頁面，否則走到一半就卡住。

    存取層級不是單純的階層（learner 是學生或管理員、staff 是教師或管理員），所以
    逐個身分檢查：進得了這條流程的人，每一步的頁面都要打得開。
    """
    routes = {route.path: route for route in all_routes()}
    allowed_roles = [role for role in UserRole if can_access(flow.access, role)]
    assert allowed_roles, f"流程 {flow.flow_id} 沒有任何身分用得到"
    for step in flow.steps:
        step_access = routes[step.path].access
        for role in allowed_roles:
            assert can_access(step_access, role), (
                f"流程 {flow.flow_id}（{flow.access}）的步驟「{step.title}」"
                f"需要 {step_access} 權限，{role.value} 打不開"
            )


@pytest.mark.parametrize(
    ("access", "roles"),
    [
        ("all", {UserRole.student, UserRole.teacher, UserRole.admin}),
        # 學生的課程頁：老師會被導回首頁，所以不是 all
        ("learner", {UserRole.student, UserRole.admin}),
        ("staff", {UserRole.teacher, UserRole.admin}),
        ("admin", {UserRole.admin}),
    ],
)
def test_access_levels_map_to_the_roles_that_may_enter(access, roles) -> None:
    assert {role for role in UserRole if can_access(access, role)} == roles


def test_every_route_and_flow_uses_a_known_access_level() -> None:
    known = {"all", "learner", "staff", "admin"}
    assert {route.access for route in all_routes()} <= known
    assert {flow.access for flow in all_flows()} <= known


def test_catalog_paths_are_unique() -> None:
    paths = [route.path for route in all_routes()]
    assert len(paths) == len(set(paths))


def test_flow_ids_are_unique() -> None:
    ids = [flow.flow_id for flow in all_flows()]
    assert len(ids) == len(set(ids))


def test_all_workflow_cards_keep_details_short() -> None:
    """流程卡每一步只有一句短提示（面板很窄），細節由助手的回答補。"""
    for flow in all_flows():
        assert flow.title.strip() and flow.summary.strip(), flow.flow_id
        assert flow.steps, flow.flow_id
        for step in flow.steps:
            assert step.title.strip(), flow.flow_id
            assert len(step.detail) <= 28, (flow.flow_id, step.title)


def test_flow_step_actions_are_known() -> None:
    """前端只認得 "recommend"（由助手就地規劃配置）；其他值會讓那一步點了沒反應。"""
    for flow in all_flows():
        for step in flow.steps:
            assert step.action in {None, "recommend"}, (flow.flow_id, step.title)
