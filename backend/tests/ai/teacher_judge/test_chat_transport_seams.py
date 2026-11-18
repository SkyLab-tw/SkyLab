"""Single-owner seams of the Teacher Judge chat modules.

``chat_transport`` owns ``settings``, ``teacher_judge_client``, ``call_vllm_message`` and
``call_vllm``. Every other chat module must reach them as ``chat_transport.<name>`` so one
replacement (tests, live script request counter) is effective for the whole chat flow.
"""

from __future__ import annotations

import ast
import json
import pathlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.ai.teacher_judge import attachment_itemwise, chat_transport, service
from tests.ai.teacher_judge.helpers import (
    patch_teacher_judge_vllm_settings,
    reply_message,
    scripted_vllm,
)

PACKAGE = pathlib.Path(service.__file__).parent
SEAM_NAMES = {"settings", "teacher_judge_client", "call_vllm_message", "call_vllm"}
CHAT_MODULES = [
    name
    for name in (
        "service",
        "reply_payload",
        "proposal_tools",
        "rubric_normalization",
        "proposal_rules",
        "proposal_replies",
        "proposal_dispatch",
        "proposal_tool_calls",
        "proposal_tool_loop",
        "attachment_itemwise",
    )
    if (PACKAGE / f"{name}.py").exists()
]


@pytest.mark.parametrize("module_name", CHAT_MODULES)
def test_chat_modules_reach_seams_only_through_chat_transport(module_name: str) -> None:
    tree = ast.parse((PACKAGE / f"{module_name}.py").read_text(encoding="utf-8"))
    bound: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            bound += [a.name for a in node.names if (a.asname or a.name) in SEAM_NAMES]
        elif isinstance(node, ast.Name) and node.id in SEAM_NAMES:
            bound.append(node.id)
    assert bound == []


async def test_chat_with_rubric_uses_replaced_transport_and_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, fake = scripted_vllm([reply_message("請提供檔案路徑。", "needs_information")])
    monkeypatch.setattr(chat_transport, "call_vllm_message", fake)
    patch_teacher_judge_vllm_settings(monkeypatch)

    result = await service.chat_with_rubric(
        messages=[SimpleNamespace(role="user", content="我想看 main.log")],
        rubric_context=json.dumps({"items": []}),
        rubric_available=True,
    )

    assert len(calls) >= 1
    assert calls[0]["model"] == "test-model"
    assert result.reply


async def test_attachment_itemwise_uses_replaced_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, object]] = []

    async def fake_call_vllm(payload, timeout=120.0):
        seen.append(payload)
        return "", {}

    monkeypatch.setattr(chat_transport, "call_vllm", fake_call_vllm)
    patch_teacher_judge_vllm_settings(monkeypatch)

    try:
        await attachment_itemwise.analyze_attachments_itemwise(
            teacher_message="",
            rubric_context=json.dumps({"items": []}),
            attachment_context="第 1 列：檢查 nginx 啟動",
            rubric_available=True,
        )
    except HTTPException:
        pass

    assert len(seen) >= 1
