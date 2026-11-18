"""Server-owned proposal count, summary and attention list in teacher replies."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.teacher_judge import chat_transport, service
from app.ai.teacher_judge.schemas import TeacherJudgeRubricItem
from tests.ai.teacher_judge.helpers import (
    patch_teacher_judge_vllm_settings,
    reply_message,
    scripted_vllm,
    tool_call_message,
)


def _item(title: str, **overrides: Any) -> TeacherJudgeRubricItem:
    values: dict[str, Any] = {"id": f"id-{title}", "title": title, "detectable": "auto"}
    values.update(overrides)
    return TeacherJudgeRubricItem(**values)


def _staged(title: str, operation: str = "add", **overrides: Any) -> dict[str, Any]:
    item = _item(title, **overrides)
    return {"item": item, "operation": operation, "raw": item.model_dump(mode="json")}


def _rejected(title: str) -> tuple[TeacherJudgeRubricItem, dict[str, Any], str]:
    item = _item(title, detectable="partial", missing_information=["檔案位置"])
    return item, item.model_dump(mode="json"), "missing"


def _summarize(reply: str, **kwargs: Any) -> str:
    kwargs.setdefault("staged_ops", [])
    kwargs.setdefault("rejected_ops", [])
    kwargs.setdefault("conversation_focus", None)
    kwargs.setdefault("template_commands", None)
    return service._proposal_summary_reply(reply, **kwargs)


# ------------------------------------------------------- _proposal_summary_reply


def test_single_clean_proposal_keeps_model_reply() -> None:
    assert _summarize("好了", staged_ops=[_staged("A")]) == "好了"


def test_no_staged_proposal_never_claims_a_count() -> None:
    reply = _summarize("請補路徑", rejected_ops=[_rejected("A"), _rejected("B")])
    assert reply == "請補路徑"


def test_many_proposals_get_count_header_first() -> None:
    reply = _summarize("共同檢查 Python", staged_ops=[_staged(t) for t in "ABCDE"])
    assert reply.splitlines()[0] == "已建立 5 項提案，請在下方提案清單確認後套用。"
    assert reply.endswith("共同檢查 Python")
    assert "摘要" not in reply
    assert "需要你注意" not in reply


def test_created_and_updated_are_counted_separately() -> None:
    reply = _summarize(
        "ok",
        staged_ops=[_staged("A"), _staged("B"), _staged("C", "update")],
    )
    assert reply.splitlines()[0] == (
        "已建立 2 項提案、已送出 1 項修改提案，請在下方提案清單確認後套用。"
    )


def test_retried_title_is_counted_once() -> None:
    reply = _summarize("ok", staged_ops=[_staged("A"), _staged("A"), _staged("B")])
    assert reply.splitlines()[0].startswith("已建立 2 項提案")


def test_unresolved_rejection_is_named_in_attention_list() -> None:
    reply = _summarize(
        "已整理",
        staged_ops=[_staged("A"), _staged("B"), _staged("C")],
        rejected_ops=[_rejected("備份腳本")],
    )
    lines = reply.splitlines()
    assert lines[0].startswith("已建立 3 項提案")
    assert lines[1] == "摘要：共 4 項需求，3 項已建立提案，1 項需要補資訊或調整。"
    assert "需要你注意：" in lines
    assert any(line.startswith("- ") and "備份腳本" in line for line in lines)


def test_rejection_already_explained_by_reply_is_not_repeated() -> None:
    reply = _summarize(
        "「備份腳本」請補上絕對路徑。",
        staged_ops=[_staged("A"), _staged("B")],
        rejected_ops=[_rejected("備份腳本")],
    )
    assert "摘要：共 3 項需求" in reply
    assert "需要你注意" not in reply


def test_rejection_retried_into_staged_is_not_attention() -> None:
    reply = _summarize(
        "ok",
        staged_ops=[_staged("A"), _staged("B")],
        rejected_ops=[_rejected("A")],
    )
    assert "摘要" not in reply
    assert "需要你注意" not in reply


def test_teacher_review_item_is_called_out_even_when_alone() -> None:
    reply = _summarize(
        "整理好了", staged_ops=[_staged("Nginx 設定", judgement_mode="teacher")]
    )
    assert reply.splitlines()[0].startswith("已建立 1 項提案")
    assert "（其中 1 項交給老師核查）" in reply
    assert "- 「Nginx 設定」交給老師核查：" in reply


def test_teacher_review_item_named_in_reply_is_not_repeated() -> None:
    reply = _summarize(
        "「Nginx 設定」會顯示結果供你查看。",
        staged_ops=[_staged("Nginx 設定", judgement_mode="teacher")],
    )
    assert reply == "「Nginx 設定」會顯示結果供你查看。"


def test_unresolved_tool_error_counts_as_follow_up_without_duplicate_bullet() -> None:
    reply = _summarize(
        "「備份腳本」的修改未通過驗證。",
        staged_ops=[_staged("A"), _staged("B")],
        error_titles=["備份腳本", "A"],
    )
    assert reply.splitlines()[0].startswith("已建立 2 項提案")
    assert "摘要：共 3 項需求，2 項已建立提案，1 項需要補資訊或調整。" in reply
    assert "需要你注意" not in reply


def test_model_stated_gap_without_tool_call_is_named() -> None:
    focus = {
        "requirements": [
            {"focus_key": "備份腳本", "status": "ready", "missing_information": []},
            {
                "focus_key": "MySQL 服務",
                "status": "needs_information",
                "missing_information": ["要檢查哪一台機器"],
            },
        ]
    }
    reply = _summarize(
        "其餘已整理",
        staged_ops=[_staged("A"), _staged("備份腳本")],
        conversation_focus=focus,
    )
    assert "摘要：共 3 項需求，2 項已建立提案，1 項需要補資訊或調整。" in reply
    assert "- 「MySQL 服務」還缺少：要檢查哪一台機器。" in reply
    assert "「備份腳本」還缺少" not in reply


# ------------------------------------------------------------- _itemwise_reply


def _row(index: int, status: str, **extra: Any) -> dict[str, Any]:
    return {
        "source_label": f"第 {index} 列",
        "title": f"項目{index}",
        "status": status,
        "missing_information": [],
        "detail": "",
        **extra,
    }


def test_itemwise_reply_counts_and_names_attention_rows() -> None:
    rows = [
        _row(1, "ready"),
        _row(2, "ready"),
        _row(3, "ready"),
        _row(4, "teacher_review"),
        _row(5, "needs_information", missing_information=["檔案絕對路徑"]),
    ]
    lines = service._itemwise_reply(rows, 5).splitlines()
    assert lines[0] == "已建立 4 項提案，請在下方提案清單確認後套用。"
    assert lines[1] == (
        "摘要：共 5 項需求，4 項已建立提案（其中 1 項交給老師核查），1 項需要補資訊或調整。"
    )
    assert lines[2] == "需要你注意："
    assert lines[3].startswith("- 第 4 列「項目4」交給老師核查")
    assert lines[4] == "- 第 5 列「項目5」還缺少資訊：檔案絕對路徑"
    assert len(lines) == 5


def test_itemwise_reply_all_ready_has_no_attention_list() -> None:
    lines = service._itemwise_reply([_row(1, "ready"), _row(2, "ready")], 2).splitlines()
    assert lines == [
        "已建立 2 項提案，請在下方提案清單確認後套用。",
        "摘要：共 2 項需求，2 項已建立提案。",
    ]


def test_itemwise_reply_without_any_proposal_does_not_claim_created() -> None:
    reply = service._itemwise_reply([_row(1, "analysis_error")], 1)
    assert "已建立" not in reply
    assert "摘要：共 1 項需求，沒有建立提案，1 項需要補資訊或調整。" in reply
    assert "- 第 1 列「項目1」這項分析沒有成功" in reply


# ------------------------------------------------- chat_with_rubric integration


_READ_ONLY_ARGV = (["uname", "-a"], ["hostname"], ["whoami"], ["uptime"], ["nproc"])


def _create_args(index: int, title: str) -> dict[str, Any]:
    return {
        "title": title,
        "detectable": "auto",
        "judgement_mode": "ai",
        "detection_method": f"執行查詢 {index}。",
        "check_steps": [
            {
                "id": f"step.{index}",
                "title": "唯讀取證",
                "collector": {"type": "command", "argv": _READ_ONLY_ARGV[index]},
                "assertion": {"type": "returncode_equals", "expected": 0},
            }
        ],
    }


async def _chat(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> Any:
    patch_teacher_judge_vllm_settings(monkeypatch)
    _calls, fake = scripted_vllm(responses)
    monkeypatch.setattr(chat_transport, "call_vllm_message", fake)
    return await service.chat_with_rubric(
        messages=[SimpleNamespace(role="user", content="多項檢查")],
        rubric_context=json.dumps({"items": []}),
        template_commands=[],
        rubric_available=True,
    )


@pytest.mark.asyncio
async def test_chat_five_proposals_lead_with_server_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    titles = ["檢查一", "檢查二", "檢查三", "檢查四", "檢查五"]
    calls = [
        tool_call_message("create_checklist_item", _create_args(i, title))["tool_calls"][0]
        for i, title in enumerate(titles)
    ]
    for index, call in enumerate(calls):
        call["id"] = f"call_{index}"
    result = await _chat(
        monkeypatch,
        [
            {"role": "assistant", "content": None, "tool_calls": calls},
            reply_message("我把這五項整理好了，請確認。", "ready"),
        ],
    )

    assert len(result.proposal) == 5
    assert result.reply.splitlines()[0] == (
        "已建立 5 項提案，請在下方提案清單確認後套用。"
    )
    assert "我把這五項整理好了" in result.reply
    staged = [c for c in result.tool_calls if c.get("status") == "staged"]
    assert len(staged) == 5


@pytest.mark.asyncio
async def test_chat_mixed_names_missing_item_and_keeps_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _chat(
        monkeypatch,
        [
            tool_call_message("create_checklist_item", _create_args(1, "檢查一")),
            tool_call_message("create_checklist_item", _create_args(2, "檢查二")),
            tool_call_message(
                "create_checklist_item",
                {
                    "title": "備份腳本檢查",
                    "detectable": "partial",
                    "judgement_mode": "ai",
                    "missing_information": ["檔案位置"],
                },
            ),
            reply_message("兩項已整理好。", "ready"),
        ],
    )

    assert len(result.proposal) == 2
    lines = result.reply.splitlines()
    assert lines[0].startswith("已建立 2 項提案")
    assert lines[1] == "摘要：共 3 項需求，2 項已建立提案，1 項需要補資訊或調整。"
    assert "需要你注意：" in lines
    assert any("備份腳本檢查" in line for line in lines[lines.index("需要你注意：") :])


@pytest.mark.asyncio
async def test_chat_hallucinated_tool_is_not_counted_as_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _chat(
        monkeypatch,
        [
            tool_call_message("create_checklist_item", _create_args(1, "檢查一")),
            tool_call_message("propose_checklist_changes", {"changes": "[]"}),
            reply_message("已整理好。", "ready"),
            # The server then forces one repair round for the failed tool.
            reply_message("已整理好。", "ready"),
        ],
    )

    assert len(result.proposal) == 1
    assert "共 2 項需求" not in result.reply
    assert "需要補資訊或調整" not in result.reply
