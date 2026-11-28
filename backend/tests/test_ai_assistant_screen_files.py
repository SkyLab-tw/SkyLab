"""畫面說明檔的載入：格式有問題要直接失敗，不帶著壞資料啟動。

內容對不對（標籤對得上語系檔、不描述版面位置）由 test_ai_assistant_knowledge.py
檢查載入後的物件；這裡只管檔案格式與兩種共用寫法（extends、use）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.assistant import screen_files
from app.ai.assistant.screen_files import ScreenFileError, load_screens
from app.utils.strict_yaml import DuplicateYamlKeyError, load_unique_yaml

_MINIMAL = """\
id: {id}
path: /{id}
title: 測試頁
purpose: 測試用的頁面。
"""


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    screens = tmp_path / "screens"
    shared = tmp_path / "shared"
    screens.mkdir()
    shared.mkdir()
    return screens, shared


def _write(directory: Path, name: str, text: str) -> None:
    (directory / f"{name}.yaml").write_text(text, encoding="utf-8")


def test_shipped_screen_files_load_and_ids_match_file_names() -> None:
    surfaces = load_screens()
    names = {path.stem for path in screen_files.SCREENS_DIR.glob("*.yaml")}
    assert {surface.id for surface in surfaces} == names
    assert len(surfaces) == len(names)


def test_screens_are_sorted_by_order_then_id(tmp_path: Path) -> None:
    screens, shared = _dirs(tmp_path)
    _write(screens, "b", _MINIMAL.format(id="b") + "order: 10\n")
    _write(screens, "a", _MINIMAL.format(id="a") + "order: 20\n")
    _write(screens, "d", _MINIMAL.format(id="d"))
    _write(screens, "c", _MINIMAL.format(id="c"))
    assert [s.id for s in load_screens(screens, shared)] == ["b", "a", "c", "d"]


def test_extends_inherits_everything_and_overrides_only_what_it_sets(
    tmp_path: Path,
) -> None:
    screens, shared = _dirs(tmp_path)
    _write(
        screens,
        "base",
        _MINIMAL.format(id="base")
        + "features:\n  - 按「新增」建立。\n"
        + "elements:\n  - id: base.name\n    role: text\n    label: 名稱\n",
    )
    _write(
        screens,
        "alias",
        "id: alias\npath: /base/:id\nextends: base\ntitle: 另一個網址\n",
    )
    by_id = {s.id: s for s in load_screens(screens, shared)}
    assert by_id["alias"].path == "/base/:id"
    assert by_id["alias"].title == "另一個網址"
    assert by_id["alias"].purpose == by_id["base"].purpose
    assert by_id["alias"].features == by_id["base"].features
    assert by_id["alias"].elements == by_id["base"].elements


def test_use_expands_shared_elements_in_place_and_merges_dialog_fields(
    tmp_path: Path,
) -> None:
    screens, shared = _dirs(tmp_path)
    _write(
        shared,
        "common-elements",
        "elements:\n"
        "  - id: common.a\n    role: text\n    label: 甲\n"
        "  - id: common.b\n    role: text\n    label: 乙\n",
    )
    _write(
        shared,
        "common-dialog",
        "fields:\n  - label: 名稱\n    required: true\nnotes:\n  - 共用的注意事項\n",
    )
    _write(
        screens,
        "page",
        _MINIMAL.format(id="page") + "elements:\n"
        "  - id: page.first\n    role: button\n    label: 最前面\n"
        "  - use: common-elements\n"
        "  - id: page.last\n    role: button\n    label: 最後面\n"
        "dialogs:\n"
        "  - id: create\n    title: 新增\n    opened_by: 新增\n    purpose: 建立一筆。\n"
        "    use: common-dialog\n"
        "  - id: edit\n    title: 編輯\n    opened_by: 編輯\n    purpose: 修改一筆。\n"
        "    use: common-dialog\n    notes:\n      - 這個視窗自己的注意事項\n",
    )
    (page,) = load_screens(screens, shared)
    assert [e.id for e in page.elements] == [
        "page.first",
        "common.a",
        "common.b",
        "page.last",
    ]
    create, edit = page.dialogs
    assert [f.label for f in create.fields] == ["名稱"]
    assert create.fields[0].required is True
    assert create.notes == ("共用的注意事項",)
    # 視窗自己有寫的優先於片段
    assert edit.notes == ("這個視窗自己的注意事項",)
    assert edit.fields == create.fields


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        (
            "page",
            "id: other\npath: /page\ntitle: 頁\npurpose: 用途。\n",
            "must match the file name",
        ),
        ("page", "id: page\npath: page\ntitle: 頁\npurpose: 用途。\n", "path"),
        ("page", "id: page\npath: /page\ntitle: 頁\n", "purpose"),
        ("page", _MINIMAL.format(id="page") + "access: teacher\n", "access"),
        ("page", _MINIMAL.format(id="page") + "typo_key: 1\n", "typo_key"),
        ("page", _MINIMAL.format(id="page") + "order: 很前面\n", "order"),
        (
            "page",
            _MINIMAL.format(id="page") + "title: 重複的鍵\n",
            "Duplicate YAML key",
        ),
        ("page", "- 不是 mapping\n", "must be a YAML mapping"),
        ("page", "id: page\n  path: [壞掉的縮排\n", "page.yaml"),
        (
            "page",
            _MINIMAL.format(id="page")
            + "elements:\n  - id: page.x\n    role: slider\n    label: 滑桿\n",
            "role",
        ),
        (
            "page",
            _MINIMAL.format(id="page") + "elements:\n  - use: missing-fragment\n",
            "unknown shared fragment",
        ),
        (
            "page",
            _MINIMAL.format(id="page")
            + "dialogs:\n  - id: d\n    title: 視窗\n    opened_by: 開\n    purpose: 用途。\n"
            "    use: missing-fragment\n",
            "unknown shared fragment",
        ),
        ("page", "id: page\npath: /page\nextends: nobody\n", "extends unknown screen"),
        ("page", "id: page\npath: /page\nextends: page\n", "cycle"),
    ],
)
def test_bad_files_stop_loading_and_name_the_file(
    tmp_path: Path, name: str, text: str, message: str
) -> None:
    screens, shared = _dirs(tmp_path)
    _write(screens, name, text)
    with pytest.raises(ScreenFileError) as error:
        load_screens(screens, shared)
    assert f"{name}.yaml" in str(error.value)
    assert message in str(error.value)


def test_extends_cycle_between_two_files_is_rejected(tmp_path: Path) -> None:
    screens, shared = _dirs(tmp_path)
    _write(screens, "a", "id: a\npath: /a\nextends: b\n")
    _write(screens, "b", "id: b\npath: /b\nextends: a\n")
    with pytest.raises(ScreenFileError, match="cycle"):
        load_screens(screens, shared)


def test_shared_fragment_without_elements_cannot_be_used_as_elements(
    tmp_path: Path,
) -> None:
    screens, shared = _dirs(tmp_path)
    _write(shared, "dialog-only", "fields:\n  - label: 名稱\n")
    _write(
        screens,
        "page",
        _MINIMAL.format(id="page") + "elements:\n  - use: dialog-only\n",
    )
    with pytest.raises(ScreenFileError, match="has no elements list"):
        load_screens(screens, shared)


def test_empty_or_missing_directory_is_an_error(tmp_path: Path) -> None:
    screens, shared = _dirs(tmp_path)
    with pytest.raises(ScreenFileError, match="no screen files"):
        load_screens(screens, shared)
    with pytest.raises(ScreenFileError, match="does not exist"):
        load_screens(tmp_path / "nowhere", shared)


def test_strict_yaml_rejects_duplicate_keys_at_any_depth() -> None:
    assert load_unique_yaml("a: 1\nb:\n  c: 2\n") == {"a": 1, "b": {"c": 2}}
    with pytest.raises(DuplicateYamlKeyError):
        load_unique_yaml("a: 1\na: 2\n")
    with pytest.raises(DuplicateYamlKeyError):
        load_unique_yaml("outer:\n  inner: 1\n  inner: 2\n")
