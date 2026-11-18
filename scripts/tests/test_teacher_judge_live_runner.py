"""Offline regressions for the teacher-judge live runner; no inference is sent."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(scope="module")
def runner():
    path = Path(__file__).resolve().parents[1] / "test_teacher_judge_live.py"
    spec = importlib.util.spec_from_file_location("teacher_judge_live_runner", path)
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


def stopped_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "case_id": "P1-path",
        "round": 1,
        "reply": "請提供 nginx 設定檔的絕對路徑。",
        "proposal_status": "needs_information",
        "staged_count": 0,
        "created_count": 0,
        "proposal": [],
        "model_requests": 2,
        "tool_budget_exhausted": False,
    }
    record.update(overrides)
    return record


def multi_record(**overrides: Any) -> dict[str, Any]:
    titles = ["檢查 hostname", "檢查 os-release", "檢查 Python 版本", "檢查 nginx", "檢查 8080"]
    record = {
        "case_id": "P1-multi",
        "round": 1,
        "reply": "已建立 5 項提案，請在下方提案清單確認後套用。\n好了",
        "proposal_status": "ready",
        "staged_count": 5,
        "created_count": 5,
        "proposal": [{"title": title} for title in titles],
    }
    record.update(overrides)
    return record


# ------------------------------------------------------------------ 選擇


def test_select_all_cases_by_default(runner) -> None:
    assert [c.case_id for c in runner.select_cases([], [])] == list(runner.CASES_BY_ID)


def test_select_by_tag_and_case_is_a_union(runner) -> None:
    by_tag = {c.case_id for c in runner.select_cases([], ["missing-path"])}
    assert by_tag == {"P1-path", "P1-mixed-path"}
    both = {c.case_id for c in runner.select_cases(["P1-attach"], ["missing-path"])}
    assert both == {"P1-path", "P1-mixed-path", "P1-attach"}


def test_select_unknown_case_exits(runner) -> None:
    with pytest.raises(SystemExit):
        runner.select_cases(["nope"], [])


def test_each_missing_gap_has_its_own_tag(runner) -> None:
    tags = {tag for case in runner.CASES for tag in case.tags}
    assert {"missing-path", "machine", "missing-condition", "summary"} <= tags


# ------------------------------------------------------------------ 判定


def test_stopped_check_passes_when_ai_only_asks(runner) -> None:
    assert runner.check_stopped("路徑")(stopped_record()) == []


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"staged_count": 1}, "不該建立提案"),
        ({"proposal_status": "ready"}, "needs_information"),
        ({"reply": "已建立提案，請提供路徑"}, "宣稱已建立"),
        ({"reply": "我已把檢查整理成提案，請提供路徑"}, "宣稱已建立"),
        ({"reply": "你想檢查哪個檔案？"}, "沒有追問"),
    ],
)
def test_stopped_check_flags_each_violation(runner, override, fragment) -> None:
    failures = runner.check_stopped("路徑")(stopped_record(**override))
    assert any(fragment in failure for failure in failures), failures


def test_stopped_check_allows_future_proposal_wording(runner) -> None:
    record = stopped_record(reply="補上絕對路徑後，我再幫你整理成提案。")
    assert runner.check_stopped("路徑")(record) == []


def test_condition_check_accepts_question_or_teacher_review(runner) -> None:
    asked = stopped_record(case_id="P1-condition", reply="要由系統自動判定，還是你自己檢查？")
    assert runner.check_condition(asked) == []

    teacher = stopped_record(
        case_id="P1-condition",
        reply="已建立 1 項提案，請在下方提案清單確認後套用。",
        proposal_status="ready",
        staged_count=1,
        created_count=1,
        proposal=[{"title": "檢查 Python 版本", "judgement_mode": "teacher"}],
    )
    assert runner.check_condition(teacher) == []

    guessed = {**teacher, "proposal": [{"title": "檢查 Python 版本", "judgement_mode": "ai"}]}
    assert any("交給老師核查" in f for f in runner.check_condition(guessed))
    assert runner.check_condition({**teacher, "staged_count": 2})


def test_condition_view_requires_single_teacher_proposal_without_question(runner) -> None:
    ok = stopped_record(
        case_id="P1-condition-view",
        proposal_status="ready",
        staged_count=1,
        proposal=[{"title": "Python 版本", "judgement_mode": "teacher"}],
    )
    assert runner.check_teacher_view(ok) == []
    ai = {**ok, "proposal": [{"title": "Python 版本", "judgement_mode": "ai"}]}
    assert any("teacher" in f for f in runner.check_teacher_view(ai))
    asked = stopped_record(case_id="P1-condition-view")
    assert len(runner.check_teacher_view(asked)) == 2


def test_condition_value_requires_ai_text_contains_expected(runner) -> None:
    ok = stopped_record(
        case_id="P1-condition-value",
        proposal_status="ready",
        staged_count=1,
        proposal=[
            {
                "title": "Python 版本",
                "judgement_mode": "ai",
                "assertions": [{"type": "text_contains", "expected": "Python 3.12"}],
            }
        ],
    )
    assert runner.check_condition_value(ok) == []
    teacher = {**ok, "proposal": [{**ok["proposal"][0], "judgement_mode": "teacher"}]}
    assert any("ai" in f for f in runner.check_condition_value(teacher))
    equals = {
        **ok,
        "proposal": [
            {**ok["proposal"][0], "assertions": [{"type": "text_equals", "expected": "3.12"}]}
        ],
    }
    assert any("text_contains" in f for f in runner.check_condition_value(equals))
    assert runner.check_condition_value(stopped_record())


def test_condition_cases_share_missing_condition_tag(runner) -> None:
    selected = {c.case_id for c in runner.select_cases([], ["missing-condition"])}
    assert selected == {"P1-condition", "P1-condition-view", "P1-condition-value"}


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"model_requests": 4}, "超過 3 次"),
        ({"model_requests": None}, "缺少模型請求次數"),
        ({"tool_budget_exhausted": True}, "輪數用盡"),
    ],
)
def test_runtime_criteria_fail_the_round(runner, override, fragment) -> None:
    case = runner.CASES_BY_ID["P1-path"]
    rounds = [stopped_record(round=i) for i in (1, 2)] + [stopped_record(round=3, **override)]
    verdict, notes = runner.evaluate_rounds(case, rounds)
    assert verdict == "NEEDS_REVIEW"
    assert any(note.startswith("第 3 輪") and fragment in note for note in notes), notes


def test_attach_rounds_skip_chat_request_limit(runner) -> None:
    case = runner.CASES_BY_ID["P1-attach"]
    assert runner.runtime_failures(case, {"model_requests": 12}) == []
    assert runner.runtime_failures(case, {"tool_budget_exhausted": True})


@pytest.mark.asyncio
async def test_run_round_counts_model_requests_and_budget_log(runner, monkeypatch) -> None:
    import logging
    from types import SimpleNamespace

    from app.ai.teacher_judge import chat_transport

    async def model_call(*_args, **_kwargs):
        return {}, {}

    monkeypatch.setattr(chat_transport, "call_vllm_message", model_call)

    async def chat_with_rubric(*_args, **_kwargs):
        for _ in range(4):
            await chat_transport.call_vllm_message({})
        logging.getLogger("app.ai.teacher_judge.service").warning(
            "Teacher Judge tool round budget (6) exhausted with staged=0"
        )
        return SimpleNamespace(
            reply="請提供路徑",
            proposal_status="needs_information",
            tool_calls=[],
            conversation_focus=None,
            proposal=None,
            metrics={},
        )

    service = SimpleNamespace(chat_with_rubric=chat_with_rubric)
    record = await runner.run_round(runner.CASES_BY_ID["P1-path"], 1, service)

    assert record.get("error") is None
    assert record["model_requests"] == 4
    assert record["tool_budget_exhausted"] is True
    assert chat_transport.call_vllm_message is model_call
    assert runner.runtime_failures(runner.CASES_BY_ID["P1-path"], record)


def test_machine_case_uses_label_only_machines(runner) -> None:
    case = runner.CASES_BY_ID["P1-machine"]
    assert [m["name"] for m in case.machines] == ["P1", "P2", "P3"]
    assert not any("web" in json.dumps(m) for m in case.machines)


def test_machine_mapping_check_requires_each_item_on_named_machine(runner) -> None:
    ok = {
        "created_count": 3,
        "proposal": [
            {"title": "P1 nginx 服務", "target_node_key": "node-1"},
            {"title": "P2 8080 監聽", "target_node_key": "node-2"},
            {"title": "P3 hostname", "target_node_key": "node-3"},
        ],
    }
    assert runner.check_machine_mapping(ok) == []
    swapped = {
        **ok,
        "proposal": [
            {**ok["proposal"][0], "target_node_key": "node-2"},
            *ok["proposal"][1:],
        ],
    }
    assert any("應分到 node-1" in f for f in runner.check_machine_mapping(swapped))
    assert runner.check_machine_mapping({**ok, "created_count": 2})


def test_multi_check_requires_count_header_and_title_mapping(runner) -> None:
    assert runner.check_multi(multi_record()) == []
    assert runner.check_multi(multi_record(created_count=4))
    assert runner.check_multi(multi_record(reply="好了"))
    missing_title = multi_record(
        proposal=[{"title": t} for t in ["檢查 hostname"] * 5]
    )
    assert any("沒有提案標題對應" in f for f in runner.check_multi(missing_title))


def test_mixed_check_requires_missing_item_named_and_not_staged(runner) -> None:
    ok = {
        "created_count": 3,
        "reply": "已建立 3 項提案，請在下方提案清單確認後套用。\n備份腳本還缺少絕對路徑",
        "proposal": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
    }
    assert runner.check_mixed_path(ok) == []
    staged_backup = {**ok, "proposal": [{"title": "檢查備份腳本"}]}
    assert any("不該建立提案" in f for f in runner.check_mixed_path(staged_backup))
    unnamed = {**ok, "reply": "已建立 3 項提案，請在下方提案清單確認後套用。\n好了"}
    assert len(runner.check_mixed_path(unnamed)) == 2


def test_attach_check_requires_distribution_header_and_attention(runner) -> None:
    ok = {
        "item_results": [
            {"status": "ready"},
            {"status": "ready"},
            {"status": "ready"},
            {"status": "teacher_review"},
            {"status": "needs_information"},
        ],
        "proposal_count": 4,
        "reply": (
            "已建立 4 項提案，請在下方提案清單確認後套用。\n需要你注意：\n"
            "- 第 4 列交給老師核查\n- 第 5 列還缺少資訊"
        ),
    }
    assert runner.check_attach(ok) == []
    wrong = {**ok, "item_results": [{"status": "ready"}] * 5}
    assert any("狀態分佈" in f for f in runner.check_attach(wrong))


# ------------------------------------------------------------------ 3/3 標準


def test_three_of_three_is_required_for_pass(runner) -> None:
    case = runner.CASES_BY_ID["P1-path"]
    good = [stopped_record(round=i) for i in (1, 2, 3)]
    assert runner.evaluate_rounds(case, good)[0] == "PASS"

    two_of_three = [*good[:2], stopped_record(round=3, staged_count=1)]
    verdict, notes = runner.evaluate_rounds(case, two_of_three)
    assert verdict == "NEEDS_REVIEW"
    assert notes and all(note.startswith("第 3 輪") for note in notes)


def test_missing_round_or_exception_needs_review(runner) -> None:
    case = runner.CASES_BY_ID["P1-path"]
    assert runner.evaluate_rounds(case, [stopped_record()])[0] == "NEEDS_REVIEW"
    errored = [stopped_record(round=1), stopped_record(round=2), {"round": 3, "error": "Timeout"}]
    verdict, notes = runner.evaluate_rounds(case, errored)
    assert verdict == "NEEDS_REVIEW"
    assert any("例外" in note for note in notes)


# ------------------------------------------------------------------ 計數與報告


def test_tool_call_counts_dedupe_retries_and_split_operations(runner) -> None:
    calls = [
        {"status": "staged", "operation": "add", "title": "A"},
        {"status": "staged", "operation": "add", "title": "A"},
        {"status": "staged", "operation": "update", "title": "B"},
        {"status": "rejected", "title": "C"},
        {"status": "read"},
    ]
    assert runner._tool_call_counts(calls) == (2, 1, 1)
    assert runner._tool_call_counts(None) == (0, 0, 0)


def test_check_reports_exit_code_and_unrun_cases(runner, capsys) -> None:
    report = {
        "cases_run": ["P1-path"],
        "results": [stopped_record(round=i) for i in (1, 2, 3)],
    }
    assert runner.check_report(report) == 0
    out = capsys.readouterr().out
    assert "P1-path" in out and "PASS" in out
    assert "本次未執行" in out and "P1-multi" in out

    report["results"][2] = stopped_record(round=3, staged_count=2)
    assert runner.check_report(report) == 1
    assert "NEEDS_REVIEW" in capsys.readouterr().out


def test_main_without_live_sends_nothing(runner, monkeypatch, capsys) -> None:
    async def boom(*_args, **_kwargs):
        raise AssertionError("不加 --live 不應送出任何請求")

    monkeypatch.setattr(runner, "run_live", boom)
    assert runner.main(["--tag", "missing-path"]) == 0
    out = capsys.readouterr().out
    assert "未送出任何請求" in out and "P1-path" in out and "P1-multi" not in out


def test_live_run_writes_latest_report_without_secrets(runner, monkeypatch, tmp_path) -> None:
    from app.ai.system_config import system_ai_env

    async def fake_round(case, round_no, _service):
        return {
            "case_id": case.case_id,
            "round": round_no,
            "input": case.message,
            "reply": "請提供絕對路徑",
            "proposal_status": "needs_information",
            "tool_calls": [],
            "proposal": [],
            "staged_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "proposal_count": 0,
            "model_requests": 2,
            "tool_budget_exhausted": False,
            "elapsed_seconds": 0.1,
            "server_log": [],
        }

    monkeypatch.setattr(runner, "run_round", fake_round)
    monkeypatch.setattr(runner, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(runner, "REPORT_JSON", tmp_path / "latest.json")
    monkeypatch.setattr(runner, "REPORT_LOG", tmp_path / "latest.log")

    assert runner.main(["--live", "--case", "P1-path", "--pause", "0"]) == 0

    report = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert report["cases_run"] == ["P1-path"]
    assert [r["round"] for r in report["results"]] == [1, 2, 3]
    text = (tmp_path / "latest.json").read_text(encoding="utf-8") + (
        tmp_path / "latest.log"
    ).read_text(encoding="utf-8")
    assert system_ai_env.vllm_api_key not in text
    assert "請提供絕對路徑" in text

    assert runner.main(["--check"]) == 0


def test_rate_limited_round_is_retried_once_then_recorded(runner, monkeypatch, tmp_path, capsys) -> None:
    calls: list[int] = []

    async def limited_round(case, round_no, _service):
        calls.append(round_no)
        return {
            "case_id": case.case_id,
            "round": round_no,
            "input": case.message,
            "reply": "",
            "elapsed_seconds": 0.0,
            "server_log": [],
            "rate_limited": True,
        }

    monkeypatch.setattr(runner, "run_round", limited_round)
    monkeypatch.setattr(runner, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(runner, "REPORT_JSON", tmp_path / "latest.json")
    monkeypatch.setattr(runner, "REPORT_LOG", tmp_path / "latest.log")

    assert runner.main(["--live", "--case", "P1-path", "--pause", "0"]) == 1
    # 每輪最多重試一次：3 輪 × 2 次嘗試。
    assert calls == [1, 1, 2, 2, 3, 3]
    out = capsys.readouterr().out
    assert "429" in out
    report = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert all(r["retried_after_429"] and "429" in r["error"] for r in report["results"])
