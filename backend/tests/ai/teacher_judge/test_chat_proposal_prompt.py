"""Chat proposal prompt, tool schema and tool-loop stop rules (is_refine=False)."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.teacher_judge import (
    attachment_itemwise,
    chat_transport,
    proposal_replies,
    proposal_tools,
    service,
)
from app.ai.teacher_judge.prompt import (
    CHAT_PROPOSAL_SYSTEM_TEMPLATE,
    FINALIZER_CHECK_PLAN_CONTRACT_INSTRUCTION,
    SITUATION_REFINE,
)
from app.ai.teacher_judge.template_command_service import GENERAL_COMMAND
from tests.ai.teacher_judge.helpers import (
    patch_teacher_judge_vllm_settings,
    reply_message,
    scripted_vllm,
    tool_call_message,
)

_TOOL_NAMES = {
    "list_checklist",
    "get_checklist_item",
    "create_checklist_item",
    "edit_checklist_item",
}
_MACHINES = [
    {"display_label": "P1", "node_key": "web"},
    {"display_label": "P2", "node_key": "db"},
]


def _complete_create(
    title: str, argv: list[str], step_id: str = "check.1"
) -> dict[str, Any]:
    return {
        "title": title,
        "judgement_mode": "ai",
        "detection_method": "執行唯讀指令。",
        "check_steps": [
            {
                "id": step_id,
                "title": "唯讀取證",
                "collector": {"type": "command", "argv": argv},
                "assertion": {"type": "returncode_equals", "expected": 0},
            }
        ],
    }


def _relative_path_create(title: str = "執行 main.py") -> dict[str, Any]:
    return _complete_create(title, ["python3", "main.py"])


def _tool_calls_message(*calls: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
            for index, (name, arguments) in enumerate(calls, start=1)
        ],
    }


def _section(prompt: str, heading: str) -> str:
    match = re.search(rf"^# {heading}\n(.*?)(?=^# |\Z)", prompt, re.S | re.M)
    assert match is not None, heading
    return match.group(1)


async def _chat(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[object],
    content: str = "檢查服務",
    **kwargs: Any,
):
    calls, fake = scripted_vllm(responses)
    monkeypatch.setattr(chat_transport, "call_vllm_message", fake)
    patch_teacher_judge_vllm_settings(monkeypatch)
    kwargs.setdefault("rubric_context", json.dumps({"items": []}))
    kwargs.setdefault("template_key", "linux")
    kwargs.setdefault("rubric_available", True)
    result = await service.chat_with_rubric(
        messages=[SimpleNamespace(role="user", content=content)], **kwargs
    )
    return calls, result


# ------------------------------------------------------------------ prompt


@pytest.mark.parametrize("rubric_available", [True, False])
async def test_chat_prompt_has_each_section_once_without_fill_vocabulary(
    monkeypatch: pytest.MonkeyPatch, rubric_available: bool
) -> None:
    calls, _result = await _chat(
        monkeypatch,
        [reply_message("好的。", "none")],
        template_commands=[GENERAL_COMMAND],
        machine_context="P1：web\nP2：db",
        machine_entries=_MACHINES,
        rubric_available=rubric_available,
    )

    prompt = calls[0]["messages"][0]["content"]
    tool_tag = "allowed_tools" if rubric_available else "no_tools"
    lines = prompt.splitlines()
    assert lines.count(f"<{tool_tag}>") == 1
    assert lines.count(f"</{tool_tag}>") == 1
    # Only the tool section is XML; rules are Markdown so no tag reads as a tool.
    assert {
        line.strip("</>") for line in lines if re.fullmatch(r"</?[a-z_]+>", line)
    } == {tool_tag}
    for heading in (
        "逐條判斷",
        "缺資訊判準",
        "判定方式",
        "工具結果處理",
        "最終回覆格式",
    ):
        assert lines.count(f"# {heading}") == 1, heading
    for word in ("partial", "manual", "detectable", "fallback"):
        assert word not in prompt
    # missing_information only names reply-focus gaps, never item fill fields.
    outside_answer = prompt.replace(_section(prompt, "最終回覆格式"), "")
    assert "missing_information" not in outside_answer
    # No copyable example sentence or value for the version-check request.
    assert "檢查 Python 版本" not in prompt
    assert "3.12" not in prompt
    rules = prompt
    for heading in ("缺資訊判準", "檢查步驟格式", "環境"):
        rules = rules.replace(_section(prompt, heading), "")
    assert "絕對路徑" not in rules


async def test_chat_prompt_keeps_machine_follow_up_rule_only_in_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _result = await _chat(
        monkeypatch,
        [reply_message("好的。", "none")],
        machine_context="P1：web\nP2：db",
        machine_entries=_MACHINES,
    )

    prompt = calls[0]["messages"][0]["content"]
    assert "列出可選機器並詢問要檢查哪一台" in _section(prompt, "缺資訊判準")
    assert prompt.count("列出可選機器") == 1


async def test_refine_prompt_still_uses_refine_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _result = await _chat(
        monkeypatch,
        [reply_message("已潤飾。", "none")],
        is_refine=True,
        rubric_context=json.dumps({"items": [{"id": "a", "title": "A"}]}),
    )

    prompt = calls[0]["messages"][0]["content"]
    assert SITUATION_REFINE.strip() in prompt
    assert FINALIZER_CHECK_PLAN_CONTRACT_INSTRUCTION.strip() in prompt
    assert "# 逐條判斷" not in prompt
    assert CHAT_PROPOSAL_SYSTEM_TEMPLATE.splitlines()[1] not in prompt


# ------------------------------------------------------------------ schema


def _properties(tools: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for tool in tools:
        if tool["function"]["name"] == name:
            return tool["function"]["parameters"]["properties"]
    raise AssertionError(name)


def test_chat_tool_schema_hides_fill_fields_and_keeps_node_fields() -> None:
    chat_tools = proposal_tools.build_proposal_tools(_MACHINES, chat=True)
    refine_tools = proposal_tools.build_proposal_tools(_MACHINES)

    create = _properties(chat_tools, "create_checklist_item")
    edit = _properties(chat_tools, "edit_checklist_item")
    for field_name in ("detectable", "missing_information", "fallback"):
        assert field_name not in create
    for field_name in ("detectable", "fallback"):
        assert field_name not in edit
    assert "老師已補齊的缺口要移除" in edit["missing_information"]["description"]
    for name in ("create_checklist_item", "edit_checklist_item"):
        chat_properties = _properties(chat_tools, name)
        refine_properties = _properties(refine_tools, name)
        assert (
            chat_properties["target_node_key"] == refine_properties["target_node_key"]
        )
        assert "partial" not in json.dumps(chat_properties, ensure_ascii=False)
        assert "manual" not in chat_properties["judgement_mode"]["description"]
    assert {tool["function"]["name"] for tool in chat_tools} == _TOOL_NAMES


def test_refine_tool_schema_is_unchanged() -> None:
    assert proposal_tools.build_proposal_tools() == proposal_tools._PROPOSAL_TOOLS
    refine_create = _properties(
        proposal_tools.build_proposal_tools(), "create_checklist_item"
    )
    assert "detectable" in refine_create
    assert "missing_information" in refine_create


async def test_chat_create_without_detectable_stages_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, result = await _chat(
        monkeypatch,
        [
            tool_call_message(
                "create_checklist_item",
                _complete_create("nginx 服務", ["systemctl", "is-active", "nginx"]),
            ),
            reply_message("已整理成提案。", "ready"),
        ],
        template_commands=[GENERAL_COMMAND],
    )

    assert len(calls) == 2
    assert result.proposal is not None
    assert result.proposal[0]["detectable"] == "auto"


# ------------------------------------------------------------------ loop


async def test_unknown_tool_is_not_forced_and_keeps_staged_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, result = await _chat(
        monkeypatch,
        [
            _tool_calls_message(
                (
                    "create_checklist_item",
                    _complete_create("nginx 服務", ["systemctl", "is-active", "nginx"]),
                ),
                ("proposal_status", {"value": "ready"}),
            ),
            reply_message("已整理成提案。", "ready"),
        ],
        template_commands=[GENERAL_COMMAND],
    )

    assert len(calls) == 2
    for payload in calls:
        choice = payload.get("tool_choice")
        if isinstance(choice, dict):
            assert choice["function"]["name"] in _TOOL_NAMES
    unknown_result = json.loads(calls[1]["messages"][-1]["content"])
    assert unknown_result["reason_code"] == "unknown_tool"
    assert "最終回覆請直接在 content 輸出 JSON" in unknown_result["error"]
    assert "未命名項目" not in result.reply
    assert all(
        entry.get("name") != "proposal_status" for entry in result.tool_calls or []
    )
    assert result.proposal is not None
    assert [item["title"] for item in result.proposal] == ["nginx 服務"]


async def test_repeated_unknown_tools_stop_tool_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, result = await _chat(
        monkeypatch,
        [
            _tool_calls_message(("reply", {"text": "a"}), ("conversation_focus", {})),
            reply_message("請問要檢查哪個服務？", "needs_information"),
        ],
    )

    assert len(calls) == 2
    assert "tool_choice" not in calls[1]
    assert result.proposal is None
    assert "未命名項目" not in result.reply


async def test_repeated_incomplete_create_stops_within_three_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, result = await _chat(
        monkeypatch,
        [
            tool_call_message("create_checklist_item", _relative_path_create()),
            tool_call_message("create_checklist_item", _relative_path_create()),
            reply_message("請提供 main.py 的絕對路徑。", "needs_information"),
        ],
        content="執行 main.py",
    )

    assert len(calls) <= 3
    assert result.proposal is None
    assert result.proposal_status == "needs_information"
    blocked = json.loads(calls[2]["messages"][-2]["content"])
    assert "本輪不要再呼叫工具" in blocked["error"]
    assert "tool_choice" not in calls[2]


async def test_changed_incomplete_retry_also_stops_within_three_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, result = await _chat(
        monkeypatch,
        [
            tool_call_message("create_checklist_item", _relative_path_create()),
            tool_call_message(
                "create_checklist_item",
                _complete_create("執行 main.py", ["python3", "./main.py"]),
            ),
            reply_message("請提供 main.py 的絕對路徑。", "none"),
        ],
        content="執行 main.py",
    )

    assert len(calls) == 3
    assert "tool_choice" not in calls[2]
    assert result.proposal is None
    assert result.proposal_status == "needs_information"


async def test_mixed_complete_and_missing_requirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, result = await _chat(
        monkeypatch,
        [
            _tool_calls_message(
                (
                    "create_checklist_item",
                    _complete_create(
                        "nginx", ["systemctl", "is-active", "nginx"], "nginx"
                    ),
                ),
                (
                    "create_checklist_item",
                    _complete_create("磁碟", ["df", "-h"], "disk"),
                ),
                (
                    "create_checklist_item",
                    _complete_create("Port", ["ss", "-lnt"], "port"),
                ),
            ),
            reply_message(
                "共同檢查服務狀態。\n- 執行 main.py：請提供絕對路徑。", "ready"
            ),
        ],
        content="檢查 nginx、磁碟、Port，並執行 main.py",
        template_commands=[GENERAL_COMMAND],
    )

    assert len(calls) == 2
    assert result.proposal is not None
    assert len(result.proposal) == 3
    assert result.reply.splitlines()[0].startswith("已建立 3 項提案")
    assert "main.py" in result.reply


async def test_attachment_item_missing_information_is_needs_information(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, fake = scripted_vllm(
        [
            tool_call_message("create_checklist_item", _relative_path_create()),
            reply_message("這列需要 main.py 的絕對路徑。", "none"),
        ]
    )
    monkeypatch.setattr(chat_transport, "call_vllm_message", fake)
    patch_teacher_judge_vllm_settings(monkeypatch)
    source = {
        "source_index": 0,
        "source_label": "第 1 列",
        "title": "執行 main.py",
        "description": "程式能正常執行",
    }

    result = await attachment_itemwise.analyze_requirement_item(
        source=source,
        rubric_context=json.dumps({"items": []}),
        rubric_available=True,
    )
    row = attachment_itemwise._itemwise_result_from_chat(source, result)

    assert len(calls) == 2
    assert row["status"] == "needs_information"
    assert row.get("operation") is None


# ------------------------------------------------------------ final reply JSON


@pytest.mark.parametrize(
    ("reply", "claims"),
    [
        ("請補充這兩點，我就整理成提案。", False),
        ("補上絕對路徑後，我再幫你整理成提案。", False),
        ("我已把「Python 版本」整理成提案。", True),
        ("已將「nginx」整理成提案，請確認。", True),
        ("已整理成提案。", True),
        ("已建立提案。", True),
    ],
)
def test_creation_claim_only_counts_completed_wording(reply: str, claims: bool) -> None:
    assert proposal_replies.reply_claims_created(reply) is claims


async def test_prose_final_reply_is_restated_once_in_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = "請提供 main.log 的絕對路徑，我就能幫你建立提案。"
    calls, result = await _chat(
        monkeypatch,
        [
            tool_call_message("list_checklist", {}),
            question,
            reply_message(question, "needs_information"),
        ],
        content="我想看main.log",
    )

    assert len(calls) == 3
    repair = calls[2]
    assert repair["response_format"] == {"type": "json_object"}
    assert "tools" not in repair and "tool_choice" not in repair
    assert repair["messages"][-2] == {"role": "assistant", "content": question}
    assert result.proposal_status == "needs_information"
    assert result.reply == question


async def test_prose_question_is_kept_when_restatement_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    question = "判定方式要以哪個版本為準？請補充這點，我就整理成提案。"
    calls, result = await _chat(
        monkeypatch,
        [question, "還是純文字"],
        content="檢查 Python 版本是否正確",
    )

    assert len(calls) == 2
    assert result.proposal_status is None
    assert result.reply == question


async def test_json_final_reply_needs_no_restatement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, result = await _chat(
        monkeypatch,
        [reply_message("請提供路徑。", "needs_information")],
    )

    assert len(calls) == 1
    assert result.proposal_status == "needs_information"


async def test_refine_prose_reply_is_not_restated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, _result = await _chat(
        monkeypatch,
        [tool_call_message("list_checklist", {}), "檢查表不需要修改。"],
        is_refine=True,
        rubric_context=json.dumps({"items": [{"id": "a", "title": "A"}]}),
    )

    assert len(calls) == 2


# ------------------------------------------------------------ staged revisit


async def test_listing_after_staging_ends_tool_phase_in_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, result = await _chat(
        monkeypatch,
        [
            _tool_calls_message(
                (
                    "create_checklist_item",
                    _complete_create(
                        "nginx", ["systemctl", "is-active", "nginx"], "nginx"
                    ),
                ),
                (
                    "create_checklist_item",
                    _complete_create("磁碟", ["df", "-h"], "disk"),
                ),
            ),
            tool_call_message("list_checklist", {}),
            reply_message("共同檢查服務狀態。", "ready"),
        ],
        template_commands=[GENERAL_COMMAND],
    )

    assert len(calls) == 3
    blocked = json.loads(calls[2]["messages"][-2]["content"])
    assert blocked["reason_code"] == "already_staged"
    assert "tools" not in calls[2]
    assert calls[2]["response_format"] == {"type": "json_object"}
    assert result.proposal is not None
    assert len(result.proposal) == 2
    assert all(entry.get("tool") != "list_checklist" for entry in result.tool_calls[2:])


async def test_editing_own_staged_item_is_blocked_and_keeps_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher_view = {
        "title": "Python 版本",
        "judgement_mode": "teacher",
        "detection_method": "收集版本給老師查看。",
        "check_steps": [
            {
                "id": "python.version",
                "title": "Python 版本",
                "collector": {"type": "command", "argv": ["python3", "--version"]},
            }
        ],
    }
    calls: list[dict[str, Any]] = []

    async def fake(payload, timeout=60.0):
        calls.append(payload)
        if len(calls) == 1:
            return tool_call_message("create_checklist_item", teacher_view), {}
        if len(calls) == 2:
            # Guess an expected value on the item staged in this same turn.
            staged = json.loads(payload["messages"][-1]["content"])
            guessed_edit = {
                "id": staged["item_id"],
                "judgement_mode": "ai",
                "check_steps": [
                    {
                        **teacher_view["check_steps"][0],
                        "assertion": {
                            "type": "text_contains",
                            "expected": "Python 3.10",
                        },
                    }
                ],
            }
            return tool_call_message("edit_checklist_item", guessed_edit), {}
        return reply_message("已整理成提案。", "ready"), {}

    monkeypatch.setattr(chat_transport, "call_vllm_message", fake)
    patch_teacher_judge_vllm_settings(monkeypatch)
    result = await service.chat_with_rubric(
        messages=[SimpleNamespace(role="user", content="我想看學生的 Python 版本")],
        rubric_context=json.dumps({"items": []}),
        rubric_available=True,
    )

    assert len(calls) == 3
    blocked = json.loads(calls[2]["messages"][-2]["content"])
    assert blocked["reason_code"] == "already_staged"
    assert result.proposal is not None
    assert result.proposal[0]["judgement_mode"] == "teacher"
    assert not any(
        entry.get("tool") == "edit_checklist_item" for entry in result.tool_calls
    )


async def test_sequential_creates_of_new_items_still_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, result = await _chat(
        monkeypatch,
        [
            tool_call_message(
                "create_checklist_item",
                _complete_create("nginx", ["systemctl", "is-active", "nginx"], "nginx"),
            ),
            tool_call_message(
                "create_checklist_item", _complete_create("磁碟", ["df", "-h"], "disk")
            ),
            reply_message("共同檢查服務狀態。", "ready"),
        ],
        template_commands=[GENERAL_COMMAND],
    )

    assert len(calls) == 3
    assert result.proposal is not None
    assert len(result.proposal) == 2
