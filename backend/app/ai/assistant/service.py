"""助手的主流程：組情境 → 有限輪數的工具迴圈 → 檢查回答 → 組回應。

一句話只走這一條路，不再先猜它屬於哪一種問題。模型拿到的是「使用者看得到的
頁面目錄＋眼前這一頁的完整說明與即時狀態」，需要別頁的說明自己用工具讀；回答
之外要附的東西（頁面按鈕、流程卡、配置規劃、畫面打光）也用工具表達，內容由
伺服器依權限組出來。

三種情況不會有模型寫的回答，回應會標成 ``degraded``，並寫進 ERROR／WARNING 日誌：

- 沒有設定模型，或模型呼叫失敗：回這一頁照定義排版的固定說明。
- 回答沒有通過遵循檢查，而且是檢查本身失敗：回「暫時無法回應」。

回答被遵循檢查判定離題或角色漂移時，回固定的範圍說明；這是正常結果，不算降級。

模型寫回答時是逐段送出來的（``chat_stream``）：使用者先看到正在寫的字，檢查要等
整段寫完才能做。所以先顯示的字只是暫時的，最後那一則完整回應才算數——沒通過檢查
時它是固定文字，前端用它換掉先前顯示的內容。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from sqlmodel import Session

from app.ai.adherence_check import check_adherence
from app.ai.assistant.catalog import (
    NavigationRoute,
    get_routes_for_user,
    resolve_user_role,
)
from app.ai.assistant.flows import get_flows_for_user
from app.ai.assistant.guard import GUARD_PROMPT, guard_document
from app.ai.assistant.knowledge import (
    catalog_lines,
    catalog_surfaces,
    live_state,
    match_surface,
    related_targets,
    render_help,
    render_page_guide,
)
from app.ai.assistant.prompt import build_system_prompt
from app.ai.assistant.schemas import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantMessage,
)
from app.ai.assistant.specs import SurfaceSpec
from app.ai.assistant.surfaces import get_surfaces_for_user
from app.ai.assistant.tools import MAX_PAGE_BUTTONS, Toolbox
from app.ai.monitoring import (
    CALL_AI_ASSISTANT,
    CALL_AI_ASSISTANT_ADHERENCE,
    AIWorkflowObservation,
    new_ai_request_id,
    record_ai_template_call,
    usage_metrics,
)
from app.ai.role_contracts import AdherenceReason, OutputMode, RoleContract
from app.ai.system_config import system_ai_config, system_ai_env
from app.ai.utils import strip_think_tags
from app.core.db import engine
from app.core.i18n import translate
from app.infrastructure.ai import VLLMRequestProfile
from app.infrastructure.ai.assistant import client as assistant_client
from app.models import User
from app.models.user import UserRole
from app.services.vm import vm_request_service

logger = logging.getLogger(__name__)

ROUTE = "/ai/assistant/chat"

ASSISTANT_CONTRACT = RoleContract(
    role_id="assistant",
    output_mode=OutputMode.MODEL_FREE_TEXT,
    contract_version="assistant-v1",
    fallback_key="aiAssistant.outOfScope",
)

# 送進模型的對話前文上限。前端保存整段對話，這裡只留最近的，最新一則一定保留。
_HISTORY_CHARS = 16_000
# 一輪最多執行幾個工具呼叫；再多就是模型在繞圈
_MAX_TOOL_CALLS_PER_ROUND = 6
# 回答是給窄面板看的，超過這個長度直接截斷
_MAX_REPLY_CHARS = 4000
# 同一則訊息裡寫了這麼多字就當成完整的回答，不是「帶你過去，按鈕在下面」這種
# 引導語（中文二三十字、英文七八十字）。實測完整的說明都在三百字上下。用在
# ToolOutcome.unless_answered：這時少一顆按鈕不必把整段收回重寫。
_STANDALONE_ANSWER_CHARS = 120
_MY_REQUESTS_LIMIT = 5


class _ModelFailure(Exception):
    """模型沒有給出可用的回答；``reason`` 進觀測指標，不顯示給使用者。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# 回答產生過程中送給前端的事件：
#   {"type": "delta", "text": …}   模型正在寫的字，接在已顯示的內容後面
#   {"type": "reset"}              先前顯示的字作廢（那一輪不是最後的回答）
#   {"type": "status", "tool": …}  剛用完這個工具，接下來要再想一輪
Emit = Callable[[dict[str, Any]], Awaitable[None]]

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


async def _discard(_event: dict[str, Any]) -> None:
    """沒有人在看過程（非串流呼叫）時用的 emit。"""


def _visible_text(raw: str) -> str:
    """模型這一輪到目前為止的輸出裡，可以給使用者看的部分。

    規則與 ``strip_think_tags`` 相同（只留結束標記之後的字），差別是輸出還沒寫完：
    開頭是推理標記、或短到還看不出是不是標記時先不顯示。
    """
    end = raw.find(_THINK_CLOSE)
    if end != -1:
        return raw[end + len(_THINK_CLOSE) :].lstrip()
    head = raw.lstrip()
    if head.startswith(_THINK_OPEN) or _THINK_OPEN.startswith(head):
        return ""
    return head


class _ShownText:
    """一輪模型輸出裡，已經送到使用者眼前的字。"""

    def __init__(self, emit: Emit) -> None:
        self._emit = emit
        self._raw = ""
        self._sent = ""

    async def feed(self, piece: str) -> None:
        self._raw += piece
        visible = _visible_text(self._raw)
        if not visible.startswith(self._sent):
            # 送出去之後才發現那是推理（沒有開頭標記、後面才冒出結束標記）
            await self._emit({"type": "reset"})
            self._sent = ""
        fresh = visible[len(self._sent) :]
        if fresh:
            await self._emit({"type": "delta", "text": fresh})
        self._sent = visible

    async def retract(self) -> None:
        """這一輪寫的字不是最後的回答（模型還要再講一次），請前端收回。"""
        if self._sent:
            await self._emit({"type": "reset"})
            self._sent = ""


@dataclass
class _Turn:
    """一次請求裡由後端可信資料組成的情境。"""

    lang: str
    role: UserRole
    routes: tuple[NavigationRoute, ...]
    surface: SurfaceSpec | None
    toolbox: Toolbox
    system_prompt: str
    history: list[dict[str, str]]
    question: str


# ------------------------------------------------------------ 情境


def _history(messages: list[AssistantMessage]) -> list[dict[str, str]]:
    """整理成模型吃得下的前文。

    只留最近的（最新一則一定保留），並把連續同一個角色的訊息併成一則、去掉開頭
    的助手訊息：有些模型的聊天範本要求 user／assistant 嚴格交替，前端又可能連續
    出現兩則助手訊息（本地附加的提示）或兩則使用者訊息（上一輪失敗）。
    """
    kept: list[AssistantMessage] = []
    chars = 0
    for message in reversed(messages):
        text = message.content.strip()
        if not text:
            continue
        if kept and chars + len(text) > _HISTORY_CHARS:
            break
        kept.append(message)
        chars += len(text)
    kept.reverse()

    merged: list[dict[str, str]] = []
    for message in kept:
        text = message.content.strip()
        if merged and merged[-1]["role"] == message.role:
            merged[-1]["content"] += "\n\n" + text
        else:
            merged.append({"role": message.role, "content": text})
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


def _load_my_requests(user_id: uuid.UUID) -> list[dict[str, Any]]:
    """使用者自己最近的申請。自己開連線、查完就還，不佔著請求的連線等模型。"""
    with Session(engine) as db:
        result = vm_request_service.list_by_user(
            session=db, user_id=user_id, limit=_MY_REQUESTS_LIMIT
        )
    requests = []
    for item in result.data:
        entry: dict[str, Any] = {
            "name": item.hostname,
            "type": item.resource_type,
            "review_status": str(getattr(item.status, "value", item.status)),
            "provisioning_status": str(
                getattr(item.provisioning_status, "value", item.provisioning_status)
            ),
            "machine_ready": item.vmid is not None,
            "submitted_at": item.created_at.date().isoformat(),
        }
        if item.review_comment:
            entry["review_comment"] = item.review_comment[:300]
        if item.provisioning_error:
            entry["provisioning_error"] = item.provisioning_error[:300]
        requests.append(entry)
    return requests


def _build_turn(request: AssistantChatRequest, current_user: User) -> _Turn:
    role = resolve_user_role(current_user)
    routes = get_routes_for_user(current_user)
    surfaces = get_surfaces_for_user(current_user)
    flows = get_flows_for_user(current_user)
    screen = request.screen
    surface = match_surface(surfaces, screen.path, screen.surface_id)
    user_id = current_user.id

    async def load_requests() -> list[dict[str, Any]]:
        return await asyncio.to_thread(_load_my_requests, user_id)

    catalog = catalog_surfaces(surfaces)
    toolbox = Toolbox(
        role=role,
        lang=request.locale,
        surfaces=catalog,
        routes=routes,
        flows=flows,
        # 打光只對使用者眼前這一頁有意義；認不出畫面時不提供
        guide_steps=screen.guide_steps if surface is not None else (),
        load_requests=load_requests,
        current_path=screen.path,
    )
    system_prompt = build_system_prompt(
        locale=request.locale,
        role=role.value,
        catalog=catalog_lines(catalog),
        flows=[
            {"id": flow.flow_id, "title": flow.title, "summary": flow.summary}
            for flow in flows
        ],
        screen_help=(
            render_help(surface, role=role, routes=routes) if surface else None
        ),
        screen_state=(
            live_state(surface, screen.state, screen.active_target) if surface else None
        ),
        current_path=screen.path,
        guide_steps=[
            {"id": step.id, "title": step.title} for step in toolbox.guide_steps
        ],
    )
    history = _history(request.messages)
    return _Turn(
        lang=request.locale,
        role=role,
        routes=routes,
        surface=surface,
        toolbox=toolbox,
        system_prompt=system_prompt,
        history=history,
        question=request.messages[-1].content.strip(),
    )


# ------------------------------------------------------------ 模型


def _tool_calls(
    message: dict[str, Any], round_index: int
) -> list[tuple[str, str, dict[str, Any]]]:
    """(id, 名稱, 參數)。形狀已由 VLLMClient 驗過，這裡只補 id 並解開參數。"""
    calls: list[tuple[str, str, dict[str, Any]]] = []
    for index, call in enumerate(message.get("tool_calls") or []):
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            arguments = json.loads(arguments or "{}")
        call_id = str(call.get("id") or f"call_{round_index}_{index}")
        calls.append((call_id, str(function.get("name")), dict(arguments or {})))
    return calls[:_MAX_TOOL_CALLS_PER_ROUND]


def build_model_payload(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    model_name: str,
    last_round: bool = False,
) -> dict[str, Any]:
    """助手每一輪送給模型的請求；live probe runner 也用這一支組請求。

    最後一輪不再給工具可用，一定要講話，免得繞到輪數用完卻沒有回答。
    """
    config = system_ai_config.assistant
    return {
        "model": model_name,
        "messages": messages,
        "tools": tools,
        "tool_choice": "none" if last_round else "auto",
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "stream": False,
    }


async def _run_model(
    turn: _Turn,
    *,
    model_name: str,
    observation: AIWorkflowObservation,
    session: Session | None,
    user_id: uuid.UUID,
    emit: Emit,
) -> str:
    """跑工具迴圈，回傳最後要給使用者的文字。附加物收集在 ``turn.toolbox``。

    模型寫的字邊寫邊經 ``emit`` 送出去；某一輪寫了字卻還要再講一次時會請前端收回。
    """
    config = system_ai_config.assistant
    tools = turn.toolbox.definitions()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": turn.system_prompt},
        *turn.history,
    ]

    for round_index in range(config.max_rounds):
        payload = build_model_payload(
            messages,
            tools,
            model_name=model_name,
            last_round=round_index == config.max_rounds - 1,
        )
        call_id = new_ai_request_id()
        started = perf_counter()
        started_at = datetime.now(timezone.utc)
        data: dict[str, Any] = {}
        shown = _ShownText(emit)
        try:
            with observation.phase("model", request_id=call_id):
                data = await assistant_client.stream_chat_completion(
                    payload,
                    profile=VLLMRequestProfile.COMPLEX_AGENT,
                    on_content=shown.feed,
                    timeout=float(config.timeout),
                    request_id=call_id,
                    thinking=config.thinking,
                )
        except Exception as exc:
            record_ai_template_call(
                session=session,
                user_id=user_id,
                call_type=CALL_AI_ASSISTANT,
                model_name=model_name,
                metrics={
                    **usage_metrics(
                        {"usage": getattr(exc, "usage", None) or {}},
                        perf_counter() - started,
                        request_id=call_id,
                        started_at=started_at,
                    ),
                    "stream": True,
                },
                status="error",
                error_message=str(exc),
            )
            reason = (
                "model_timeout" if "Timeout" in type(exc).__name__ else "model_error"
            )
            raise _ModelFailure(reason) from exc
        record_ai_template_call(
            session=session,
            user_id=user_id,
            call_type=CALL_AI_ASSISTANT,
            model_name=model_name,
            metrics={
                **usage_metrics(
                    data,
                    perf_counter() - started,
                    request_id=call_id,
                    started_at=started_at,
                ),
                "stream": True,
            },
        )

        message = data["choices"][0]["message"]
        content = strip_think_tags(str(message.get("content") or "")).strip()
        calls = _tool_calls(message, round_index)
        if not calls:
            return content

        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": call_id_,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                    for call_id_, name, arguments in calls
                ],
            }
        )
        needs_reply = False
        answered = len(content) >= _STANDALONE_ANSWER_CHARS
        for call_id_, name, arguments in calls:
            with observation.phase("tool"):
                outcome = await turn.toolbox.run(name, arguments)
            reply_needed = outcome.needs_reply and not (
                outcome.unless_answered and answered
            )
            needs_reply = needs_reply or reply_needed
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id_,
                    "content": json.dumps(outcome.result, ensure_ascii=False),
                }
            )
            if reply_needed:
                # 模型要帶著這個結果再想一輪：讓等待的人知道現在在做什麼
                await emit({"type": "status", "tool": name})
        # 同一則訊息已經寫好回答、工具只是附上按鈕或流程：不必再繞一輪
        if content and not needs_reply:
            return content
        await shown.retract()

    raise _ModelFailure("round_limit")


async def _check_reply(
    turn: _Turn,
    reply: str,
    *,
    model_name: str,
    request_id: str,
    observation: AIWorkflowObservation,
    session: Session | None,
    user_id: uuid.UUID,
) -> AdherenceReason | None:
    """回答可以顯示就回 None，否則回被擋下的原因。"""
    guard_request_id = f"{request_id}:adherence"
    with observation.phase("adherence", request_id=guard_request_id):
        result = await check_adherence(
            assistant_client,
            ASSISTANT_CONTRACT,
            turn.question,
            reply,
            {},
            guard_request_id,
            model_name=model_name,
            phase="respond",
            system_prompt=GUARD_PROMPT,
            document=guard_document(turn.question, reply, turn.toolbox.called),
        )
    record_ai_template_call(
        session=session,
        user_id=user_id,
        call_type=CALL_AI_ASSISTANT_ADHERENCE,
        model_name=model_name,
        metrics={
            "request_id": guard_request_id,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
            "elapsed_seconds": result.elapsed_seconds,
            "usage_reported": result.usage_reported,
            "response_model": result.response_model,
        },
        status="success" if result.allowed else "error",
        error_message=None if result.allowed else result.reason_code.value,
    )
    return None if result.allowed else result.reason_code


# ------------------------------------------------------------ 回應


def _degraded(turn: _Turn, request_id: str) -> AssistantChatResponse:
    """沒有模型可用時的回答：這一頁照定義排版的說明，講得硬但不會錯。"""
    if turn.surface is None:
        return AssistantChatResponse(
            request_id=request_id,
            reply=translate("aiAssistant.unavailable", turn.lang),
            degraded=True,
        )
    guide = render_page_guide(turn.surface, role=turn.role)
    return AssistantChatResponse(
        request_id=request_id,
        reply=f"{translate('aiAssistant.degradedPageGuide', turn.lang)}\n\n{guide}",
        pages=related_targets(turn.surface, turn.routes)[:MAX_PAGE_BUTTONS],
        degraded=True,
    )


async def chat_stream(
    request: AssistantChatRequest,
    current_user: User,
    session: Session | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """邊產生邊送出的一輪對話：過程事件之後，最後一定是一則 ``final``。

    ``final`` 的 ``response`` 就是 ``chat()`` 的回傳值，也是唯一算數的內容；在它
    之前的 ``delta`` 只是讓使用者不必乾等。呼叫端中途不再迭代（使用者關掉面板、
    連線斷了）時，背後的模型呼叫會一併取消。
    """
    queue: asyncio.Queue[dict[str, Any] | Exception] = asyncio.Queue()

    async def run() -> None:
        try:
            response = await chat(request, current_user, session, emit=queue.put)
        except Exception as exc:
            await queue.put(exc)  # 在迭代的那一端重新拋出
        else:
            await queue.put({"type": "final", "response": response})

    task = asyncio.create_task(run())
    try:
        while True:
            event = await queue.get()
            if isinstance(event, Exception):
                raise event
            yield event
            if event["type"] == "final":
                return
    finally:
        task.cancel()


async def chat(
    request: AssistantChatRequest,
    current_user: User,
    session: Session | None = None,
    *,
    emit: Emit = _discard,
) -> AssistantChatResponse:
    """一輪對話的完整回應。``emit`` 收產生過程中的事件，不需要過程的呼叫端不用給。"""
    model_name = system_ai_env.vllm_model_name.strip()
    with AIWorkflowObservation(route=ROUTE, model=model_name) as observation:
        request_id = new_ai_request_id()
        turn = _build_turn(request, current_user)
        if not model_name:
            logger.warning(
                "VLLM_MODEL_NAME is empty; assistant answers from static help"
            )
            observation.outcome, observation.terminal_reason = (
                "fallback",
                "not_configured",
            )
            return _degraded(turn, request_id)

        try:
            reply = await _run_model(
                turn,
                model_name=model_name,
                observation=observation,
                session=session,
                user_id=current_user.id,
                emit=emit,
            )
        except _ModelFailure as exc:
            logger.error(
                "Assistant model call failed, answering from static help: "
                "request_id=%s reason=%s cause=%r",
                request_id,
                exc.reason,
                exc.__cause__,
            )
            observation.outcome, observation.terminal_reason = "fallback", exc.reason
            return _degraded(turn, request_id)

        reply = reply[:_MAX_REPLY_CHARS].strip()
        toolbox = turn.toolbox
        if not reply:
            # 最後一輪不能呼叫工具，照理一定有字；真的沒有就是模型壞了。
            logger.error("Assistant model returned no text: request_id=%s", request_id)
            observation.outcome, observation.terminal_reason = "fallback", "empty_reply"
            return _degraded(turn, request_id)

        blocked = await _check_reply(
            turn,
            reply,
            model_name=model_name,
            request_id=request_id,
            observation=observation,
            session=session,
            user_id=current_user.id,
        )
        if blocked is AdherenceReason.CHECK_FAILED:
            logger.error(
                "Assistant adherence check unavailable, withholding the answer: "
                "request_id=%s",
                request_id,
            )
            observation.outcome, observation.terminal_reason = (
                "error",
                "adherence_failed",
            )
            return AssistantChatResponse(
                request_id=request_id,
                reply=translate("aiAssistant.unavailable", turn.lang),
                degraded=True,
            )
        if blocked is not None:
            logger.warning(
                "Assistant answer blocked by adherence check: request_id=%s reason=%s",
                request_id,
                blocked.value,
            )
            observation.outcome, observation.terminal_reason = (
                "blocked",
                "adherence_block",
            )
            return AssistantChatResponse(
                request_id=request_id,
                reply=translate(ASSISTANT_CONTRACT.fallback_key, turn.lang),
            )

        plan = toolbox.plan
        return AssistantChatResponse(
            request_id=request_id,
            reply=reply,
            pages=toolbox.pages,
            flow=toolbox.flow,
            plan=plan,
            spotlight=toolbox.spotlight,
            choices=(
                list(plan.question.options)
                if plan is not None and plan.status == "ask" and plan.question
                else []
            ),
        )
