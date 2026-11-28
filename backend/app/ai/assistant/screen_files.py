"""從 ``backend/config/assistant/`` 讀出每個畫面的說明。

一個畫面一個檔（``screens/<畫面 id>.yaml``），新增頁面就是加一個檔。內容是助手
回答的唯一依據，所以載入時就把形狀驗完：格式不對、鍵重複、引用了不存在的片段，
都直接丟例外讓後端啟動失敗，不帶著壞資料跑。內容本身對不對（按鈕名稱是否對得上
語系檔、有沒有描述版面位置）由測試檢查載入後的物件。

寫作規則（違反了就是在幫倒忙）：

1. **不寫版面位置。** 沒有「右上角」「往下捲」「左側清單」。版面會調整，寫死的位置
   過期之後比沒有位置更糟。要指認元素就用畫面上的文字：「按『新增連線』」。
2. **不寫跨頁流程。** 「接著去防火牆開埠」屬於流程（``flows.py``）；這裡只寫這一頁
   的功能怎麼用、彈出視窗怎麼填、什麼情況該改去哪一頁。
3. **只寫查得到的事。** ``constraints`` 必須對得上前端真正的驗證規則；視窗標題與
   開啟按鈕用畫面原文，測試會拿它們比對前端語系檔。
4. **相關頁面只能指向導覽目錄（``catalog.py``）裡的路徑**，助手才帶得過去。

兩種共用寫法，避免同一段內容抄好幾份：

- 檔案最上層的 ``extends: <另一個畫面 id>``：先拿那個畫面的全部內容，再用這個檔
  寫的鍵蓋過去。給「同一頁的另一個網址」用。
- ``use: <片段名稱>``（``shared/<片段名稱>.yaml``）：寫在 ``elements`` 清單裡的一項
  ``- use: x`` 會展開成片段的 ``elements``；寫在某個視窗裡，會把片段的 ``fields``、
  ``notes`` 併進來，視窗自己有寫的優先。

``order`` 決定畫面的排列順序（小的在前，預設 1000）。順序有意義：同一個網址配得上
兩個路徑樣板時取排在前面的那個。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.assistant.catalog import RouteAccess
from app.ai.assistant.specs import (
    DialogField,
    DialogSpec,
    ElementRole,
    ElementSpec,
    RelatedPage,
    SurfaceSpec,
)
from app.utils.strict_yaml import DuplicateYamlKeyError, load_unique_yaml

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config" / "assistant"
SCREENS_DIR = CONFIG_DIR / "screens"
SHARED_DIR = CONFIG_DIR / "shared"

DEFAULT_ORDER = 1000


class ScreenFileError(ValueError):
    """畫面說明檔的格式或引用有問題。訊息裡一定帶檔名。"""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ElementModel(_Strict):
    id: str = Field(min_length=1)
    role: ElementRole
    label: str = Field(min_length=1)
    help: str = ""
    constraints: list[str] = Field(default_factory=list)
    section: str = ""
    sensitive: bool = False


class _DialogFieldModel(_Strict):
    label: str = Field(min_length=1)
    help: str = ""
    required: bool = False


class _DialogModel(_Strict):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    opened_by: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    fields: list[_DialogFieldModel] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    access: RouteAccess = "all"


class _RelatedModel(_Strict):
    path: str = Field(min_length=1)
    when: str = Field(min_length=1)


class _ScreenModel(_Strict):
    id: str = Field(min_length=1)
    path: str = Field(min_length=1, pattern=r"^/")
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    access: RouteAccess = "all"
    order: int = DEFAULT_ORDER
    when_to_use: str = ""
    sections: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    elements: list[_ElementModel] = Field(default_factory=list)
    dialogs: list[_DialogModel] = Field(default_factory=list)
    related: list[_RelatedModel] = Field(default_factory=list)


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        data = load_unique_yaml(path.read_text(encoding="utf-8"))
    except (OSError, DuplicateYamlKeyError, yaml.YAMLError) as exc:
        raise ScreenFileError(f"{path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ScreenFileError(f"{path.name}: the file must be a YAML mapping")
    return data


def _read_dir(directory: Path) -> dict[str, dict[str, Any]]:
    if not directory.is_dir():
        raise ScreenFileError(f"{directory} does not exist")
    return {path.stem: _read_mapping(path) for path in sorted(directory.glob("*.yaml"))}


def _fragment(
    name: Any, fragments: dict[str, dict[str, Any]], file: str
) -> dict[str, Any]:
    if not isinstance(name, str) or name not in fragments:
        raise ScreenFileError(f"{file}: unknown shared fragment {name!r}")
    return fragments[name]


def _expand_uses(
    raw: dict[str, Any], fragments: dict[str, dict[str, Any]], file: str
) -> dict[str, Any]:
    """展開 ``use``。回傳新的 mapping，不改到原本的（片段與 extends 的來源會重複使用）。"""
    result = dict(raw)
    elements = raw.get("elements")
    if isinstance(elements, list):
        expanded: list[Any] = []
        for item in elements:
            if isinstance(item, dict) and set(item) == {"use"}:
                shared = _fragment(item["use"], fragments, file).get("elements")
                if not isinstance(shared, list):
                    raise ScreenFileError(
                        f"{file}: shared fragment {item['use']!r} has no elements list"
                    )
                expanded.extend(shared)
            else:
                expanded.append(item)
        result["elements"] = expanded
    dialogs = raw.get("dialogs")
    if isinstance(dialogs, list):
        merged: list[Any] = []
        for item in dialogs:
            if isinstance(item, dict) and "use" in item:
                own = {key: value for key, value in item.items() if key != "use"}
                merged.append({**_fragment(item["use"], fragments, file), **own})
            else:
                merged.append(item)
        result["dialogs"] = merged
    return result


def _resolve_extends(
    screen_id: str,
    raws: dict[str, dict[str, Any]],
    seen: tuple[str, ...] = (),
) -> dict[str, Any]:
    raw = raws[screen_id]
    base_id = raw.get("extends")
    if base_id is None:
        return raw
    file = f"{screen_id}.yaml"
    if not isinstance(base_id, str) or base_id not in raws:
        raise ScreenFileError(f"{file}: extends unknown screen {base_id!r}")
    if base_id == screen_id or base_id in seen:
        raise ScreenFileError(f"{file}: extends forms a cycle")
    base = _resolve_extends(base_id, raws, (*seen, screen_id))
    own = {key: value for key, value in raw.items() if key != "extends"}
    return {**base, **own}


def _to_spec(model: _ScreenModel) -> SurfaceSpec:
    return SurfaceSpec(
        id=model.id,
        path=model.path,
        title=model.title,
        purpose=model.purpose,
        sections=tuple(model.sections),
        elements=tuple(
            ElementSpec(
                id=item.id,
                role=item.role,
                label=item.label,
                help=item.help,
                constraints=tuple(item.constraints),
                section=item.section,
                sensitive=item.sensitive,
            )
            for item in model.elements
        ),
        access=model.access,
        when_to_use=model.when_to_use,
        features=tuple(model.features),
        dialogs=tuple(
            DialogSpec(
                id=item.id,
                title=item.title,
                opened_by=item.opened_by,
                purpose=item.purpose,
                fields=tuple(
                    DialogField(label=f.label, help=f.help, required=f.required)
                    for f in item.fields
                ),
                notes=tuple(item.notes),
                access=item.access,
            )
            for item in model.dialogs
        ),
        related=tuple(
            RelatedPage(path=item.path, when=item.when) for item in model.related
        ),
    )


def load_screens(
    screens_dir: Path = SCREENS_DIR, shared_dir: Path = SHARED_DIR
) -> tuple[SurfaceSpec, ...]:
    """讀出所有畫面，依 ``order``（相同時依 id）排序。任何問題都丟 ``ScreenFileError``。"""
    fragments = _read_dir(shared_dir) if shared_dir.is_dir() else {}
    raws = _read_dir(screens_dir)
    if not raws:
        raise ScreenFileError(f"{screens_dir} has no screen files")

    models: list[_ScreenModel] = []
    for screen_id in raws:
        file = f"{screen_id}.yaml"
        resolved = _expand_uses(_resolve_extends(screen_id, raws), fragments, file)
        try:
            model = _ScreenModel.model_validate(resolved)
        except ValidationError as exc:
            raise ScreenFileError(f"{file}: {exc}") from exc
        if model.id != screen_id:
            raise ScreenFileError(f"{file}: id {model.id!r} must match the file name")
        models.append(model)

    models.sort(key=lambda model: (model.order, model.id))
    return tuple(_to_spec(model) for model in models)
