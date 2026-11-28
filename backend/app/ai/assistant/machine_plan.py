"""申請機器前要問清楚的四件事：用途、GPU、桌面環境、使用多久。

一句「我要一台機器」不足以規劃出對的東西，但直接丟一份猜出來的配置給使用者，
他也無從判斷對不對。所以規劃前先把這四項問齊，每題都給可以直接點的選項。

聽懂使用者的回答交給模型（它把對話整理成 ``plan_machine`` 的參數），這裡只做
模型不該決定的部分：還缺哪一項、下一題問什麼、選項有哪些，以及把答案轉成推薦
規劃（``template_recommendation``）認得的寫法。
"""

from __future__ import annotations

from typing import Any

from app.ai.assistant.schemas import PlanFacts, PlanKey, PlanQuestion, PlanState
from app.core.i18n import translate

PLAN_KEYS: tuple[PlanKey, ...] = ("purpose", "gpu", "display", "duration")

# 推薦規劃用關鍵字讀這些答案（見 recommendation_service._apply_intake_facts），
# 所以不管介面語言是什麼，存下來的一律是這組中文寫法。
GPU_ANSWERS = {
    "need": "需要 GPU",
    "no": "不需要 GPU",
    "unsure": "不確定，你幫我判斷",
}
DISPLAY_ANSWERS = {
    "desktop": "需要圖形桌面",
    "windows": "需要 Windows",
    "cli": "Linux 指令列就好",
}
_UNSURE = "不確定，你幫我判斷"
# 申請表單的時段最多只能排到 90 天後
MAX_DURATION_DAYS = 90


def _question(key: PlanKey, lang: str) -> PlanQuestion:
    options = translate(f"aiAssistant.plan.{key}.options", lang)
    return PlanQuestion(
        key=key,
        text=translate(f"aiAssistant.plan.{key}.question", lang),
        options=[option.strip() for option in options.split("|") if option.strip()],
    )


def _clean_text(value: Any, limit: int = 500) -> str | None:
    text = str(value).strip() if isinstance(value, str) else ""
    return text[:limit] or None


def _duration(value: Any) -> str | None:
    # bool 是 int 的子類別；True 不是「1 天」
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    days = round(value)
    if days < 1:
        return None
    return f"{min(days, MAX_DURATION_DAYS)}天"


def resolve_plan(arguments: dict[str, Any], *, lang: str) -> PlanState:
    """依模型整理出來的需求，決定要再問一題還是可以開始規劃。

    ``proceed`` 是使用者明講「不用問了、直接產生」：沒回答的項目交給規劃自己
    判斷，並標成推斷，讓使用者在結果裡看得出哪些不是他講的。
    """
    purpose = _clean_text(arguments.get("purpose"), 2000)
    facts = PlanFacts(
        purpose=purpose,
        gpu=GPU_ANSWERS.get(str(arguments.get("gpu") or "")),
        display=DISPLAY_ANSWERS.get(str(arguments.get("display") or "")),
        duration=_duration(arguments.get("duration_days")),
    )
    assumed = arguments.get("assumed")
    if isinstance(assumed, list):
        facts.inferred = [
            key for key in PLAN_KEYS if key in assumed and getattr(facts, key)
        ]

    if arguments.get("proceed") is True and facts.purpose:
        for key in ("gpu", "display"):
            if not getattr(facts, key):
                setattr(facts, key, _UNSURE)
                facts.inferred.append(key)

    answered = [key for key in PLAN_KEYS if getattr(facts, key)]
    missing = [key for key in PLAN_KEYS if key not in answered]
    # 沒講要用多久時，直接產生就讓規劃挑預設時段，不再追問
    if arguments.get("proceed") is True and facts.purpose:
        missing = [key for key in missing if key != "duration"]
    if not missing:
        return PlanState(
            status="ready", facts=facts, answered=len(answered), total=len(PLAN_KEYS)
        )
    return PlanState(
        status="ask",
        facts=facts,
        question=_question(missing[0], lang),
        answered=len(answered),
        total=len(PLAN_KEYS),
    )
