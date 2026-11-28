from __future__ import annotations

import asyncio
import json
import logging
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

import httpx

from app.infrastructure.ai.model_adapter import (
    ModelAdapterError,
    ThinkingLevel,
    adapt_chat_request,
)

_CLIENTS: weakref.WeakSet[VLLMClient] = weakref.WeakSet()
logger = logging.getLogger(__name__)


class VLLMCapability(str, Enum):
    """Transport-visible capabilities required by a System AI request."""

    THINKING_CONTROL = "thinking_control"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"
    NATIVE_TOOL_CALLS = "native_tool_calls"


class VLLMRequestProfile(str, Enum):
    """Small shared profiles for the direct-vLLM System AI boundary."""

    NAVIGATION_DECISION = "navigation_decision"
    BOUNDED_EXPLANATION = "bounded_explanation"
    CONFIGURED_TEXT = "configured_text"
    STRUCTURED_OBJECT = "structured_object"
    COMPLEX_AGENT = "complex_agent"
    ADHERENCE_CHECK = "adherence_check"


class VLLMProfileError(ValueError):
    """Raised when a request or response violates its declared profile."""


class VLLMEmptyContentError(VLLMProfileError):
    """No usable text or tool call; retain usage without retaining model content."""

    def __init__(self, profile: VLLMRequestProfile, response: dict[str, Any]) -> None:
        super().__init__(
            f"Profile {profile.value} requires non-empty assistant content"
        )
        usage = response.get("usage")
        self.usage = dict(usage) if isinstance(usage, dict) else {}


@dataclass(frozen=True)
class _ProfilePolicy:
    max_tokens: int | None
    capabilities: frozenset[VLLMCapability]


_PROFILE_POLICIES: Final[dict[VLLMRequestProfile, _ProfilePolicy]] = {
    VLLMRequestProfile.NAVIGATION_DECISION: _ProfilePolicy(
        max_tokens=384,
        capabilities=frozenset(
            {VLLMCapability.THINKING_CONTROL, VLLMCapability.JSON_SCHEMA}
        ),
    ),
    VLLMRequestProfile.BOUNDED_EXPLANATION: _ProfilePolicy(
        max_tokens=384,
        capabilities=frozenset({VLLMCapability.THINKING_CONTROL}),
    ),
    VLLMRequestProfile.CONFIGURED_TEXT: _ProfilePolicy(
        max_tokens=None,
        capabilities=frozenset({VLLMCapability.THINKING_CONTROL}),
    ),
    VLLMRequestProfile.STRUCTURED_OBJECT: _ProfilePolicy(
        max_tokens=None,
        capabilities=frozenset(
            {VLLMCapability.THINKING_CONTROL, VLLMCapability.JSON_OBJECT}
        ),
    ),
    VLLMRequestProfile.COMPLEX_AGENT: _ProfilePolicy(
        max_tokens=None,
        capabilities=frozenset(
            {VLLMCapability.THINKING_CONTROL, VLLMCapability.NATIVE_TOOL_CALLS}
        ),
    ),
    VLLMRequestProfile.ADHERENCE_CHECK: _ProfilePolicy(
        max_tokens=128,
        capabilities=frozenset(
            {VLLMCapability.THINKING_CONTROL, VLLMCapability.JSON_SCHEMA}
        ),
    ),
}


def required_capabilities(
    profile: VLLMRequestProfile,
) -> frozenset[VLLMCapability]:
    """Expose the capability contract for diagnostics and live probes."""
    try:
        return _PROFILE_POLICIES[profile].capabilities
    except KeyError as exc:  # pragma: no cover - enum exhaustiveness guard
        raise VLLMProfileError(f"Unknown vLLM request profile: {profile!r}") from exc


def _profile_policy(profile: VLLMRequestProfile) -> _ProfilePolicy:
    if not isinstance(profile, VLLMRequestProfile):
        raise VLLMProfileError("A valid VLLMRequestProfile is required")
    return _PROFILE_POLICIES[profile]


def _validate_response_format(
    payload: dict[str, Any], profile: VLLMRequestProfile, policy: _ProfilePolicy
) -> None:
    response_format = payload.get("response_format")
    if VLLMCapability.JSON_OBJECT in policy.capabilities:
        if (
            not isinstance(response_format, dict)
            or response_format.get("type") != "json_object"
        ):
            raise VLLMProfileError(
                f"Profile {profile.value} requires response_format=json_object"
            )
        return
    if VLLMCapability.JSON_SCHEMA in policy.capabilities:
        schema_envelope = (
            response_format.get("json_schema")
            if isinstance(response_format, dict)
            and response_format.get("type") == "json_schema"
            else None
        )
        if (
            not isinstance(schema_envelope, dict)
            or not isinstance(schema_envelope.get("name"), str)
            or not schema_envelope["name"].strip()
            or not isinstance(schema_envelope.get("schema"), dict)
        ):
            raise VLLMProfileError(
                f"Profile {profile.value} requires a named JSON Schema"
            )
        return
    if response_format is not None:
        raise VLLMProfileError(
            f"Profile {profile.value} does not allow response_format"
        )


def _validate_request(payload: dict[str, Any], profile: VLLMRequestProfile) -> None:
    policy = _profile_policy(profile)
    if "extra_body" in payload:
        raise VLLMProfileError(
            "extra_body is an SDK wrapper and must not be sent to direct vLLM"
        )
    if not isinstance(payload.get("model"), str) or not payload["model"].strip():
        raise VLLMProfileError(f"Profile {profile.value} requires a model")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise VLLMProfileError(f"Profile {profile.value} requires messages")
    max_tokens = payload.get("max_tokens")
    if type(max_tokens) is not int or max_tokens <= 0:
        raise VLLMProfileError(
            f"Profile {profile.value} requires a positive integer max_tokens"
        )
    if policy.max_tokens is not None and max_tokens > policy.max_tokens:
        raise VLLMProfileError(
            f"Profile {profile.value} allows at most {policy.max_tokens} output tokens"
        )
    if payload.get("stream", False) is not False:
        raise VLLMProfileError(
            "System AI VLLMClient only supports non-stream responses"
        )

    tools = payload.get("tools")
    if VLLMCapability.NATIVE_TOOL_CALLS not in policy.capabilities:
        if tools or payload.get("tool_choice") is not None:
            raise VLLMProfileError(f"Profile {profile.value} does not allow tools")
    elif tools is not None:
        if not isinstance(tools, list) or not tools:
            raise VLLMProfileError(
                f"Profile {profile.value} requires a non-empty tools list"
            )
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if (
                not isinstance(tool, dict)
                or tool.get("type") != "function"
                or not isinstance(function, dict)
                or not isinstance(function.get("name"), str)
                or not function["name"].strip()
            ):
                raise VLLMProfileError(
                    f"Profile {profile.value} received an invalid tool definition"
                )
        tool_choice = payload.get("tool_choice")
        if tool_choice is None:
            raise VLLMProfileError(
                f"Profile {profile.value} requires tool_choice when tools are present"
            )
        if isinstance(tool_choice, str):
            valid_tool_choice = tool_choice in {"auto", "none", "required"}
        else:
            selected = (
                tool_choice.get("function")
                if isinstance(tool_choice, dict)
                and tool_choice.get("type") == "function"
                else None
            )
            valid_tool_choice = (
                isinstance(selected, dict)
                and isinstance(selected.get("name"), str)
                and bool(selected["name"].strip())
            )
        if not valid_tool_choice:
            raise VLLMProfileError(
                f"Profile {profile.value} received an invalid tool_choice"
            )
        if payload.get("response_format") is not None:
            raise VLLMProfileError(
                f"Profile {profile.value} cannot combine tools with response_format"
            )
    _validate_response_format(payload, profile, policy)


def validate_request_profile(
    payload: dict[str, Any], profile: VLLMRequestProfile
) -> None:
    """Validate the same adapted contract used for transport, without model traffic."""
    _prepare_request(payload, profile)


def _prepare_request(
    payload: dict[str, Any],
    profile: VLLMRequestProfile,
    *,
    thinking: ThinkingLevel | None = None,
) -> dict[str, Any]:
    _validate_request(payload, profile)
    try:
        return adapt_chat_request(payload, thinking=thinking)
    except ModelAdapterError as exc:
        raise VLLMProfileError(str(exc)) from exc


def _validate_tool_calls(tool_calls: Any, profile: VLLMRequestProfile) -> bool:
    if not tool_calls:
        return False
    if not isinstance(tool_calls, list):
        raise VLLMProfileError(
            f"Profile {profile.value} received an invalid tool_calls envelope"
        )
    for tool_call in tool_calls:
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        if (
            not isinstance(function, dict)
            or not isinstance(function.get("name"), str)
            or not function["name"].strip()
        ):
            raise VLLMProfileError(
                f"Profile {profile.value} received an invalid native tool call"
            )
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                raise VLLMProfileError(
                    f"Profile {profile.value} received invalid tool arguments"
                ) from exc
        if not isinstance(arguments, dict):
            raise VLLMProfileError(
                f"Profile {profile.value} requires object tool arguments"
            )
    return True


def _validate_response(response: Any, profile: VLLMRequestProfile) -> dict[str, Any]:
    policy = _profile_policy(profile)
    if not isinstance(response, dict):
        raise VLLMProfileError(
            f"Profile {profile.value} received a non-object response"
        )
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise VLLMProfileError(
            f"Profile {profile.value} requires exactly one response choice"
        )
    choice = choices[0]
    if not isinstance(choice, dict):
        raise VLLMProfileError(
            f"Profile {profile.value} received an invalid response choice"
        )
    if choice.get("finish_reason") == "length":
        raise VLLMProfileError(f"Profile {profile.value} response was truncated")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise VLLMProfileError(
            f"Profile {profile.value} received an invalid assistant message"
        )
    has_tool_calls = _validate_tool_calls(message.get("tool_calls"), profile)
    if has_tool_calls and VLLMCapability.NATIVE_TOOL_CALLS not in policy.capabilities:
        raise VLLMProfileError(f"Profile {profile.value} received forbidden tool calls")
    content = message.get("content")
    if has_tool_calls:
        return response
    if content is None or (isinstance(content, str) and not content.strip()):
        logger.warning(
            "Empty vLLM response: profile=%s finish_reason=%s content_type=%s "
            "reasoning_present=%s",
            profile.value,
            choice.get("finish_reason"),
            type(content).__name__,
            bool(message.get("reasoning") or message.get("reasoning_content")),
        )
        raise VLLMEmptyContentError(profile, response)
    if not isinstance(content, str) or not content.strip():
        raise VLLMProfileError(
            f"Profile {profile.value} requires non-empty assistant content"
        )
    if policy.capabilities.intersection(
        {VLLMCapability.JSON_OBJECT, VLLMCapability.JSON_SCHEMA}
    ):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise VLLMProfileError(
                f"Profile {profile.value} received invalid JSON content"
            ) from exc
        if not isinstance(parsed, dict):
            raise VLLMProfileError(
                f"Profile {profile.value} requires a JSON object response"
            )
    return response


def _is_context_overflow(response: httpx.Response, requested: Any) -> bool:
    """vLLM's 'at least' input count is a lower bound, not a usable budget."""
    if response.status_code != 400 or type(requested) is not int:
        return False
    try:
        error = response.json().get("error", {})
        return error.get("param") == "input_tokens" and (
            "maximum context length" in str(error.get("message") or "")
        )
    except (AttributeError, TypeError, ValueError):
        return False


async def _assemble_stream(
    response: httpx.Response,
    on_content: Callable[[str], Awaitable[None]],
) -> dict[str, Any]:
    """讀完一個串流回應，組回非串流回應的形狀；文字一段一段交給 ``on_content``。

    推理內容（``reasoning_content``）不轉交也不保留。串流沒有走到 ``finish_reason``
    就斷掉算失敗，不把半截回答當成完整的。
    """
    content: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    finish_reason: Any = None
    usage: dict[str, Any] | None = None
    model: Any = None
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue  # 註解（keep-alive）、event 欄位與空行
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            raise VLLMProfileError("vLLM stream sent a chunk that is not JSON") from exc
        if not isinstance(chunk, dict):
            raise VLLMProfileError("vLLM stream sent a non-object chunk")
        if chunk.get("error"):
            raise VLLMProfileError(
                f"vLLM stream reported an error: {str(chunk['error'])[:300]}"
            )
        model = chunk.get("model") or model
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        choices = chunk.get("choices")
        if not choices:
            continue  # 只帶 usage 的收尾 chunk
        if (
            not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], dict)
            or choices[0].get("index", 0) != 0
        ):
            raise VLLMProfileError("vLLM stream requires exactly one response choice")
        choice = choices[0]
        delta = choice.get("delta")
        if isinstance(delta, dict):
            text = delta.get("content")
            if isinstance(text, str) and text:
                content.append(text)
                await on_content(text)
            for call in delta.get("tool_calls") or []:
                function = call.get("function") if isinstance(call, dict) else None
                if not isinstance(function, dict):
                    raise VLLMProfileError("vLLM stream sent an invalid tool call")
                entry = tool_calls.setdefault(
                    int(call.get("index") or 0),
                    {
                        "id": None,
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if call.get("id") and entry["id"] is None:
                    entry["id"] = call["id"]
                # 名稱與參數都可能分好幾段送來，照順序接起來
                for key in ("name", "arguments"):
                    if isinstance(function.get(key), str):
                        entry["function"][key] += function[key]
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]
    if finish_reason is None:
        raise VLLMProfileError("vLLM stream ended before the response was complete")
    message: dict[str, Any] = {"role": "assistant", "content": "".join(content) or None}
    if tool_calls:
        message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
    assembled: dict[str, Any] = {
        "model": model,
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
    }
    if usage is not None:
        assembled["usage"] = usage
    return assembled


class VLLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_timeout: float = 30.0,
        limits: httpx.Limits | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._default_timeout = default_timeout
        self._limits = limits or httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
        )
        self._http_client: httpx.AsyncClient | None = None
        _CLIENTS.add(self)

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._default_timeout),
                limits=self._limits,
            )
        return self._http_client

    async def create_chat_completion(
        self,
        payload: dict[str, Any],
        *,
        profile: VLLMRequestProfile,
        timeout: float | None = None,
        request_id: str | None = None,
        thinking: ThinkingLevel | None = None,
    ) -> dict[str, Any]:
        """``thinking`` 覆寫模型設定檔的全模型預設，只給明確需要的功能用。"""
        payload = _prepare_request(payload, profile, thinking=thinking)
        headers = self._headers(request_id)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        http_client = await self._get_http_client()
        response = await http_client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=effective_timeout,
        )
        output_limit = await self._context_output_limit(
            http_client,
            response,
            payload,
            headers=headers,
            timeout=effective_timeout,
            request_id=request_id,
        )
        if output_limit is not None:
            # A rejected generation executed no tools. Retry the exact same prompt
            # once with a smaller output reservation; never trim safety/history.
            response = await http_client.post(
                f"{self._base_url}/chat/completions",
                json={**payload, "max_tokens": output_limit},
                headers=headers,
                timeout=effective_timeout,
            )
        response.raise_for_status()
        return _validate_response(response.json(), profile)

    async def stream_chat_completion(
        self,
        payload: dict[str, Any],
        *,
        profile: VLLMRequestProfile,
        on_content: Callable[[str], Awaitable[None]],
        timeout: float | None = None,
        request_id: str | None = None,
        thinking: ThinkingLevel | None = None,
    ) -> dict[str, Any]:
        """串流版的 ``create_chat_completion``：模型寫的字一段一段交給 ``on_content``。

        回傳值與非串流版同一個形狀、通過同一套檢查，呼叫端只是多拿到逐段的文字。
        ``timeout`` 是整個回應的上限（httpx 的讀取逾時只管兩段資料之間的間隔）。
        ``payload`` 照非串流的寫法給（``stream: False``），串流參數由這裡加上。
        """
        payload = _prepare_request(payload, profile, thinking=thinking)
        headers = self._headers(request_id)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        http_client = await self._get_http_client()
        body = {**payload, "stream": True, "stream_options": {"include_usage": True}}
        assembled: dict[str, Any] | None = None
        async with asyncio.timeout(effective_timeout):
            # 第二次只在上下文放不下時發生：同一份 prompt，把輸出預留縮小再送一次
            for attempt in range(2):
                async with http_client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=effective_timeout,
                ) as response:
                    if response.is_error:
                        await response.aread()
                        output_limit = (
                            await self._context_output_limit(
                                http_client,
                                response,
                                payload,
                                headers=headers,
                                timeout=effective_timeout,
                                request_id=request_id,
                            )
                            if attempt == 0
                            else None
                        )
                        if output_limit is None:
                            response.raise_for_status()
                        body = {**body, "max_tokens": output_limit}
                        continue
                    assembled = await _assemble_stream(response, on_content)
                    break
        if assembled is None:  # pragma: no cover - 迴圈不是 break 就是 raise
            raise VLLMProfileError("vLLM stream produced no response")
        return _validate_response(assembled, profile)

    def _headers(self, request_id: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # 沒設 --api-key 的 vLLM 不需要認證；VLLM_API_KEY 留空時送 "Bearer " 會被
        # h11 判為非法標頭，請求根本發不出去
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if request_id:
            headers["X-Request-ID"] = request_id[:255]
        return headers

    async def _context_output_limit(
        self,
        http_client: httpx.AsyncClient,
        response: httpx.Response,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
        timeout: float,
        request_id: str | None,
    ) -> int | None:
        """上下文放不下時，回傳同一份 prompt 還容得下的輸出 token 數；其餘情況回 None。"""
        if not _is_context_overflow(response, payload.get("max_tokens")):
            return None
        # Count the full prompt with the serving model's chat template/tools.
        # The early-abort count in a 400 changes with max_tokens and cannot
        # establish how much room the unchanged prompt actually leaves.
        tokenize_payload = {
            key: payload[key]
            for key in (
                "model",
                "messages",
                "tools",
                "chat_template",
                "chat_template_kwargs",
                "add_generation_prompt",
                "continue_final_message",
                "add_special_tokens",
            )
            if key in payload
        }
        if "reasoning_effort" in payload:
            # TokenizeChatRequest accepts template kwargs, not a top-level
            # reasoning_effort. Render with the same effort as generation.
            tokenize_payload["chat_template_kwargs"] = {
                **dict(payload.get("chat_template_kwargs") or {}),
                "reasoning_effort": payload["reasoning_effort"],
            }
        output_limit = None
        try:
            token_response = await http_client.post(
                f"{self._base_url.removesuffix('/v1')}/tokenize",
                json=tokenize_payload,
                headers=headers,
                timeout=timeout,
            )
            token_response.raise_for_status()
            token_data = token_response.json()
            prompt_tokens = token_data.get("count")
            context_tokens = token_data.get("max_model_len")
            if type(prompt_tokens) is int and type(context_tokens) is int:
                available = context_tokens - prompt_tokens - 32
                if prompt_tokens >= 0 and 128 <= available < payload["max_tokens"]:
                    output_limit = available
        except (httpx.HTTPError, AttributeError, TypeError, ValueError) as exc:
            logger.warning(
                "vLLM context token count failed: request_id=%s error=%s",
                request_id,
                exc,
            )
        if output_limit is not None:
            logger.warning(
                "vLLM context overflow: request_id=%s max_tokens=%s adjusted_max_tokens=%s",
                request_id,
                payload["max_tokens"],
                output_limit,
            )
        return output_limit

    async def aclose(self) -> None:
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
        self._http_client = None


async def close_all_vllm_clients() -> None:
    for client in list(_CLIENTS):
        await client.aclose()
