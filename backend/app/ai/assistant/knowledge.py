"""把畫面定義組成模型讀得懂的說明，並把畫面對應到可以前往的頁面。

這裡不做任何判斷，只排版：答案的依據就是 ``backend/config/assistant/screens/`` 裡
寫好的字，模型負責把它講成使用者聽得懂的話。同一份排版也是模型不可用時的後備
（``render_page_guide``），所以助手在模型離線時仍然有東西可以回。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.ai.assistant.catalog import (
    NavigationRoute,
    can_access,
    find_route_by_path,
)
from app.ai.assistant.schemas import PageTarget
from app.ai.assistant.specs import DialogSpec, ElementState, SurfaceSpec
from app.ai.assistant.surfaces import find_element
from app.models.user import UserRole

# 同一個路徑上的第二個畫面要帶什麼 location state 才會直接打開。
_NAV_STATE: dict[str, dict[str, Any]] = {"request-form": {"create": True}}


def visible_dialogs(surface: SurfaceSpec, role: UserRole) -> tuple[DialogSpec, ...]:
    """這個身分在這頁看得到的視窗。看不到的連提都不提，免得照著找卻找不到。"""
    return tuple(
        dialog for dialog in surface.dialogs if can_access(dialog.access, role)
    )


def catalog_surfaces(surfaces: Iterable[SurfaceSpec]) -> list[SurfaceSpec]:
    """給模型挑的頁面清單。說明完全相同的畫面只留一個（同一頁的不同網址）。"""
    seen: set[tuple[str, str, str]] = set()
    result: list[SurfaceSpec] = []
    for surface in surfaces:
        key = (surface.title, surface.purpose, surface.when_to_use)
        if key in seen:
            continue
        seen.add(key)
        result.append(surface)
    return result


def catalog_lines(surfaces: Iterable[SurfaceSpec]) -> str:
    lines = []
    for surface in surfaces:
        line = f"- {surface.id}｜{surface.title}｜{surface.purpose}"
        if surface.when_to_use:
            line += f"｜何時用：{surface.when_to_use}"
        lines.append(line)
    return "\n".join(lines)


def match_surface(
    surfaces: Iterable[SurfaceSpec], path: str | None, surface_id: str | None
) -> SurfaceSpec | None:
    """使用者眼前是哪個畫面。

    前端回報的 ``surface_id`` 只在它的路徑樣板對得上目前路徑時才採用——同一個
    路徑可能有兩個畫面（申請列表與申請表單），要靠 id 分辨，但 id 不能把人帶到
    另一頁的說明去。
    """
    clean = (path or "").split("?")[0].rstrip("/") or "/"
    matched = [
        surface
        for surface in surfaces
        if re.fullmatch(re.sub(r":[^/]+", "[^/]+", surface.path), clean)
    ]
    if not matched:
        return None
    for surface in matched:
        if surface.id == surface_id:
            return surface
    # 完全相同的路徑優先於帶參數的樣板（/course-template-management/new）
    exact = [surface for surface in matched if surface.path == clean]
    return (exact or matched)[0]


def _dialog_block(dialog: DialogSpec) -> str:
    lines = [
        f"- 視窗「{dialog.title}」（按「{dialog.opened_by}」開啟）：{dialog.purpose}"
    ]
    for item in dialog.fields:
        tag = "（必填）" if item.required else ""
        detail = f"：{item.help}" if item.help else ""
        lines.append(f"  - 「{item.label}」{tag}{detail}")
    lines.extend(f"  - 注意：{note}" for note in dialog.notes)
    return "\n".join(lines)


def render_help(
    surface: SurfaceSpec,
    *,
    role: UserRole,
    routes: Iterable[NavigationRoute],
) -> str:
    """一個畫面的完整說明，給模型當依據。純文字、不寫版面位置。"""
    parts = [
        f"【{surface.title}】（頁面 id：{surface.id}）",
        f"用途：{surface.purpose}",
    ]
    if surface.when_to_use:
        parts.append(f"什麼時候用：{surface.when_to_use}")
    if surface.features:
        parts.append("功能：\n" + "\n".join(f"- {item}" for item in surface.features))
    dialogs = visible_dialogs(surface, role)
    if dialogs:
        parts.append("會跳出的視窗：\n" + "\n".join(_dialog_block(d) for d in dialogs))
    described = [
        element for element in surface.elements if element.help or element.constraints
    ]
    if described:
        lines = []
        for element in described:
            line = f"- 「{element.label}」"
            if element.section:
                line += f"（{element.section}）"
            if element.help:
                line += f"：{element.help}"
            if element.constraints:
                line += f" 限制：{'、'.join(element.constraints)}。"
            lines.append(line)
        parts.append("欄位與控制項：\n" + "\n".join(lines))
    plain = [
        element.label
        for element in surface.elements
        if element.label and not (element.help or element.constraints)
    ]
    if plain:
        parts.append("其他元素：" + "、".join(dict.fromkeys(plain)))
    allowed = list(routes)
    related = []
    for item in surface.related:
        route = find_route_by_path(item.path, allowed)
        if route is not None:
            related.append(f"- {route.title}：{item.when}")
    if related:
        parts.append("要做的事不在這頁時：\n" + "\n".join(related))
    return "\n".join(parts)


def live_state(
    surface: SurfaceSpec,
    state: dict[str, ElementState],
    active_target: str | None,
) -> dict[str, Any] | None:
    """前端回報的即時狀態，只留這個畫面宣告過的元素。

    標籤永遠用伺服器端的定義；敏感欄位只說有沒有填，不把內容送進 prompt。
    """
    elements: list[dict[str, Any]] = []
    for spec in surface.elements:
        current = state.get(spec.id)
        if current is None:
            continue
        item: dict[str, Any] = {"label": spec.label}
        if current.value is not None:
            if spec.sensitive:
                item["filled"] = bool(current.value)
            else:
                item["value"] = current.value
        if current.error:
            item["error"] = current.error
        if current.disabled is not None:
            item["disabled"] = current.disabled
        if current.disabled_reason:
            item["disabled_reason"] = current.disabled_reason
        elements.append(item)
    focused = find_element(surface, active_target or "")
    if not elements and focused is None:
        return None
    result: dict[str, Any] = {"elements": elements}
    if focused is not None:
        result["focused"] = focused.label
    return result


def page_target(
    surface: SurfaceSpec, routes: Iterable[NavigationRoute]
) -> PageTarget | None:
    """畫面對應到哪顆可以點的頁面按鈕；去不了就回 None。

    帶參數的畫面（某一台機器、某一個班級）沒辦法直接前往，改帶到它的上一層
    清單，並說明要從那裡點進去。
    """
    allowed = list(routes)
    route = find_route_by_path(surface.path, allowed)
    if route is not None:
        return PageTarget(
            title=surface.title,
            path=route.path,
            reason=surface.when_to_use or route.summary,
            state=_NAV_STATE.get(surface.id),
        )
    path = surface.path
    while path.count("/") > 1:
        path = path.rsplit("/", 1)[0]
        route = find_route_by_path(path, allowed)
        if route is not None:
            return PageTarget(
                title=route.title,
                path=route.path,
                reason=f"從「{route.title}」點進去就是「{surface.title}」。",
            )
    return None


def related_targets(
    surface: SurfaceSpec, routes: Iterable[NavigationRoute]
) -> list[PageTarget]:
    """這頁的相關頁面，只留使用者有權限去的。"""
    allowed = list(routes)
    targets: list[PageTarget] = []
    for item in surface.related:
        route = find_route_by_path(item.path, allowed)
        if route is not None:
            targets.append(
                PageTarget(title=route.title, path=route.path, reason=item.when)
            )
    return targets


def render_page_guide(surface: SurfaceSpec, *, role: UserRole) -> str:
    """模型不可用時的後備回答：照定義排版的整頁說明（markdown）。"""
    parts = [f"**{surface.title}**：{surface.purpose}"]
    if surface.when_to_use:
        parts.append(f"**什麼時候用**：{surface.when_to_use}")
    if surface.features:
        parts.append(
            "**怎麼用**\n" + "\n".join(f"- {item}" for item in surface.features)
        )
    dialogs = visible_dialogs(surface, role)
    if dialogs:
        lines = []
        for dialog in dialogs:
            required = [item.label for item in dialog.fields if item.required]
            line = f"- **{dialog.title}**（按「{dialog.opened_by}」開啟）：{dialog.purpose}"
            if required:
                line += f"必填：{'、'.join(required)}。"
            lines.append(line)
        parts.append("**會跳出的視窗**\n" + "\n".join(lines))
    return "\n\n".join(parts)
