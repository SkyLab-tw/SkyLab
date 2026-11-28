#!/usr/bin/env python3
"""AI 助手真實模型測試：已在目標頁時直接用這一頁的說明回答，不附指向自己的按鈕。

直接呼叫線上入口 ``app.ai.assistant.service.chat``（提示詞、工具迴圈、推理強度與
回答檢查都和線上相同），使用根目錄 .env 的 VLLM_BASE_URL／VLLM_API_KEY／
VLLM_MODEL_NAME；不碰 DB（查申請的工具不提供）、不經 LiteLLM。不加 --live 只檢查
case 的畫面認得出來並列出預期，不送請求。每個 case 固定跑 3 輪，3/3 符合且每輪
不超過 10 秒才算 PASS。

從 repository 根目錄執行（backend 虛擬環境）：

    cd backend
    uv run python ../scripts/AI_live_test/ai_assistant_live.py                 # 列出 case
    uv run python ../scripts/AI_live_test/ai_assistant_live.py --live          # 全跑
    uv run python ../scripts/AI_live_test/ai_assistant_live.py --live --case same-page-howto
    uv run python ../scripts/AI_live_test/ai_assistant_live.py --check         # 只重新判定 latest.json

只覆寫 test-results/ai-assistant-live/latest.json 與 latest.log；不輸出任何 key。
自動判定只檢查契約（頁面按鈕、降級或被檢查器擋下、延遲）；說明內容是否正確要人工讀 latest.log。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
REPORT_DIR = REPO_ROOT / "test-results" / "ai-assistant-live"
REPORT_JSON = REPORT_DIR / "latest.json"
REPORT_LOG = REPORT_DIR / "latest.log"
REPORT_VERSION = "ai-assistant-live-v1"
ROUNDS = 3
MAX_ROUND_SECONDS = 10.0
HERE_MARKERS = ("目前就在", "已經在", "已在")
LOCALE = "zh-TW"

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
    # "answer"：用這一頁的說明回答；"navigate"：附上 expected_path 的頁面按鈕
    expected: str
    expected_path: str | None = None
    # 先前的使用者訊息；線上會把連續的使用者訊息併成一則
    history: tuple[str, ...] = ()
    # 回答的第一句要講明使用者已經在這一頁（使用者明講要去的就是目前這頁時）
    says_here: bool = False

    def describe(self) -> str:
        if self.expected == "answer":
            here = f"第一句講明已在「{self.page_title}」，" if self.says_here else ""
            return f"{here}用這頁的說明回答，不附 {self.current_path} 的按鈕"
        return f"附上 {self.expected_path} 的頁面按鈕"


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
    Case("same-page-explicit", "帶我去防火牆", "/firewall", "firewall", "防火牆", "answer", says_here=True),
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
    if record.get("degraded"):
        failures.append("回答降級成伺服器的固定文字（模型失敗或檢查器無法使用）")
    adherence = record.get("adherence") or {}
    if adherence.get("verdict") not in (None, "allow"):
        failures.append(f"回答被檢查器擋下：{adherence['verdict']}/{adherence.get('reason_code')}")
    # 帶開啟方式的按鈕（state）在目前頁也會做事，線上照樣附上
    links = [_page_key(page["path"]) for page in record.get("pages", []) if not page.get("state")]
    if case.expected == "answer":
        if _page_key(case.current_path) in links:
            failures.append(f"仍有指向目前頁 {case.current_path} 的按鈕")
        if not str(record.get("reply") or "").strip():
            failures.append("沒有回答")
        first_sentence = str(record.get("reply") or "").split("。")[0]
        if case.says_here and not any(marker in first_sentence for marker in HERE_MARKERS):
            failures.append("答案第一句沒有講明已在這一頁")
    elif _page_key(case.expected_path) not in links:
        failures.append(f"pages={links}，預期附上 {case.expected_path} 的按鈕")
    return failures


def evaluate_rounds(case: Case, records: list[dict[str, Any]]) -> tuple[str, list[str]]:
    notes = [f"第 {r['round']} 輪：{'；'.join(f)}" for r in records if (f := round_failures(case, r))]
    if len(records) != ROUNDS:
        notes.append(f"只有 {len(records)}/{ROUNDS} 輪")
    return ("PASS" if not notes else "NEEDS_REVIEW"), notes


def summary(record: dict[str, Any]) -> str:
    if record.get("error"):
        return "ERROR"
    if record.get("degraded"):
        return f"degraded {record['elapsed_seconds']}s"
    pages = ",".join(page["path"] for page in record.get("pages", [])) or "no-pages"
    return f"{pages} {record['elapsed_seconds']}s"


# ---------------------------------------------------------------- 實打


class _Recorder:
    """包住 client 的兩種呼叫，記錄 profile 與模型原文（不含 key）。

    助手的回答走串流（``stream_chat_completion``），遵循檢查走一次回完的
    ``create_chat_completion``；兩種都要記。串流的那幾次另外記下第一段文字
    出現的時間，那是使用者開始看到字的時間點。
    """

    _METHODS = ("create_chat_completion", "stream_chat_completion")

    def __init__(self, client: Any, calls: list[dict[str, Any]]) -> None:
        self._client = client
        self._originals = {name: getattr(client, name) for name in self._METHODS}
        self._calls = calls

    def _wrap(self, name: str) -> Any:
        original = self._originals[name]

        async def call(payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            return await self._call(original, payload, kwargs)

        return call

    async def _call(
        self, original: Any, payload: dict[str, Any], kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        profile = getattr(kwargs.get("profile"), "value", str(kwargs.get("profile")))
        entry: dict[str, Any] = {"profile": profile}
        self._calls.append(entry)
        started = time.perf_counter()
        on_content = kwargs.get("on_content")
        if on_content is not None:

            async def timed(piece: str) -> None:
                entry.setdefault(
                    "first_text_seconds", round(time.perf_counter() - started, 2)
                )
                await on_content(piece)

            kwargs = {**kwargs, "on_content": timed}
        try:
            response = await original(payload, **kwargs)
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            entry["elapsed_seconds"] = round(time.perf_counter() - started, 2)
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        entry["content"] = str(message.get("content") or "")
        entry["finish_reason"] = choice.get("finish_reason")
        entry["tool_calls"] = [
            {
                "name": (call.get("function") or {}).get("name"),
                "arguments": (call.get("function") or {}).get("arguments"),
            }
            for call in message.get("tool_calls") or []
            if isinstance(call, dict)
        ]
        return response

    def __enter__(self) -> _Recorder:
        for name in self._METHODS:
            setattr(self._client, name, self._wrap(name))
        return self

    def __exit__(self, *_exc: object) -> None:
        for name, original in self._originals.items():
            setattr(self._client, name, original)


@contextlib.contextmanager
def _swapped(module: Any, name: str, value: Any) -> Iterator[None]:
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


def build_request(case: Case) -> Any:
    """與前端送出的形狀相同：對話、介面語言、使用者眼前的畫面。"""
    from app.ai.assistant.schemas import AssistantChatRequest

    return AssistantChatRequest(
        messages=[
            *({"role": "user", "content": text} for text in case.history),
            {"role": "user", "content": case.question},
        ],
        locale=LOCALE,
        screen={"path": case.current_path, "surface_id": case.surface_id},
    )


def probe_user() -> Any:
    from app.models.user import UserRole

    # 學生身分：防火牆與我的機器都看得到；沒有 session，用量只記 process 內指標
    return SimpleNamespace(id=None, role=UserRole.student, is_superuser=False)


def offline_turn_builder(build_turn: Any) -> Any:
    """線上的 ``_build_turn``，只拔掉查申請的工具：實打不碰資料庫。"""

    def build(request: Any, current_user: Any) -> Any:
        turn = build_turn(request, current_user)
        turn.toolbox.load_requests = None
        if turn.surface is None:
            raise RuntimeError(f"surface {request.screen.surface_id!r} is not registered")
        return turn

    return build


def validate_cases(cases: list[Case]) -> None:
    """不送請求：每個 case 的請求要能組出來，畫面要認得出來。"""
    from app.ai.assistant import service as assistant_service

    build = offline_turn_builder(assistant_service._build_turn)
    for case in cases:
        build(build_request(case), probe_user())


async def run_round(case: Case, round_no: int) -> dict[str, Any]:
    from app.ai.assistant import service as assistant_service

    calls: list[dict[str, Any]] = []
    verdicts: list[dict[str, str]] = []
    original_check = assistant_service.check_adherence

    async def recording_check(*args: Any, **kwargs: Any) -> Any:
        result = await original_check(*args, **kwargs)
        verdicts.append({"verdict": result.verdict.value, "reason_code": result.reason_code.value})
        return result

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
        with (
            _Recorder(assistant_service.assistant_client, calls),
            _swapped(assistant_service, "check_adherence", recording_check),
            _swapped(
                assistant_service,
                "_build_turn",
                offline_turn_builder(assistant_service._build_turn),
            ),
        ):
            response = await assistant_service.chat(build_request(case), probe_user(), None)
        record.update(
            reply=response.reply,
            pages=[
                {"path": page.path, "title": page.title, "state": page.state}
                for page in response.pages
            ],
            flow=response.flow.flow_id if response.flow else None,
            spotlight=response.spotlight.target_id if response.spotlight else None,
            degraded=response.degraded,
        )
    except Exception as exc:  # noqa: BLE001 - 實打記錄例外，不中斷其他 case
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["adherence"] = verdicts[0] if verdicts else None
    record["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    return record


def _effective_endpoint() -> dict[str, str]:
    from app.ai.system_config import system_ai_config, system_ai_env

    parts = urlsplit(system_ai_env.vllm_base_url)
    return {
        "base_url": f"{parts.scheme}://{parts.netloc}{parts.path}",
        "model": system_ai_env.vllm_model_name,
        "thinking": system_ai_config.assistant.thinking,
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
    """人工檢查用全文：回答、按鈕、各次模型呼叫原文與工具呼叫。"""
    endpoint = report["endpoint"]
    lines = [
        f"# AI 助手實打記錄 {report['generated_at']}",
        f"endpoint={endpoint['base_url']} model={endpoint['model']} thinking={endpoint.get('thinking')}",
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
            pages = [page["path"] for page in record.get("pages", [])]
            lines += [
                f"pages={pages} flow={record.get('flow')} spotlight={record.get('spotlight')} "
                f"degraded={record.get('degraded')} adherence={record.get('adherence')}",
                "--- 回答全文 ---",
                str(record.get("reply") or ""),
            ]
        lines.append("--- 模型呼叫 ---")
        for call in record.get("model_calls", []):
            tools = "".join(
                f"\n    -> {tool['name']}({tool['arguments']})" for tool in call.get("tool_calls", [])
            )
            lines.append(f"- {call['profile']}: {call.get('error') or call.get('content', '')}{tools}")
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
        validate_cases(cases)
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
