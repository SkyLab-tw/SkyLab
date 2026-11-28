"""每個畫面的說明：這一頁在做什麼、怎麼用、有哪些欄位與彈出視窗。

內容不在這裡。一個畫面一個檔，放在 ``backend/config/assistant/screens/``，格式與
寫作規則見 :mod:`app.ai.assistant.screen_files`。這個模組在匯入時把它們讀進來
（格式有問題就丟例外，後端啟動失敗），並提供依身分過濾與查找的函式。
"""

from __future__ import annotations

from collections.abc import Iterable

from app.ai.assistant.catalog import can_access, resolve_user_role
from app.ai.assistant.screen_files import load_screens
from app.ai.assistant.specs import ElementSpec, SurfaceSpec
from app.models import User

_SURFACES: tuple[SurfaceSpec, ...] = load_screens()


def all_surfaces() -> tuple[SurfaceSpec, ...]:
    return _SURFACES


def get_surfaces_for_user(user: User) -> tuple[SurfaceSpec, ...]:
    role = resolve_user_role(user)
    return tuple(s for s in _SURFACES if can_access(s.access, role))


def find_surface(
    surface_id: str, surfaces: Iterable[SurfaceSpec]
) -> SurfaceSpec | None:
    target = (surface_id or "").strip()
    if not target:
        return None
    for surface in surfaces:
        if surface.id == target:
            return surface
    return None


def find_element(surface: SurfaceSpec, element_id: str) -> ElementSpec | None:
    target = (element_id or "").strip()
    if not target:
        return None
    for element in surface.elements:
        if element.id == target:
            return element
    return None
