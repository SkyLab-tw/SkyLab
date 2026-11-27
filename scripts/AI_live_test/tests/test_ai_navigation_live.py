"""Offline regressions for the AI navigation live runner; no inference is sent."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(scope="module")
def runner():
    path = Path(__file__).resolve().parents[1] / "ai_navigation_live.py"
    spec = importlib.util.spec_from_file_location("ai_navigation_live_runner", path)
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


def _record(**overrides: Any) -> dict[str, Any]:
    record = {
        "case_id": "same-page-howto",
        "round": 1,
        "elapsed_seconds": 4.2,
        "action": "answer",
        "primary": None,
        "suggestions": ["/my-resources"],
        "answer": "你目前就在「防火牆」。按「新增連線」。",
        "model_calls": [{"profile": "navigation_decision"}, {"profile": "bounded_explanation"}],
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    ("overrides", "expected_note"),
    [
        ({}, None),
        ({"elapsed_seconds": 10.5}, "超過 10s"),
        ({"suggestions": ["/firewall"]}, "指向目前頁"),
        ({"answer": "按「新增連線」。"}, "沒有講明已在這一頁"),
        ({"answer": "你目前就在「防火牆」。你目前就在防火牆頁面。"}, "重複出現"),
        ({"answer": "你已經在防火牆頁面，按「新增連線」。"}, None),
        ({"action": "navigate", "primary": "/firewall", "answer": ""}, "預期 answer"),
    ],
)
def test_same_page_rounds_are_judged_by_contract(runner, overrides, expected_note) -> None:
    failures = runner.round_failures(runner.CASES_BY_ID["same-page-howto"], _record(**overrides))
    if expected_note is None:
        assert failures == []
    else:
        assert any(expected_note in failure for failure in failures)


def test_other_page_must_navigate_without_page_help(runner) -> None:
    case = runner.CASES_BY_ID["other-page"]
    ok = _record(case_id="other-page", action="navigate", primary="/my-resources", suggestions=[], answer="",
                 model_calls=[{"profile": "navigation_decision"}])
    assert runner.round_failures(case, ok) == []
    helped = {**ok, "model_calls": [*ok["model_calls"], {"profile": "bounded_explanation"}]}
    assert any("頁面說明" in failure for failure in runner.round_failures(case, helped))


def test_case_passes_only_when_all_three_rounds_pass(runner) -> None:
    case = runner.CASES_BY_ID["same-page-howto"]
    rounds = [_record(round=n) for n in (1, 2, 3)]
    assert runner.evaluate_rounds(case, rounds)[0] == "PASS"
    assert runner.evaluate_rounds(case, rounds[:2])[0] == "NEEDS_REVIEW"
    rounds[2] = _record(round=3, error="TimeoutError: x")
    assert runner.evaluate_rounds(case, rounds)[0] == "NEEDS_REVIEW"
