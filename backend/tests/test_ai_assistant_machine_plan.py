"""申請機器前要問清楚的四件事：還缺哪一項、下一題問什麼、答案怎麼交給推薦規劃。"""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.assistant.machine_plan import (
    DISPLAY_ANSWERS,
    GPU_ANSWERS,
    MAX_DURATION_DAYS,
    PLAN_KEYS,
    resolve_plan,
)
from app.ai.template_recommendation import recommendation_service
from app.ai.template_recommendation.schemas import (
    ChatMessage,
    ChatRequest,
    IntakeFactsContext,
)
from app.core.i18n import translate

_FULL: dict[str, Any] = {
    "purpose": "架 Flask 網站做專題",
    "gpu": "no",
    "display": "cli",
    "duration_days": 30,
}


def _plan(arguments: dict[str, Any], lang: str = "zh-TW"):
    return resolve_plan(arguments, lang=lang)


# ------------------------------------------------------------ 還缺哪一項


def test_nothing_known_asks_what_the_machine_is_for() -> None:
    plan = _plan({})
    assert (plan.status, plan.answered, plan.total) == ("ask", 0, 4)
    assert plan.question is not None
    assert plan.question.key == "purpose"
    assert plan.question.text == translate("aiAssistant.plan.purpose.question", "zh-TW")
    assert plan.question.options == [
        option.strip()
        for option in translate("aiAssistant.plan.purpose.options", "zh-TW").split("|")
    ]
    assert len(plan.question.options) >= 3
    assert plan.facts.model_dump() == {
        "purpose": None,
        "gpu": None,
        "display": None,
        "duration": None,
        "inferred": [],
    }


@pytest.mark.parametrize(
    ("known", "next_key", "answered"),
    [
        (("purpose",), "gpu", 1),
        (("purpose", "gpu"), "display", 2),
        (("purpose", "gpu", "display"), "duration", 3),
        # 題目照固定順序問，跟模型先填了哪一項無關
        (("purpose", "duration_days"), "gpu", 2),
        (("gpu", "display", "duration_days"), "purpose", 3),
    ],
)
def test_questions_are_asked_one_at_a_time_in_a_fixed_order(
    known: tuple[str, ...], next_key: str, answered: int
) -> None:
    plan = _plan({key: _FULL[key] for key in known})
    assert plan.status == "ask"
    assert plan.question is not None and plan.question.key == next_key
    assert plan.question.options, "每一題都要有可以直接點的選項"
    assert plan.answered == answered


def test_everything_known_is_ready_without_a_question() -> None:
    plan = _plan(_FULL)
    assert (plan.status, plan.answered, plan.total) == ("ready", 4, 4)
    assert plan.question is None
    assert plan.facts.model_dump() == {
        "purpose": "架 Flask 網站做專題",
        "gpu": "不需要 GPU",
        "display": "Linux 指令列就好",
        "duration": "30天",
        "inferred": [],
    }


def test_plan_keys_cover_every_fact() -> None:
    assert PLAN_KEYS == ("purpose", "gpu", "display", "duration")
    assert _plan({}).total == len(PLAN_KEYS)


# ------------------------------------------------------------ 直接產生


def test_proceed_lets_the_planner_decide_what_was_not_answered() -> None:
    plan = _plan({"purpose": "訓練影像分類模型", "proceed": True})
    assert plan.status == "ready" and plan.question is None
    assert plan.facts.gpu == "不確定，你幫我判斷"
    assert plan.facts.display == "不確定，你幫我判斷"
    # 沒講多久就讓規劃挑預設時段，不追問也不編一個天數
    assert plan.facts.duration is None
    assert plan.facts.inferred == ["gpu", "display"]
    assert plan.answered == 3


def test_proceed_keeps_what_the_user_did_say() -> None:
    plan = _plan(
        {"purpose": "跑模型", "gpu": "need", "duration_days": 14, "proceed": True}
    )
    assert plan.status == "ready"
    assert plan.facts.gpu == "需要 GPU"
    assert plan.facts.display == "不確定，你幫我判斷"
    assert plan.facts.duration == "14天"
    assert plan.facts.inferred == ["display"]


def test_proceed_without_a_purpose_still_asks_for_it() -> None:
    """連要做什麼都不知道就沒有東西可以規劃。"""
    plan = _plan({"proceed": True})
    assert plan.status == "ask"
    assert plan.question is not None and plan.question.key == "purpose"
    assert plan.facts.gpu is None and plan.facts.inferred == []


@pytest.mark.parametrize("flag", ["true", 1, "yes", None, False])
def test_only_a_real_true_counts_as_proceed(flag: Any) -> None:
    plan = _plan({"purpose": "架網站", "proceed": flag})
    assert plan.status == "ask"
    assert plan.question is not None and plan.question.key == "gpu"


# ------------------------------------------------------------ 推斷標記


def test_assumed_only_marks_facts_that_were_actually_filled() -> None:
    plan = _plan(
        {
            "purpose": "架網站",
            "gpu": "no",
            "assumed": ["gpu", "display", "duration", "bogus", 3],
        }
    )
    assert plan.facts.inferred == ["gpu"]
    assert plan.status == "ask"
    assert plan.question is not None and plan.question.key == "display"


def test_assumed_follows_the_fact_order_and_never_repeats() -> None:
    plan = _plan({**_FULL, "assumed": ["display", "gpu", "gpu"]})
    assert plan.facts.inferred == ["gpu", "display"]
    proceed = _plan({"purpose": "架網站", "assumed": ["gpu"], "proceed": True})
    assert proceed.facts.inferred == ["gpu", "display"]


@pytest.mark.parametrize("assumed", ["gpu", None, {"gpu": True}, 1])
def test_malformed_assumed_is_ignored(assumed: Any) -> None:
    assert _plan({**_FULL, "assumed": assumed}).facts.inferred == []


# ------------------------------------------------------------ 參數清理


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "1天"),
        (30, "30天"),
        (90, "90天"),
        (91, "90天"),
        (365, "90天"),
        (2.6, "3天"),
        (0, None),
        (-5, None),
        (0.2, None),
        # bool 是 int 的子類別；True 不是「1 天」
        (True, None),
        (False, None),
        ("30", None),
        (None, None),
        ([30], None),
    ],
)
def test_duration_is_a_bounded_number_of_days(value: Any, expected: str | None) -> None:
    plan = _plan({**_FULL, "duration_days": value})
    assert plan.facts.duration == expected
    assert plan.status == ("ready" if expected else "ask")
    assert MAX_DURATION_DAYS == 90


@pytest.mark.parametrize(
    "arguments",
    [
        {"gpu": "maybe"},
        {"gpu": "需要 GPU"},
        {"gpu": True},
        {"gpu": ["need"]},
        {"display": "vnc"},
        {"display": None},
    ],
)
def test_values_outside_the_enums_count_as_unanswered(
    arguments: dict[str, Any],
) -> None:
    key = next(iter(arguments))
    plan = _plan({**_FULL, **arguments})
    assert getattr(plan.facts, key) is None
    assert plan.status == "ask"
    assert plan.question is not None and plan.question.key == key


@pytest.mark.parametrize("purpose", ["", "   ", None, 42, ["架網站"]])
def test_blank_or_non_text_purpose_is_missing(purpose: Any) -> None:
    plan = _plan({**_FULL, "purpose": purpose})
    assert plan.facts.purpose is None
    assert plan.question is not None and plan.question.key == "purpose"


def test_purpose_is_trimmed_and_capped() -> None:
    plan = _plan({**_FULL, "purpose": "  " + "跑" * 3000 + "  "})
    assert plan.facts.purpose == "跑" * 2000


# ------------------------------------------------------------ 介面語言


@pytest.mark.parametrize("lang", ["zh-TW", "en", "ja"])
@pytest.mark.parametrize("key", PLAN_KEYS)
def test_every_question_exists_in_every_language(lang: str, key: str) -> None:
    arguments = {name: _FULL[name] for name in _FULL if not name.startswith(key)}
    plan = _plan(arguments, lang)
    assert plan.question is not None and plan.question.key == key
    assert plan.question.text == translate(f"aiAssistant.plan.{key}.question", lang)
    # 沒翻到的話 translate 會把 key 原樣吐回來
    assert not plan.question.text.startswith("aiAssistant.")
    chinese = _plan(arguments, "zh-TW").question
    assert chinese is not None
    assert len(plan.question.options) == len(chinese.options) >= 3
    assert all(option.strip() for option in plan.question.options)
    if lang != "zh-TW":
        assert plan.question.text != chinese.text
        assert plan.question.options != chinese.options


def test_stored_answers_do_not_depend_on_the_interface_language() -> None:
    """推薦規劃用中文關鍵字讀這些答案；介面是英文時存下來的仍是同一組寫法。"""
    assert _plan(_FULL, "en").facts == _plan(_FULL, "ja").facts == _plan(_FULL).facts


def test_unknown_language_falls_back_to_the_default() -> None:
    assert _plan({}, "fr").question == _plan({}, "zh-TW").question


# ------------------------------------------------------------ 推薦規劃讀得懂


def _intent(purpose: str, **facts: str):
    return recommendation_service.infer_intent_from_chat(
        ChatRequest(
            messages=[ChatMessage(role="user", content=purpose)],
            intake_facts=IntakeFactsContext(purpose=purpose, **facts),
        )
    )


@pytest.mark.parametrize(
    ("choice", "purpose", "requires_gpu"),
    [
        ("need", "架網站", True),
        ("no", "訓練深度學習模型", False),
        ("unsure", "AI 訓練", True),
        ("unsure", "架網站", False),
    ],
)
def test_gpu_answers_mean_the_same_thing_to_the_planner(
    choice: str, purpose: str, requires_gpu: bool
) -> None:
    intent = _intent(purpose, gpu=GPU_ANSWERS[choice])
    assert intent.requires_gpu is requires_gpu


@pytest.mark.parametrize(
    ("choice", "windows", "desktop"),
    [("windows", True, True), ("desktop", False, True), ("cli", False, False)],
)
def test_display_answers_mean_the_same_thing_to_the_planner(
    choice: str, windows: bool, desktop: bool
) -> None:
    intent = _intent("做專題", display=DISPLAY_ANSWERS[choice])
    assert (intent.needs_windows, intent.needs_desktop) == (windows, desktop)


@pytest.mark.parametrize("days", [1, 14, 30, 90])
def test_duration_round_trips_through_the_planner_parser(days: int) -> None:
    duration = _plan({**_FULL, "duration_days": days}).facts.duration
    assert recommendation_service.parse_duration_days(duration) == days


def test_ready_facts_validate_as_the_planner_input() -> None:
    """前端把 plan.facts 原樣當 intake_facts 送給 /recommend。"""
    facts = _plan({**_FULL, "assumed": ["gpu", "display"]}).facts
    context = IntakeFactsContext.model_validate(facts.model_dump())
    assert context.inferred == ["gpu", "display"]
    assert context.duration == "30天"
