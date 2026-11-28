"""發布草稿時，把 pydantic 的驗證錯誤轉成老師看得懂、依語系的一句話。

草稿允許不完整的內容，要到發布才用 EnvironmentCreate 驗證。pydantic 的錯誤
原文是英文，還帶欄位路徑與 type 代碼，不能直接丟給老師。這裡只取第一個錯誤，
依「哪一段、哪一種錯」組句子；schema 裡 validator 自己丟出的訊息本來就是翻好
的句子，原樣帶出（機器的問題前面補上是哪一台）。
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.core.i18n import t

# 欄位沒送、是 None、或是空字串
_BLANK_TYPES = frozenset({"missing", "string_type", "string_too_short"})

_NODE_FIELD_KEYS = {
    "name": "course_env.field_name",
    "role": "course_env.field_role",
    "cpu": "course_env.field_cpu",
    "memory_mb": "course_env.field_memory",
    "disk_gb": "course_env.field_disk",
    "custom_username": "course_env.field_username",
    "source_template_id": "course_env.field_source",
    "custom_image_ref": "course_env.field_source",
}

# 清單超過上限時的訊息；上限數字取自 pydantic 的錯誤內容，不在這裡再寫一份
_TOO_MANY_KEYS = {
    "nodes": "course_env.publish_too_many_machines",
    "edges": "course_env.publish_too_many_edges",
    "publications": "course_env.publish_too_many_publications",
}

_ITEM_INVALID_KEYS = {
    "edges": "course_env.publish_edge_invalid",
    "publications": "course_env.publish_publication_invalid",
}


def _machine_label(configuration: Mapping[str, Any], index: int) -> str:
    """有名稱就用名稱指認，沒有（多半就是名稱沒填）改說第幾台。"""
    nodes = configuration.get("nodes")
    node = nodes[index] if isinstance(nodes, list) and index < len(nodes) else None
    name = node.get("name") if isinstance(node, Mapping) else None
    if isinstance(name, str) and name.strip():
        return t("course_env.publish_machine_named", name=name.strip())
    return t("course_env.publish_machine_numbered", index=index + 1)


def _machine_message(
    configuration: Mapping[str, Any],
    loc: tuple[Any, ...],
    index: int,
    kind: str,
    ctx: Mapping[str, Any],
) -> str:
    machine = _machine_label(configuration, index)
    if kind == "value_error" and ctx.get("error") is not None:
        return t(
            "course_env.publish_machine_detail",
            machine=machine,
            detail=str(ctx["error"]),
        )
    field_key = _NODE_FIELD_KEYS.get(str(loc[2])) if len(loc) >= 3 else None
    field = t(field_key or "course_env.field_setting")
    if kind in _BLANK_TYPES:
        return t("course_env.publish_machine_field_blank", machine=machine, field=field)
    if kind == "string_too_long":
        return t(
            "course_env.publish_machine_field_too_long",
            machine=machine,
            field=field,
            max=ctx.get("max_length"),
        )
    return t("course_env.publish_machine_field_invalid", machine=machine, field=field)


def publish_validation_message(
    exc: ValidationError, configuration: Mapping[str, Any]
) -> str:
    """第一個驗證錯誤對應的訊息（目前請求的語系）。"""
    error = exc.errors(include_url=False)[0]
    loc = tuple(error["loc"])
    kind = str(error["type"])
    ctx: Mapping[str, Any] = error.get("ctx") or {}
    section = loc[0] if loc else None
    # 清單裡第幾筆出錯（從 0 起算）；錯在清單本身或單一欄位時是 None
    index = loc[1] if len(loc) >= 2 and isinstance(loc[1], int) else None

    if section == "nodes" and index is not None:
        return _machine_message(configuration, loc, index, kind, ctx)
    if kind == "value_error" and ctx.get("error") is not None:
        return str(ctx["error"])
    if loc == ("name",):
        if kind in _BLANK_TYPES:
            return t("course_env.publish_name_required")
        if kind == "string_too_long":
            return t("course_env.publish_name_too_long", max=ctx.get("max_length"))
    if loc == ("description",) and kind == "string_too_long":
        return t("course_env.publish_description_too_long", max=ctx.get("max_length"))
    if loc == ("nodes",) and kind in {"missing", "too_short"}:
        return t("course_env.publish_no_machines")
    if len(loc) == 1 and section in _TOO_MANY_KEYS and kind == "too_long":
        return t(_TOO_MANY_KEYS[section], max=ctx.get("max_length"))
    if section in _ITEM_INVALID_KEYS and index is not None:
        return t(_ITEM_INVALID_KEYS[section], index=index + 1)
    return t("course_env.publish_configuration_invalid")


__all__ = ["publish_validation_message"]
