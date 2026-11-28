"""讀人手維護的 YAML 設定檔：重複的鍵直接報錯，不默默用後面的蓋掉前面的。"""

from __future__ import annotations

from typing import Any

import yaml


class DuplicateYamlKeyError(ValueError):
    """同一個 mapping 裡出現兩次相同的鍵。"""


class _UniqueKeyLoader(yaml.SafeLoader):  # type: ignore[misc]
    """SafeLoader，但 mapping 的鍵不可重複。"""


def _unique_mapping(loader: Any, node: Any) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise DuplicateYamlKeyError(
                "YAML mapping keys must be scalar values"
            ) from exc
        if duplicate:
            raise DuplicateYamlKeyError(f"Duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def load_unique_yaml(text: str) -> Any:
    """解析一份 YAML 文字；鍵重複或語法錯誤都會丟例外。"""
    return yaml.load(text, Loader=_UniqueKeyLoader)
