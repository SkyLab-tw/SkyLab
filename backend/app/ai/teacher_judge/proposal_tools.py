"""Checklist proposal tool schemas and request-scoped tool construction (package-internal)."""

from __future__ import annotations

import copy
from typing import Any

from app.ai.teacher_judge.check_plan_contract import typed_step_tool_schema
from app.ai.teacher_judge.machine_context import PEER_IP_TOKEN

LIST_CHECKLIST_TOOL_NAME = "list_checklist"
GET_CHECKLIST_ITEM_TOOL_NAME = "get_checklist_item"
CREATE_CHECKLIST_ITEM_TOOL_NAME = "create_checklist_item"
EDIT_CHECKLIST_ITEM_TOOL_NAME = "edit_checklist_item"


# All proposal modes use the same typed write schema.
_CHECKLIST_STEP_TOOL_SCHEMA = typed_step_tool_schema()


PROPOSAL_FILL_PROPERTIES: dict[str, Any] = {
    "title": {"type": "string", "description": "檢查項目名稱"},
    "target_node_key": {
        "type": ["string", "null"],
        "description": (
            "班級拓撲中要執行檢查的邏輯機器；可依提示使用 P1/P2，後端會保存為 node_key。"
            "拓撲有兩台以上機器而老師沒有指定、名稱或角色也無法唯一對應時，"
            "不要猜測任一台、不要呼叫此工具；改在 reply 詢問要檢查哪一台。"
        ),
    },
    "peer_node_key": {
        "type": ["string", "null"],
        "description": (
            "選填；由執行節點觀察的同班級邏輯機器。"
            f"只有宣告 peer 時才能將 {PEER_IP_TOKEN} 作為完整 argv element"
        ),
    },
    "checked": {
        "type": "boolean",
        "description": "是否已達成；只有老師明確要求或已有直接證據時才能改，新項目為 false",
    },
    "detectable": {
        "type": "string",
        "enum": ["auto", "partial", "manual"],
        "description": "腳本取證支援：auto=可執行取證、partial=缺少資訊、manual=不支援",
    },
    "judgement_mode": {
        "type": "string",
        "enum": ["ai", "teacher"],
        "description": "結果核對方式：ai=系統自動核對、teacher=導師依腳本證據核查",
    },
    "detection_method": {
        "type": ["string", "null"],
        "description": "腳本取證方式說明（detectable=auto/partial 時填寫）",
    },
    "fallback": {
        "type": ["string", "null"],
        "description": "manual 時的替代建議；auto 不得提供",
    },
    "missing_information": {
        "type": "array",
        "items": {"type": "string"},
        "description": "partial 時逐項列出尚缺的資訊",
    },
    "check_steps": {
        "type": "array",
        "items": _CHECKLIST_STEP_TOOL_SCHEMA,
        "description": "完整 typed check_steps；每步含 id、title、collector，ai 模式含 assertion，teacher 模式省略。此欄位整體替換，不能遺漏既有步驟。",
    },
}

_LIST_CHECKLIST_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LIST_CHECKLIST_TOOL_NAME,
        "description": (
            "列出目前檢查表的所有項目（ID、標題、detectable、judgement_mode）。"
            "需要修改、刪除或引用既有項目，或重新核查整張檢查表時使用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}

_GET_CHECKLIST_ITEM_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": GET_CHECKLIST_ITEM_TOOL_NAME,
        "description": "以 ID 查詢單一檢查項目的完整內容；修改既有項目前必須先用它確認。",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "list_checklist 回傳的項目 ID",
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
}

_CREATE_CHECKLIST_ITEM_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": CREATE_CHECKLIST_ITEM_TOOL_NAME,
        "description": (
            "建立全新檢查項目的新增提案，老師確認套用後才會寫入檢查表。"
            "只需填 title 與已知欄位；留空欄位使用系統預設；系統會自動指定項目 ID。"
            "標題與既有項目重複時會被拒絕；請改用 edit_checklist_item 修改，"
            "或改用更精確的標題後重新建立。"
        ),
        "parameters": {
            "type": "object",
            "properties": PROPOSAL_FILL_PROPERTIES,
            "required": ["title"],
            "additionalProperties": False,
        },
    },
}

_EDIT_CHECKLIST_ITEM_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": EDIT_CHECKLIST_ITEM_TOOL_NAME,
        "description": (
            "對既有檢查項目送出修改提案，老師確認套用後才會寫入檢查表。"
            "必須先用 get_checklist_item 確認項目 ID 並讀取完整內容，list_checklist 摘要不算完成讀取；"
            "只填有變動的欄位，省略的欄位維持原值，要清空時明確填 null 或空陣列。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "既有項目 ID"},
                **PROPOSAL_FILL_PROPERTIES,
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
}

_PROPOSAL_TOOLS: list[dict[str, Any]] = [
    _LIST_CHECKLIST_TOOL,
    _GET_CHECKLIST_ITEM_TOOL,
    _CREATE_CHECKLIST_ITEM_TOOL,
    _EDIT_CHECKLIST_ITEM_TOOL,
]


PROPOSAL_TOOL_NAMES = frozenset(tool["function"]["name"] for tool in _PROPOSAL_TOOLS)

# Chat proposals only accept complete (auto) items, so the model never sees the
# partial/manual vocabulary; the server fills detectability itself. Edit keeps
# missing_information only so resolved gaps of a stored item can be cleared.
_CHAT_HIDDEN_FILL_FIELDS = {
    CREATE_CHECKLIST_ITEM_TOOL_NAME: ("detectable", "missing_information", "fallback"),
    EDIT_CHECKLIST_ITEM_TOOL_NAME: ("detectable", "fallback"),
}
_CHAT_EDIT_MISSING_INFORMATION_DESCRIPTION = (
    "既有項目尚未補齊的缺口；老師已補齊的缺口要移除，全部補齊時填 []。不得新增缺口。"
)
_CHAT_TOOL_DESCRIPTIONS = {
    CREATE_CHECKLIST_ITEM_TOOL_NAME: (
        "為一條資訊完整的新檢查需求建立新增提案，老師確認套用後才寫入檢查表。"
        "只在機器、檢查對象與判定方式都確定時呼叫；缺任何一項時不要呼叫，改在回覆詢問老師。"
        "檔案路徑與 target_node_key 只能取自老師訊息、附件或對話，不得自行代入預設位置或自選機器。"
        "同標題已存在時會被拒絕，請改用 edit_checklist_item。"
    ),
    EDIT_CHECKLIST_ITEM_TOOL_NAME: (
        "對既有檢查項目送出修改提案，老師確認套用後才寫入檢查表。"
        "必須先呼叫 get_checklist_item 讀取完整內容；只在修改後資訊完整時呼叫，只填要變更的欄位。"
    ),
}


_CHAT_JUDGEMENT_MODE_DESCRIPTION = (
    "ai=依 assertion 自動判定；teacher=只收集結果給老師查看，不放 assertion"
)
_CHAT_DETECTION_METHOD_DESCRIPTION = "一句話說明系統如何取證"


def build_proposal_tools(
    machine_entries: list[dict[str, Any]] | None = None,
    *,
    chat: bool = False,
) -> list[dict[str, Any]]:
    """Build request-scoped node enums without mutating shared tool schemas."""
    tools = copy.deepcopy(_PROPOSAL_TOOLS)
    if chat:
        for tool in tools:
            function = tool["function"]
            description = _CHAT_TOOL_DESCRIPTIONS.get(function["name"])
            if description is None:
                continue
            function["description"] = description
            properties = function["parameters"]["properties"]
            for field_name in _CHAT_HIDDEN_FILL_FIELDS[function["name"]]:
                properties.pop(field_name, None)
            properties["judgement_mode"] = {
                **properties["judgement_mode"],
                "description": _CHAT_JUDGEMENT_MODE_DESCRIPTION,
            }
            properties["detection_method"] = {
                **properties["detection_method"],
                "description": _CHAT_DETECTION_METHOD_DESCRIPTION,
            }
            if "missing_information" in properties:
                properties["missing_information"] = {
                    **properties["missing_information"],
                    "description": _CHAT_EDIT_MISSING_INFORMATION_DESCRIPTION,
                }
    if machine_entries is None:
        return tools
    node_keys = [
        str(entry.get("node_key") or "").strip()
        for entry in machine_entries
        if str(entry.get("node_key") or "").strip()
    ]
    aliases = "，".join(
        f"{entry.get('display_label')}={entry.get('node_key')}"
        for entry in machine_entries
        if entry.get("display_label") and entry.get("node_key")
    )
    for tool in tools:
        function = tool.get("function") or {}
        properties = (function.get("parameters") or {}).get("properties") or {}
        for field_name in ("target_node_key", "peer_node_key"):
            field = properties.get(field_name)
            if isinstance(field, dict):
                field["enum"] = [*node_keys, None]
                if aliases:
                    field["description"] = f"{field.get('description', '')}；{aliases}"
    return tools
