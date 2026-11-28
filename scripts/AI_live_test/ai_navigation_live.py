#!/usr/bin/env python3
"""AI 導覽真實模型測試：已在目標頁時改回頁面說明，不給指向自己的連結。

直接呼叫線上入口 ``resolve_navigation``（同頁時內部再呼叫頁面說明與 adherence），
使用根目錄 .env 的 VLLM_BASE_URL／VLLM_API_KEY／VLLM_MODEL_NAME；不碰 DB、不經
LiteLLM。不加 --live 只列出 case 與預期，不送請求。每個 case 固定跑 3 輪，3/3 符合
且每輪不超過 10 秒才算 PASS。

從 repository 根目錄執行（backend 虛擬環境）：

    cd backend
    uv run python ../scripts/AI_live_test/ai_navigation_live.py                 # 列出 case
    uv run python ../scripts/AI_live_test/ai_navigation_live.py --live          # 全跑
    uv run python ../scripts/AI_live_test/ai_navigation_live.py --live --case same-page-howto
    uv run python ../scripts/AI_live_test/ai_navigation_live.py --check         # 只重新判定 latest.json

只覆寫 test-results/ai-navigation-live/latest.json 與 latest.log；不輸出任何 key。
自動判定只檢查契約（動作、連結、前綴、延遲）；說明內容是否正確要人工讀 latest.log。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
REPORT_DIR = REPO_ROOT / "test-results" / "ai-navigation-live"
REPORT_JSON = REPORT_DIR / "latest.json"
REPORT_LOG = REPORT_DIR / "latest.log"
REPORT_VERSION = "ai-navigation-live-v1"
ROUNDS = 3
MAX_ROUND_SECONDS = 10.0
HERE_MARKERS = ("目前就在", "已經在")

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
# Backend settings resolve their env file relative to the working directory.
os.chdir(BACKEND_ROOT)


@dataclass(frozen=True)
class Case:
    case_id: str
    question: str
    current_path: str
    surface_id: str
    page_title: str
    # "answer"：改回頁面說明；"navigate"：照常導覽到 expected_path
    expected: str
    expected_path: str | None = None
    history: tuple[str, ...] = ()

    def describe(self) -> str:
        if self.expected == "answer":
            return f"說明（第一句講明已在「{self.page_title}」這頁），不含 {self.current_path} 連結"
        return f"導覽到 {self.expected_path}，不呼叫頁面說明"


CASES = (
    Case(
        "same-page-howto",
        "防火牆要怎麼開 port 給外部？",
        "/firewall",
        "firewall",
        "防火牆",
        "answer",
        history=("帶我去防火牆",),
    ),
    Case("same-page-explicit", "帶我去防火牆", "/firewall", "firewall", "防火牆", "answer"),
    Case(
        "other-page",
        "帶我去我的機器",
        "/firewall",
        "firewall",
        "防火牆",
        "navigate",
        expected_path="/my-resources",
    ),
)
CASES_BY_ID = {case.case_id: case for case in CASES}


# ---------------------------------------------------------------- 判定


def _page_key(path: str | None) -> str:
    return (path or "").split("?")[0].rstrip("/") or "/"


def round_failures(case: Case, record: dict[str, Any]) -> list[str]:
    if record.get("error"):
        return [f"例外：{record['error']}"]
    failures: list[str] = []
    if record["elapsed_seconds"] > MAX_ROUND_SECONDS:
        failures.append(f"耗時 {record['elapsed_seconds']}s 超過 {MAX_ROUND_SECONDS:g}s")
    links = [_page_key(record.get("primary")), *map(_page_key, record.get("suggestions", []))]
    help_calls = [call for call in record.get("model_calls", []) if call["profile"] == "bounded_explanation"]
    if case.expected == "answer":
        if record["action"] != "answer":
            failures.append(f"action={record['action']}，預期 answer")
        first_sentence = str(record.get("answer") or "").split("。")[0]
        if not any(marker in first_sentence for marker in HERE_MARKERS):
            failures.append("答案第一句沒有講明已在這一頁")
        if str(record.get("answer") or "").count("目前就在") > 1:
            failures.append("「目前就在」重複出現")
        if record.get("primary") or _page_key(case.current_path) in links[1:]:
            failures.append(f"仍有指向目前頁 {case.current_path} 的連結")
        if not help_calls:
            failures.append("沒有呼叫頁面說明模型")
    else:
        if record["action"] not in {"navigate", "suggest"} or _page_key(record.get("primary")) != case.expected_path:
            failures.append(f"action={record['action']} primary={record.get('primary')}，預期導覽到 {case.expected_path}")
        if help_calls:
            failures.append("不是目前頁卻呼叫了頁面說明")
    return failures


def evaluate_rounds(case: Case, records: list[dict[str, Any]]) -> tuple[str, list[str]]:
    notes = [f"第 {r['round']} 輪：{'；'.join(f)}" for r in records if (f := round_failures(case, r))]
    if len(records) != ROUNDS:
        notes.append(f"只有 {len(records)}/{ROUNDS} 輪")
    return ("PASS" if not notes else "NEEDS_REVIEW"), notes


def summary(record: dict[str, Any]) -> str:
    if record.get("error"):
        return "ERROR"
    target = record.get("primary") or ("answer" if record["action"] == "answer" else record["action"])
    return f"{target} {record['elapsed_seconds']}s"


# ---------------------------------------------------------------- 實打


class _Recorder:
    """包住 client 的 create_chat_completion，記錄 profile 與模型原文（不含 key）。"""

    def __init__(self, client: Any, calls: list[dict[str, Any]]) -> None:
        self._client = client
        self._original = client.create_chat_completion
        self._calls = calls

    async def _call(self, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        profile = getattr(kwargs.get("profile"), "value", str(kwargs.get("profile")))
        entry: dict[str, Any] = {"profile": profile}
        self._calls.append(entry)
        try:
            response = await self._original(payload, **kwargs)
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            raise
        choice = (response.get("choices") or [{}])[0]
        entry["content"] = str((choice.get("message") or {}).get("content") or "")
        entry["finish_reason"] = choice.get("finish_reason")
        return response

    def __enter__(self) -> _Recorder:
        self._client.create_chat_completion = self._call
        return self

    def __exit__(self, *_exc: object) -> None:
        self._client.create_chat_completion = self._original


async def run_round(case: Case, round_no: int) -> dict[str, Any]:
    from app.ai.contextual_help import service as help_service
    from app.ai.navigation import service as nav_service
    from app.ai.navigation.schemas import NavigationMessage
    from app.models.user import UserRole

    # 學生身分：防火牆與我的機器都看得到；沒有 session，用量只記 process 內指標
    user = SimpleNamespace(id=None, role=UserRole.student, is_superuser=False)
    calls: list[dict[str, Any]] = []
    record: dict[str, Any] = {
        "case_id": case.case_id,
        "round": round_no,
        "question": case.question,
        "current_path": case.current_path,
        "history": list(case.history),
        "model_calls": calls,
    }
    started = time.perf_counter()
    try:
        with _Recorder(nav_service.navigation_client, calls), _Recorder(help_service.help_client, calls):
            response = await nav_service.resolve_navigation(
                case.question,
                user,
                None,
                history=[NavigationMessage(role="user", content=text) for text in case.history],
                current_path=case.current_path,
                surface_id=case.surface_id,
            )
        record.update(
            action=response.action,
            primary=response.primary.path if response.primary else None,
            suggestions=[item.path for item in response.suggestions],
            answer=response.answer or response.clarification_question or "",
        )
    except Exception as exc:  # noqa: BLE001 - 實打記錄例外，不中斷其他 case
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    return record


def _effective_endpoint() -> dict[str, str]:
    from app.ai.system_config import system_ai_env

    parts = urlsplit(system_ai_env.vllm_base_url)
    return {
        "base_url": f"{parts.scheme}://{parts.netloc}{parts.path}",
        "model": system_ai_env.vllm_model_name,
    }


async def run_live(cases: list[Case]) -> dict[str, Any]:
    from app.infrastructure.ai import close_ai_clients

    results: list[dict[str, Any]] = []
    try:
        for case in cases:
            for round_no in range(1, ROUNDS + 1):
                record = await run_round(case, round_no)
                results.append(record)
                print(f"{case.case_id} 第 {round_no}/{ROUNDS} 輪 {summary(record)}", flush=True)  # noqa: T201
    finally:
        await close_ai_clients()
    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": _effective_endpoint(),
        "rounds": ROUNDS,
        "max_round_seconds": MAX_ROUND_SECONDS,
        "cases_run": [case.case_id for case in cases],
        "results": results,
    }


# ---------------------------------------------------------------- 報告


def render_log(report: dict[str, Any]) -> str:
    """人工檢查用全文：答案、連結、各次模型呼叫原文。"""
    lines = [
        f"# AI 導覽實打記錄 {report['generated_at']}",
        f"endpoint={report['endpoint']['base_url']} model={report['endpoint']['model']}",
        "",
    ]
    for record in report["results"]:
        case = CASES_BY_ID[record["case_id"]]
        failures = round_failures(case, record)
        lines += [
            "=" * 78,
            f"[{record['case_id']}] 第 {record['round']} 輪  {record['elapsed_seconds']}s  預期：{case.describe()}",
            f"目前頁：{record['current_path']}  前文：{record['history']}",
            f"輸入：{record['question']}",
        ]
        if record.get("error"):
            lines.append(f"例外：{record['error']}")
        else:
            lines += [
                f"action={record['action']} primary={record['primary']} suggestions={record['suggestions']}",
                "--- 答案全文 ---",
                str(record.get("answer") or ""),
            ]
        lines.append("--- 模型呼叫 ---")
        lines += [
            f"- {call['profile']}: {call.get('error') or call.get('content', '')}"
            for call in record.get("model_calls", [])
        ]
        lines.append("自動判定：" + ("符合" if not failures else "不符 → " + "；".join(failures)))
        lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_LOG.write_text(render_log(report), encoding="utf-8")


def check_report(report: dict[str, Any]) -> int:
    """依已存的 report 判定；回傳結束碼（有任何 NEEDS_REVIEW 為 1）。"""
    exit_code = 0
    details: list[str] = []
    for case_id in [cid for cid in report.get("cases_run", []) if cid in CASES_BY_ID]:
        case = CASES_BY_ID[case_id]
        records = sorted(
            (r for r in report.get("results", []) if r["case_id"] == case_id),
            key=lambda r: r["round"],
        )
        verdict, notes = evaluate_rounds(case, records)
        actual = " / ".join(summary(record) for record in records)
        print(f"{case_id:<20}{actual:<60}{verdict}")  # noqa: T201
        if verdict != "PASS":
            exit_code = 1
            details += [f"[{case_id}] {note}" for note in notes]
    if details:
        print("\nNEEDS_REVIEW 說明（請讀 latest.log 人工判斷）：")  # noqa: T201
        print("\n".join(details))  # noqa: T201
    return exit_code


def select_cases(case_ids: list[str]) -> list[Case]:
    unknown = [case_id for case_id in case_ids if case_id not in CASES_BY_ID]
    if unknown:
        raise SystemExit(f"未知的 case：{', '.join(unknown)}")
    return [case for case in CASES if not case_ids or case.case_id in case_ids]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="實際送出推論請求（每個 case 固定 3 輪）")
    parser.add_argument("--check", action="store_true", help="只讀 latest.json 重新判定，不送請求")
    parser.add_argument("--case", action="append", default=[], help="只跑指定 case，可重複")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check:
        if not REPORT_JSON.exists():
            print(f"找不到 {REPORT_JSON}，請先執行 --live", file=sys.stderr)  # noqa: T201
            return 2
        return check_report(json.loads(REPORT_JSON.read_text(encoding="utf-8")))
    cases = select_cases(args.case)
    if not args.live:
        endpoint = _effective_endpoint()
        print(f"endpoint={endpoint['base_url']} model={endpoint['model']}（未送出任何請求，加 --live 才會實打）")  # noqa: T201
        for case in cases:
            print(f"- {case.case_id:<20} {case.current_path} 問「{case.question}」\n    預期：{case.describe()}")  # noqa: T201
        return 0
    report = asyncio.run(run_live(cases))
    write_report(report)
    print(f"已寫入 {REPORT_JSON} 與 {REPORT_LOG}")  # noqa: T201
    return check_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
