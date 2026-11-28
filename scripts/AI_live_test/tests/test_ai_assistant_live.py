"""Offline regressions for the AI assistant live runner; no inference is sent."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture(scope="module")
def runner():
    path = Path(__file__).resolve().parents[1] / "ai_assistant_live.py"
    spec = importlib.util.spec_from_file_location("ai_assistant_live_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    previous_cwd = Path.cwd()
    previous_path = sys.path[:]
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        os.chdir(previous_cwd)
        sys.path[:] = previous_path
        sys.modules.pop(spec.name, None)


def _page(path: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"path": path, "title": path, "state": state}


def _record(**overrides: Any) -> dict[str, Any]:
    record = {
        "case_id": "same-page-howto",
        "round": 1,
        "question": "防火牆要怎麼開 port 給外部？",
        "current_path": "/firewall",
        "history": ["帶我去防火牆"],
        "elapsed_seconds": 4.2,
        "reply": "在這頁按「新增規則」，填入要開放的埠號與來源。",
        "pages": [_page("/my-resources")],
        "flow": None,
        "degraded": False,
        "adherence": {"verdict": "allow", "reason_code": "none"},
        "model_calls": [{"profile": "complex_agent"}, {"profile": "adherence_check"}],
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    ("overrides", "expected_note"),
    [
        ({}, None),
        ({"elapsed_seconds": 10.5}, "超過 10s"),
        ({"pages": [_page("/firewall")]}, "指向目前頁"),
        ({"pages": [_page("/firewall/?tab=rules")]}, "指向目前頁"),
        # 帶開啟方式的按鈕在目前頁也會做事，線上照樣附上
        ({"pages": [_page("/firewall", {"create": True})]}, None),
        ({"degraded": True}, "降級"),
        ({"adherence": {"verdict": "block", "reason_code": "role_drift"}}, "檢查器擋下"),
        ({"reply": "  "}, "沒有回答"),
    ],
)
def test_same_page_rounds_are_judged_by_contract(runner, overrides, expected_note) -> None:
    failures = runner.round_failures(runner.CASES_BY_ID["same-page-howto"], _record(**overrides))
    if expected_note is None:
        assert failures == []
    else:
        assert any(expected_note in failure for failure in failures)


@pytest.mark.parametrize(
    ("reply", "expected_note"),
    [
        ("你已經在「防火牆」這頁了。按「新增規則」就能開放連線。", None),
        ("你目前就在「防火牆」。", None),
        ("按「新增規則」。你已經在防火牆頁面。", "沒有講明已在這一頁"),
    ],
)
def test_explicit_same_page_request_says_the_user_is_already_there(
    runner, reply, expected_note
) -> None:
    case = runner.CASES_BY_ID["same-page-explicit"]
    failures = runner.round_failures(case, _record(case_id=case.case_id, reply=reply, pages=[]))
    if expected_note is None:
        assert failures == []
    else:
        assert any(expected_note in failure for failure in failures)


def test_other_page_must_attach_the_target_button(runner) -> None:
    case = runner.CASES_BY_ID["other-page"]
    ok = _record(case_id="other-page", reply="下方附上「我的機器」的按鈕。", pages=[_page("/my-resources/")])
    assert runner.round_failures(case, ok) == []
    missing = {**ok, "pages": [_page("/firewall")]}
    assert any("/my-resources" in failure for failure in runner.round_failures(case, missing))


def test_case_passes_only_when_all_three_rounds_pass(runner) -> None:
    case = runner.CASES_BY_ID["same-page-howto"]
    rounds = [_record(round=n) for n in (1, 2, 3)]
    assert runner.evaluate_rounds(case, rounds)[0] == "PASS"
    assert runner.evaluate_rounds(case, rounds[:2])[0] == "NEEDS_REVIEW"
    rounds[2] = _record(round=3, error="TimeoutError: x")
    assert runner.evaluate_rounds(case, rounds)[0] == "NEEDS_REVIEW"


def test_cases_use_registered_screens_and_reachable_targets(runner) -> None:
    from app.ai.assistant import service as assistant_service

    runner.validate_cases(list(runner.CASES))
    build = runner.offline_turn_builder(assistant_service._build_turn)
    for case in runner.CASES:
        request = runner.build_request(case)
        assert [message.role for message in request.messages] == ["user"] * (len(case.history) + 1)
        assert request.messages[-1].content == case.question
        assert request.screen.path == case.current_path
        turn = build(request, runner.probe_user())
        assert turn.surface.id == case.surface_id
        # 實打不碰資料庫：查申請的工具不提供
        tools = {tool["function"]["name"]: tool["function"] for tool in turn.toolbox.definitions()}
        assert "get_my_requests" not in tools
        assert turn.toolbox.load_requests is None
        if case.expected == "navigate":
            page_ids = tools["show_pages"]["parameters"]["properties"]["page_ids"]["items"]["enum"]
            assert case.expected_path.strip("/") in page_ids


def test_offline_turn_builder_rejects_an_unknown_screen(runner) -> None:
    from app.ai.assistant import service as assistant_service

    case = runner.Case("x", "x", "/nowhere", "nowhere", "x", "answer")
    with pytest.raises(RuntimeError, match="not registered"):
        runner.offline_turn_builder(assistant_service._build_turn)(
            runner.build_request(case), runner.probe_user()
        )


class _FakeClient:
    """模型呼叫回固定回答與工具呼叫；遵循檢查一律放行。"""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.profiles: list[str] = []

    async def create_chat_completion(self, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        profile = kwargs["profile"].value
        self.profiles.append(profile)
        message = (
            {"content": json.dumps({"verdict": "allow", "reason_code": "none"})}
            if profile == "adherence_check"
            else self.reply
        )
        return {"choices": [{"finish_reason": "stop", "message": message}]}

    async def stream_chat_completion(
        self, payload: dict[str, Any], *, on_content: Any, **kwargs: Any
    ) -> dict[str, Any]:
        # 直接叫類別上的函式：實打時 create_chat_completion 也被記錄器包著，
        # 經過它會把同一次呼叫記成兩筆
        response = await _FakeClient.create_chat_completion(self, payload, **kwargs)
        content = response["choices"][0]["message"].get("content")
        if content:
            await on_content(content)
        return response


def test_run_round_goes_through_the_production_entry_point(runner, monkeypatch) -> None:
    from app.ai.assistant import service as assistant_service

    client = _FakeClient({
        "content": "下方附上「我的機器」的按鈕。",
        "tool_calls": [{
            "id": "t0",
            "type": "function",
            "function": {"name": "show_pages", "arguments": json.dumps({"page_ids": ["my-resources"]})},
        }],
    })
    monkeypatch.setattr(assistant_service, "assistant_client", client)
    monkeypatch.setattr(assistant_service, "system_ai_env", SimpleNamespace(vllm_model_name="offline"))
    before = (assistant_service.check_adherence, assistant_service._build_turn)

    case = runner.CASES_BY_ID["other-page"]
    record = asyncio.run(runner.run_round(case, 1))

    assert "error" not in record, record.get("error")
    assert [page["path"] for page in record["pages"]] == ["/my-resources"]
    assert record["degraded"] is False
    assert record["adherence"] == {"verdict": "allow", "reason_code": "none"}
    assert [call["profile"] for call in record["model_calls"]] == ["complex_agent", "adherence_check"]
    assert record["model_calls"][0]["tool_calls"] == [
        {"name": "show_pages", "arguments": json.dumps({"page_ids": ["my-resources"]})}
    ]
    assert runner.round_failures(case, record) == []
    # 實打結束後線上的 hook 都換回來
    assert (assistant_service.check_adherence, assistant_service._build_turn) == before
    assert client.create_chat_completion.__func__ is _FakeClient.create_chat_completion
    assert client.stream_chat_completion.__func__ is _FakeClient.stream_chat_completion
    # 回答是串流來的：記得到第一段文字出現的時間；檢查那一次沒有這一項
    answer, check = record["model_calls"]
    assert "first_text_seconds" in answer and "first_text_seconds" not in check
    assert "elapsed_seconds" in answer and "elapsed_seconds" in check


def test_dry_run_lists_cases_without_sending_requests(runner, monkeypatch, capsys) -> None:
    from app.ai.assistant import service as assistant_service

    class _Refuse:
        async def create_chat_completion(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise AssertionError("dry run must not call the model")

        stream_chat_completion = create_chat_completion

    monkeypatch.setattr(assistant_service, "assistant_client", _Refuse())
    assert runner.main([]) == 0
    output = capsys.readouterr().out
    assert all(case.case_id in output for case in runner.CASES)


def test_check_without_a_report_asks_for_a_live_run(runner, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(runner, "REPORT_JSON", tmp_path / "latest.json")
    assert runner.main(["--check"]) == 2


def test_log_lists_the_reply_buttons_and_tool_calls(runner) -> None:
    record = _record(
        case_id="other-page",
        pages=[_page("/my-resources")],
        model_calls=[
            {
                "profile": "complex_agent",
                "content": "下方附上按鈕。",
                "tool_calls": [{"name": "show_pages", "arguments": '{"page_ids": ["my-resources"]}'}],
            }
        ],
    )
    report = {
        "generated_at": "2026-11-28T00:00:00+00:00",
        "endpoint": {"base_url": "http://offline/v1", "model": "offline", "thinking": "medium"},
        "results": [record],
    }
    log = runner.render_log(report)
    assert "pages=['/my-resources']" in log
    assert "-> show_pages(" in log
    assert "自動判定：符合" in log
