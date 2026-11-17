#!/usr/bin/env python3
"""AI 導師 P1 真實模型測試：追問是否停下、多需求提案數量、回覆摘要。

直接呼叫 service 層（chat_with_rubric / analyze_attachments_itemwise），使用根目錄
.env 的 VLLM_BASE_URL／VLLM_API_KEY／VLLM_MODEL_NAME；不碰 DB、不經 LiteLLM、不執行任何工具。
不加 --live 只列出 case 與預期，不送請求。每個 case 固定跑 3 輪，3/3 符合才算 PASS。

從 repository 根目錄執行（backend 虛擬環境）：

    cd backend
    uv run python ../scripts/test_teacher_judge_live.py                      # 列出 case
    uv run python ../scripts/test_teacher_judge_live.py --live --tag missing-path
    uv run python ../scripts/test_teacher_judge_live.py --live --case P1-multi
    uv run python ../scripts/test_teacher_judge_live.py --live                # 全跑
    uv run python ../scripts/test_teacher_judge_live.py --check               # 只重新判定 latest.json

只覆寫 test-results/teacher-judge-live/latest.json 與 latest.log；不輸出任何 key。
自動判定只檢查契約（數量、狀態、必要詞），語意正確性要人工讀 latest.log。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
REPORT_DIR = REPO_ROOT / "test-results" / "teacher-judge-live"
REPORT_JSON = REPORT_DIR / "latest.json"
REPORT_LOG = REPORT_DIR / "latest.log"
REPORT_VERSION = "teacher-judge-live-v1"
ROUNDS = 3
ROUND_TIMEOUT_SECONDS = 420
# 公開 AI API 有 Campus RPM 限流：輪與輪之間停頓；被 429 擋下時等一個限流視窗再重試該輪一次。
ROUND_PAUSE_SECONDS = 20
RATE_LIMIT_WAIT_SECONDS = 65

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
# Backend settings resolve their env file relative to the working directory.
os.chdir(BACKEND_ROOT)

STOP_CLAIM_PATTERN = re.compile(r"已建立|已新增|已整理成提案|已把.{0,40}整理成提案")
HEADER_PATTERN = re.compile(r"^已建立 (\d+) 項提案")

SINGLE_MACHINE = [
    {
        "display_label": "P1",
        "node_key": "web",
        "name": "web-01",
        "role": "server",
        "resource_type": "vm",
        "os": "ubuntu",
    }
]
# 兩台角色、名稱都無法分辨的機器：需求沒指定時，AI 不能從上下文推斷要查哪一台。
TWIN_MACHINES = [
    *SINGLE_MACHINE,
    {
        "display_label": "P2",
        "node_key": "web2",
        "name": "web-02",
        "role": "server",
        "resource_type": "vm",
        "os": "ubuntu",
    },
]

FIVE_REQUIREMENTS = (
    "請幫我建立這 5 項檢查，資訊都已經給齊了：\n"
    "1. 檢查 /etc/hostname 檔案內容是 web01\n"
    "2. 檢查 /etc/os-release 檔案內容包含 Ubuntu\n"
    "3. 檢查 python3 --version 的輸出包含 3.12\n"
    "4. 檢查 nginx 服務狀態是 active\n"
    "5. 檢查 8080 連接埠有在監聽"
)
FIVE_KEYWORDS = (("hostname",), ("os-release", "ubuntu"), ("python",), ("nginx",), ("8080",))

MIXED_MESSAGE = (
    "請幫我建立這 4 項檢查：\n"
    "1. 檢查 /etc/hostname 檔案內容是 web01\n"
    "2. 檢查 /etc/os-release 檔案內容包含 Ubuntu\n"
    "3. 檢查 python3 --version 的輸出包含 3.12\n"
    "4. 檢查學生的備份腳本 backup.sh 有存在並且可以執行"
)

ATTACHMENT_TEXT = (
    "作業一 評分表\n"
    "1. 檢查 /etc/hostname 檔案內容是 web01（10 分）\n"
    "2. 檢查 /etc/os-release 檔案內容包含 Ubuntu（10 分）\n"
    "3. 檢查 python3 --version 的輸出包含 3.12（10 分）\n"
    "4. 收集 /etc/nginx/nginx.conf 檔案內容，沒有固定答案，由老師自己看（10 分）\n"
    "5. 檢查學生的備份腳本 backup.sh 有存在並且可以執行（10 分）"
)


# ---------------------------------------------------------------- 判定函式
# 每個判定只讀 record（可序列化的欄位），回傳不符合的說明；空 list 代表本輪符合。


def _staged_titles(record: dict[str, Any]) -> list[str]:
    return [str(item.get("title") or "") for item in record.get("proposal") or []]


def _reply_has(record: dict[str, Any], markers: tuple[str, ...]) -> bool:
    reply = str(record.get("reply") or "")
    return any(marker in reply for marker in markers)


def check_stopped(*markers: str) -> Callable[[dict[str, Any]], list[str]]:
    """AI 停下：沒有任何 staged 提案、狀態為 needs_information、只追問不宣稱已建立。"""

    def check(record: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        if record.get("staged_count"):
            failures.append(f"不該建立提案，實際 staged={record['staged_count']}")
        if record.get("proposal_status") != "needs_information":
            failures.append(
                f"proposal_status 應為 needs_information，實際 {record.get('proposal_status')!r}"
            )
        if STOP_CLAIM_PATTERN.search(str(record.get("reply") or "")):
            failures.append("回覆宣稱已建立提案")
        if markers and not _reply_has(record, markers):
            failures.append(f"回覆沒有追問，缺少任一關鍵字 {list(markers)}")
        return failures

    return check


def check_condition(record: dict[str, Any]) -> list[str]:
    """缺判定條件：停下詢問判定方式，或建立單一「交給老師核查」提案，兩者皆符合。"""

    stopped = check_stopped("預期", "自動", "自己檢查", "老師查看")(record)
    if not stopped:
        return []
    proposal = record.get("proposal") or []
    if record.get("staged_count") == 1 and len(proposal) == 1:
        if proposal[0].get("judgement_mode") == "teacher":
            return []
        return [
            "建立的提案不是交給老師核查（judgement_mode 應為 teacher，"
            f"實際 {proposal[0].get('judgement_mode')!r}）"
        ]
    return stopped


def _header_count(record: dict[str, Any]) -> int | None:
    first_line = str(record.get("reply") or "").split("\n", 1)[0]
    matched = HEADER_PATTERN.match(first_line)
    return int(matched.group(1)) if matched else None


def check_multi(record: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if record.get("created_count") != 5:
        failures.append(f"新增提案應為 5，實際 {record.get('created_count')}")
    if _header_count(record) != 5:
        failures.append("回覆首行不是「已建立 5 項提案」")
    titles = [title.lower() for title in _staged_titles(record)]
    used: set[int] = set()
    for keywords in FIVE_KEYWORDS:
        index = next(
            (
                i
                for i, title in enumerate(titles)
                if i not in used and any(keyword in title for keyword in keywords)
            ),
            None,
        )
        if index is None:
            failures.append(f"沒有提案標題對應需求 {list(keywords)}")
        else:
            used.add(index)
    return failures


def check_mixed_path(record: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if record.get("created_count") != 3:
        failures.append(f"新增提案應為 3，實際 {record.get('created_count')}")
    if any("備份" in title or "backup" in title.lower() for title in _staged_titles(record)):
        failures.append("缺路徑的備份腳本不該建立提案")
    if _header_count(record) != 3:
        failures.append("回覆首行不是「已建立 3 項提案」")
    if not _reply_has(record, ("備份", "backup.sh")):
        failures.append("回覆沒有點名缺路徑的備份腳本")
    if not _reply_has(record, ("路徑", "位置")):
        failures.append("回覆沒有說明缺少路徑／位置")
    return failures


def check_attach(record: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    statuses = Counter(str(row.get("status")) for row in record.get("item_results") or [])
    expected = {"ready": 3, "teacher_review": 1, "needs_information": 1}
    if dict(statuses) != expected:
        failures.append(f"item_results 狀態分佈應為 {expected}，實際 {dict(statuses)}")
    if record.get("proposal_count") != 4:
        failures.append(f"提案數應為 4，實際 {record.get('proposal_count')}")
    if _header_count(record) != 4:
        failures.append("回覆首行不是「已建立 4 項提案」")
    reply = str(record.get("reply") or "")
    if "需要你注意" not in reply:
        failures.append("回覆沒有「需要你注意」清單")
    if "交給老師核查" not in reply:
        failures.append("注意清單沒有點名交給老師核查的項目")
    if "還缺少" not in reply:
        failures.append("注意清單沒有點名缺資訊的項目")
    return failures


@dataclass(frozen=True)
class Case:
    case_id: str
    tags: tuple[str, ...]
    covers: str
    kind: str  # "chat" | "attach"
    machines: list[dict[str, Any]]
    message: str
    expected: str
    check: Callable[[dict[str, Any]], list[str]]
    attachment_text: str = ""
    summary: Callable[[dict[str, Any]], str] = field(
        default=lambda record: f"staged={record.get('staged_count')}"
    )


def _created_summary(record: dict[str, Any]) -> str:
    return f"新增={record.get('created_count')}"


CASES: tuple[Case, ...] = (
    Case(
        "P1-path",
        ("missing-path",),
        "追問行為（prompt、location_rejections）",
        "chat",
        SINGLE_MACHINE,
        "檢查 nginx 設定有 listen 8080",
        "AI 停下，追問路徑",
        check_stopped("路徑"),
    ),
    Case(
        "P1-machine",
        ("missing-machine",),
        "追問行為（prompt、機器驗證）",
        "chat",
        TWIN_MACHINES,
        "檢查 nginx 服務有在執行",
        "AI 停下，追問哪一台機器",
        check_stopped("機器", "哪一台", "哪台"),
    ),
    Case(
        "P1-condition",
        ("missing-condition",),
        "追問行為（prompt 規則：缺判定條件）",
        "chat",
        SINGLE_MACHINE,
        "檢查 Python 版本是否正確",
        "AI 停下詢問預期版本，或建立 1 項交給老師核查的提案",
        check_condition,
    ),
    Case(
        "P1-mixed-path",
        ("missing-path", "summary"),
        "一般對話摘要與注意清單",
        "chat",
        SINGLE_MACHINE,
        MIXED_MESSAGE,
        "新增 3 項、備份腳本缺路徑未建立並被點名、首行已建立 3 項提案",
        check_mixed_path,
        summary=_created_summary,
    ),
    Case(
        "P1-multi",
        ("multi", "summary"),
        "一般對話摘要、prompt 多項回覆規則",
        "chat",
        SINGLE_MACHINE,
        FIVE_REQUIREMENTS,
        "新增 5 項、標題對應 5 項需求、首行已建立 5 項提案",
        check_multi,
        summary=_created_summary,
    ),
    Case(
        "P1-attach",
        ("attach", "summary"),
        "_itemwise_reply 附件逐項回覆",
        "attach",
        SINGLE_MACHINE,
        "請核查附件全部評分項目",
        "ready 3／teacher_review 1／needs_information 1、提案 4、首行已建立 4 項提案",
        check_attach,
        attachment_text=ATTACHMENT_TEXT,
        summary=lambda record: (
            "狀態=" + str(dict(Counter(r.get("status") for r in record.get("item_results") or [])))
        ),
    ),
)
CASES_BY_ID = {case.case_id: case for case in CASES}


def select_cases(case_ids: list[str], tags: list[str]) -> list[Case]:
    unknown = [case_id for case_id in case_ids if case_id not in CASES_BY_ID]
    if unknown:
        raise SystemExit(f"未知的 case：{unknown}；可用：{list(CASES_BY_ID)}")
    if not case_ids and not tags:
        return list(CASES)
    return [
        case
        for case in CASES
        if case.case_id in case_ids or any(tag in case.tags for tag in tags)
    ]


def evaluate_rounds(case: Case, records: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """回傳 (PASS | NEEDS_REVIEW, 說明)。固定 3 輪，缺輪次或任一輪不符都要人工檢查。"""
    notes: list[str] = []
    if len(records) != ROUNDS:
        notes.append(f"只有 {len(records)}/{ROUNDS} 輪記錄")
    for record in records:
        if record.get("error"):
            notes.append(f"第 {record['round']} 輪例外：{record['error']}")
            continue
        notes.extend(f"第 {record['round']} 輪：{item}" for item in case.check(record))
    return ("PASS" if not notes else "NEEDS_REVIEW"), notes


# ---------------------------------------------------------------- 實打執行


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{record.levelname} {record.name}: {record.getMessage()}")


def _tool_call_counts(tool_calls: list[dict[str, Any]] | None) -> tuple[int, int, int]:
    staged = [call for call in tool_calls or [] if call.get("status") == "staged"]
    created = {str(c.get("title") or c.get("item_id")) for c in staged if c.get("operation") != "update"}
    updated = {str(c.get("title") or c.get("item_id")) for c in staged if c.get("operation") == "update"}
    return len(created) + len(updated), len(created), len(updated)


def _public_proposal(proposal: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {
            "title": item.get("title"),
            "operation": item.get("operation"),
            "judgement_mode": item.get("judgement_mode"),
            "detectable": item.get("detectable"),
            "target_node_key": item.get("target_node_key"),
        }
        for item in proposal or []
    ]


async def run_round(case: Case, round_no: int, service: Any) -> dict[str, Any]:
    from app.ai.teacher_judge.machine_context import format_machine_context
    from app.ai.teacher_judge.schemas import TeacherJudgeRubricChatMessage

    capture = _LogCapture()
    teacher_logger = logging.getLogger("app.ai")
    previous_level = teacher_logger.level
    teacher_logger.setLevel(logging.INFO)
    teacher_logger.addHandler(capture)
    started = time.perf_counter()
    record: dict[str, Any] = {
        "case_id": case.case_id,
        "round": round_no,
        "input": case.message,
        "attachment": case.attachment_text or None,
        "machines": [entry["display_label"] for entry in case.machines],
    }
    common = {
        "rubric_context": json.dumps({"items": []}),
        "template_key": "linux",
        "template_commands": [],
        "machine_context": format_machine_context(case.machines),
        "machine_entries": case.machines,
        "rubric_available": True,
    }
    try:
        if case.kind == "attach":
            attachment = SimpleNamespace(
                original_filename="rubric.txt", extracted_text=case.attachment_text
            )
            from app.ai.teacher_judge.attachment_service import attachment_context

            result = await asyncio.wait_for(
                service.analyze_attachments_itemwise(
                    teacher_message=case.message,
                    attachment_context=attachment_context([attachment]),
                    **common,
                ),
                timeout=ROUND_TIMEOUT_SECONDS,
            )
            record.update(
                reply=result.reply,
                proposal_status=None,
                tool_calls=None,
                item_results=[
                    {
                        "source_label": row.get("source_label"),
                        "title": row.get("title"),
                        "status": row.get("status"),
                        "missing_information": row.get("missing_information"),
                        "detail": row.get("detail"),
                    }
                    for row in result.item_results
                ],
                proposal=_public_proposal(result.proposal),
                proposal_count=len(result.proposal or []),
                error_detail=getattr(result, "error", None),
            )
            record.update(staged_count=record["proposal_count"], created_count=record["proposal_count"], updated_count=0)
        else:
            result = await asyncio.wait_for(
                service.chat_with_rubric(
                    [TeacherJudgeRubricChatMessage(role="user", content=case.message)],
                    **common,
                ),
                timeout=ROUND_TIMEOUT_SECONDS,
            )
            staged, created, updated = _tool_call_counts(result.tool_calls)
            record.update(
                reply=result.reply,
                proposal_status=result.proposal_status,
                tool_calls=result.tool_calls,
                conversation_focus=result.conversation_focus,
                proposal=_public_proposal(result.proposal),
                proposal_count=len(result.proposal or []),
                staged_count=staged,
                created_count=created,
                updated_count=updated,
            )
        metrics = getattr(result, "metrics", None)
        record["metrics"] = dict(metrics) if isinstance(metrics, dict) else str(metrics)
    except Exception as exc:  # noqa: BLE001 - 實打要記錄任何失敗，不中斷其他 case
        record["error"] = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        teacher_logger.removeHandler(capture)
        teacher_logger.setLevel(previous_level)
    record["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    record["rate_limited"] = any("429" in line for line in capture.lines)
    record["server_log"] = capture.lines[-30:]
    return record


def _effective_endpoint() -> dict[str, str]:
    from app.ai.system_config import system_ai_env

    parts = urlsplit(system_ai_env.vllm_base_url)
    return {
        "base_url": f"{parts.scheme}://{parts.netloc}{parts.path}",
        "model": system_ai_env.vllm_model_name,
    }


async def run_live(
    cases: list[Case], pause_seconds: float = ROUND_PAUSE_SECONDS
) -> dict[str, Any]:
    from app.ai.teacher_judge import service
    from app.infrastructure.ai import close_ai_clients

    endpoint = _effective_endpoint()
    results: list[dict[str, Any]] = []
    first = True
    try:
        for case in cases:
            for round_no in range(1, ROUNDS + 1):
                if not first:
                    await asyncio.sleep(pause_seconds)
                first = False
                record = await run_round(case, round_no, service)
                if record.get("rate_limited"):
                    print(  # noqa: T201
                        f"{case.case_id} 第 {round_no} 輪被上游 429 限流，"
                        f"等待 {RATE_LIMIT_WAIT_SECONDS}s 後重試一次",
                        flush=True,
                    )
                    await asyncio.sleep(RATE_LIMIT_WAIT_SECONDS if pause_seconds else 0)
                    record = await run_round(case, round_no, service)
                    record["retried_after_429"] = True
                    if record.get("rate_limited") and not record.get("error"):
                        record["error"] = "上游 429 限流，重試後仍被限流"
                results.append(record)
                state = "ERROR" if record.get("error") else case.summary(record)
                print(  # noqa: T201
                    f"{case.case_id} 第 {round_no}/{ROUNDS} 輪 {state} "
                    f"{record['elapsed_seconds']}s",
                    flush=True,
                )
    finally:
        await close_ai_clients()
    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "rounds": ROUNDS,
        "cases_run": [case.case_id for case in cases],
        "results": results,
    }


# ---------------------------------------------------------------- 報告


def render_log(report: dict[str, Any]) -> str:
    """人工檢查用全文：回覆、工具呼叫統計、伺服器端記錄。"""
    lines = [
        f"# AI 導師 P1 實打記錄 {report['generated_at']}",
        f"endpoint={report['endpoint']['base_url']} model={report['endpoint']['model']}",
        "",
    ]
    for record in report["results"]:
        case = CASES_BY_ID[record["case_id"]]
        failures = [] if record.get("error") else case.check(record)
        lines += [
            "=" * 78,
            f"[{record['case_id']}] 第 {record['round']} 輪  {record['elapsed_seconds']}s  "
            f"預期：{case.expected}",
            f"輸入：{record['input']}",
        ]
        if record.get("attachment"):
            lines.append(f"附件：\n{record['attachment']}")
        if record.get("error"):
            lines.append(f"例外：{record['error']}")
        lines += [
            f"proposal_status={record.get('proposal_status')} "
            f"新增={record.get('created_count')} 修改={record.get('updated_count')} "
            f"提案數={record.get('proposal_count')}",
            "--- 回覆全文 ---",
            str(record.get("reply") or ""),
            "--- 提案 ---",
            *(f"- {json.dumps(item, ensure_ascii=False)}" for item in record.get("proposal") or []),
        ]
        if record.get("item_results"):
            lines.append("--- 逐項結果 ---")
            lines += [
                f"- {json.dumps(row, ensure_ascii=False)}" for row in record["item_results"]
            ]
        if record.get("tool_calls"):
            lines.append("--- 工具呼叫（前端狀態列資料來源） ---")
            lines += [
                f"- {json.dumps(call, ensure_ascii=False)}" for call in record["tool_calls"]
            ]
        if record.get("conversation_focus"):
            lines.append(
                f"--- conversation_focus ---\n{json.dumps(record['conversation_focus'], ensure_ascii=False)}"
            )
        if record.get("server_log"):
            lines.append("--- 伺服器端記錄 ---")
            lines += record["server_log"]
        lines.append(
            "自動判定：" + ("符合" if not failures and not record.get("error") else "不符 → " + "；".join(failures))
        )
        lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_LOG.write_text(render_log(report), encoding="utf-8")


def check_report(report: dict[str, Any]) -> int:
    """只讀已存的 report 重新判定；回傳結束碼（有任何 NEEDS_REVIEW 為 1）。"""
    ran = [case_id for case_id in report.get("cases_run", []) if case_id in CASES_BY_ID]
    by_case: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in ran}
    for record in report.get("results", []):
        if record["case_id"] in by_case:
            by_case[record["case_id"]].append(record)
    print(f"{'case':<14}{'預期':<48}{'各輪實際':<44}結果")  # noqa: T201
    exit_code = 0
    details: list[str] = []
    for case_id in ran:
        case = CASES_BY_ID[case_id]
        records = sorted(by_case[case_id], key=lambda record: record["round"])
        verdict, notes = evaluate_rounds(case, records)
        actual = " / ".join(
            "ERROR" if record.get("error") else case.summary(record) for record in records
        )
        print(f"{case_id:<14}{case.expected[:46]:<48}{actual[:42]:<44}{verdict}")  # noqa: T201
        if verdict != "PASS":
            exit_code = 1
            details += [f"[{case_id}] {note}" for note in notes]
    skipped = [case.case_id for case in CASES if case.case_id not in ran]
    if skipped:
        print(f"本次未執行：{', '.join(skipped)}")  # noqa: T201
    if details:
        print("\nNEEDS_REVIEW 說明（請讀 latest.log 人工判斷）：")  # noqa: T201
        print("\n".join(details))  # noqa: T201
    return exit_code


def list_cases(cases: list[Case]) -> None:
    endpoint = _effective_endpoint()
    print(f"endpoint={endpoint['base_url']} model={endpoint['model']}（未送出任何請求，加 --live 才會實打）")  # noqa: T201
    for case in cases:
        print(f"- {case.case_id:<14} tags={','.join(case.tags):<24} 涵蓋={case.covers}\n    預期：{case.expected}")  # noqa: T201


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="實際送出推論請求（每個 case 固定 3 輪）")
    parser.add_argument("--check", action="store_true", help="只讀 latest.json 重新判定，不送請求")
    parser.add_argument("--case", action="append", default=[], help="只跑指定 case，可重複")
    parser.add_argument("--tag", action="append", default=[], help="只跑含此標籤的 case，可重複")
    parser.add_argument(
        "--pause", type=float, default=ROUND_PAUSE_SECONDS, help="輪與輪之間的停頓秒數（避免 Campus RPM 限流）"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check:
        if not REPORT_JSON.exists():
            print(f"找不到 {REPORT_JSON}，請先執行 --live", file=sys.stderr)  # noqa: T201
            return 2
        return check_report(json.loads(REPORT_JSON.read_text(encoding="utf-8")))
    cases = select_cases(args.case, args.tag)
    if not args.live:
        list_cases(cases)
        return 0
    report = asyncio.run(run_live(cases, args.pause))
    write_report(report)
    print(f"已寫入 {REPORT_JSON} 與 {REPORT_LOG}")  # noqa: T201
    return check_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
