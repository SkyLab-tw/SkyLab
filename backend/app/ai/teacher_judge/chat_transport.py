"""vLLM transport for Teacher Judge chat: request, retry, usage accounting (package-internal).

This module owns the ``settings`` and ``teacher_judge_client`` bindings and the
``call_vllm_message`` / ``call_vllm`` seams. Other Teacher Judge modules must
reach them as ``chat_transport.<name>`` so a single replacement stays effective."""

from __future__ import annotations

import asyncio
import json
import logging
from time import perf_counter
from typing import Any, cast

import httpx
from fastapi import HTTPException

from app.ai.teacher_judge._types import VLLMMetrics
from app.ai.teacher_judge.config import settings
from app.ai.utils import strip_think_tags
from app.core.i18n import t
from app.infrastructure.ai import VLLMRequestProfile
from app.infrastructure.ai.teacher_judge import client as teacher_judge_client
from app.infrastructure.ai.vllm_client import VLLMEmptyContentError

__all__ = [
    "MAX_CHAT_COMPLETION_TOKENS",
    "assistant_message",
    "call_vllm",
    "call_vllm_message",
    "charge_missing_completion_usage",
    "merge_vllm_metrics",
    "settings",
    "teacher_judge_client",
    "tool_arguments",
]

logger = logging.getLogger(__name__)


MAX_CHAT_COMPLETION_TOKENS = 16_384


def merge_vllm_metrics(first: VLLMMetrics, second: VLLMMetrics) -> VLLMMetrics:
    """Keep usage accounting accurate when one corrective generation is required."""
    prompt_tokens = int(first.get("prompt_tokens") or 0) + int(
        second.get("prompt_tokens") or 0
    )
    completion_tokens = int(first.get("completion_tokens") or 0) + int(
        second.get("completion_tokens") or 0
    )
    elapsed_seconds = float(first.get("elapsed_seconds") or 0) + float(
        second.get("elapsed_seconds") or 0
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(first.get("total_tokens") or 0)
        + int(second.get("total_tokens") or 0),
        "elapsed_seconds": elapsed_seconds,
        "tokens_per_second": completion_tokens / elapsed_seconds
        if elapsed_seconds > 0
        else 0.0,
        "usage_reported": bool(first.get("usage_reported", True))
        and bool(second.get("usage_reported", False)),
        "response_model": second.get("response_model") or first.get("response_model"),
    }


def charge_missing_completion_usage(
    metrics: VLLMMetrics, reserved_tokens: int
) -> VLLMMetrics:
    if metrics.get("usage_reported", False):
        return metrics
    prompt_tokens = int(metrics.get("prompt_tokens") or 0)
    charged = max(int(reserved_tokens), 0)
    return {
        **metrics,
        "completion_tokens": charged,
        "total_tokens": prompt_tokens + charged,
        "tokens_per_second": (
            charged / float(metrics.get("elapsed_seconds") or 0)
            if float(metrics.get("elapsed_seconds") or 0) > 0
            else 0.0
        ),
    }


def _request_profile(payload: dict[str, Any]) -> VLLMRequestProfile:
    """Map Teacher Judge's current request shape to the shared vLLM contract."""
    if payload.get("tools"):
        return VLLMRequestProfile.COMPLEX_AGENT
    response_format = payload.get("response_format")
    if (
        isinstance(response_format, dict)
        and response_format.get("type") == "json_object"
    ):
        return VLLMRequestProfile.STRUCTURED_OBJECT
    return VLLMRequestProfile.CONFIGURED_TEXT


async def _request_vllm_with_retry(
    payload: dict[str, Any],
    *,
    profile: VLLMRequestProfile,
    timeout: float,
) -> dict[str, Any]:
    """Retry one rejected/unconnected generation within the original deadline."""
    started = perf_counter()
    for attempt in range(2):
        remaining = timeout - (perf_counter() - started)
        if remaining <= 0:
            raise httpx.ReadTimeout("Teacher Judge model request deadline exceeded")
        try:
            return await asyncio.wait_for(
                teacher_judge_client.create_chat_completion(
                    payload,
                    profile=profile,
                    timeout=remaining,
                ),
                timeout=remaining,
            )
        except asyncio.TimeoutError as exc:
            raise httpx.ReadTimeout(
                "Teacher Judge model request deadline exceeded"
            ) from exc
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            if attempt:
                raise
        except httpx.HTTPStatusError as exc:
            # Authentication, invalid input, truncation and ambiguous read
            # timeouts require a correction, rather than the same request.
            if attempt or exc.response.status_code not in {429, 503}:
                raise
        logger.warning(
            "Teacher Judge model request temporarily unavailable; retrying once"
        )
        await asyncio.sleep(min(0.25, max(timeout - (perf_counter() - started), 0)))
    raise AssertionError("unreachable")  # pragma: no cover - 迴圈內必 return 或 raise


async def call_vllm_message(
    payload: dict[str, Any], timeout: float = 120.0
) -> tuple[dict[str, Any], VLLMMetrics]:
    """Call vLLM chat/completions and preserve structured assistant data."""
    url = f"{settings.VLLM_BASE_URL}/chat/completions"
    started = perf_counter()

    logger.debug(f"Calling vLLM API: {url}")

    try:
        failed_usage: dict[str, Any] = {}
        request = payload
        for attempt in range(2):
            remaining = timeout - (perf_counter() - started)
            if remaining <= 0:
                raise httpx.ReadTimeout("Teacher Judge model request deadline exceeded")
            try:
                data = await _request_vllm_with_retry(
                    request,
                    profile=_request_profile(request),
                    timeout=remaining,
                )
                break
            except VLLMEmptyContentError as exc:
                # No tool call was returned or executed. Correct only this generation;
                # never replay earlier tools or silently treat an empty reply as success.
                used = exc.usage.get("completion_tokens")
                if attempt or type(used) is not int or used < 0:
                    raise
                remaining_tokens = int(payload.get("max_tokens") or 0) - used
                if remaining_tokens <= 0:
                    raise
                failed_usage = exc.usage
                request = {
                    **payload,
                    "max_tokens": remaining_tokens,
                    "messages": [
                        *payload["messages"],
                        {
                            "role": "system",
                            "content": (
                                "上一輪沒有提供可用的回覆。請依原本格式輸出非空的最終說明，"
                                "或呼叫本輪允許的工具；不要只輸出思考內容。"
                                "若無須修改，說明判斷依據；若資訊不足，具體列出需要教師補充的資訊。"
                                "只能根據已取得的資料與工具結果回答，不得把未完成檢查說成通過。"
                            ),
                        },
                    ],
                }
                logger.warning(
                    "Teacher Judge empty response; requesting one corrected reply"
                )

        elapsed = max(perf_counter() - started, 0.0)
        raw_usage = data.get("usage")
        usage_reported = isinstance(raw_usage, dict)
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0) + int(
            failed_usage.get("prompt_tokens") or 0
        )
        completion_tokens = int(usage.get("completion_tokens") or 0) + int(
            failed_usage.get("completion_tokens") or 0
        )
        total_tokens = sum(
            int(
                part.get("total_tokens")
                or (
                    int(part.get("prompt_tokens") or 0)
                    + int(part.get("completion_tokens") or 0)
                )
            )
            for part in (failed_usage, usage)
        )
        tps = (completion_tokens / elapsed) if elapsed > 0 else 0.0

        logger.info(
            f"vLLM call successful: {total_tokens} tokens in {elapsed:.2f}s ({tps:.1f} t/s)"
        )

        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("Model output was truncated before completion")
        message = choice.get("message") or {}
        if not isinstance(message, dict):
            raise ValueError("Model response message was not an object")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            content = str(content)
        message = {
            **message,
            "content": strip_think_tags(content) if isinstance(content, str) else None,
        }
        metrics = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "elapsed_seconds": round(elapsed, 3),
            "tokens_per_second": round(tps, 2),
            "usage_reported": usage_reported,
            "response_model": str(data.get("model") or "")[:255] or None,
        }
        return message, cast("VLLMMetrics", metrics)
    except httpx.TimeoutException as exc:
        logger.error(f"vLLM API timeout after {timeout}s")
        raise HTTPException(status_code=504, detail=t("service.vllm_timeout")) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.error(f"vLLM API returned status {status}")
        raise HTTPException(
            status_code=502, detail=t("service.vllm_error_status", status=status)
        ) from exc
    except Exception as exc:
        logger.error(f"vLLM API call failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=502, detail=t("service.vllm_call_failed", exc=exc)
        ) from exc


async def call_vllm(
    payload: dict[str, Any], timeout: float = 120.0
) -> tuple[str, VLLMMetrics]:
    """Call vLLM chat/completions and return text for non-agent callers."""
    message, metrics = await call_vllm_message(payload, timeout=timeout)
    message = assistant_message(message)
    content = message.get("content") or ""
    return str(content), metrics


def assistant_message(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        message = dict(value)
        message.setdefault("role", "assistant")
        return message
    return {"role": "assistant", "content": str(value or "")}


def tool_arguments(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
