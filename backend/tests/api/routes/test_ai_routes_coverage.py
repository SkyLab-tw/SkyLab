"""AI 路由（ai_template_recommendation、ai_proxy、ai_pve_log、ai_api、ai_assistant）的直接呼叫測試。"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.ai.pve_log import ssh_exec as pve_ssh_exec
from app.ai.pve_log.history import PveHistoryValidationError
from app.ai.template_recommendation import options_service
from app.ai.template_recommendation.schemas import ChatMessage, ChatRequest, DeviceNode
from app.api.routes import ai_api as ai_api_route
from app.api.routes import ai_assistant as assistant_route
from app.api.routes import ai_proxy as proxy_route
from app.api.routes import ai_pve_log as pve_log_route
from app.api.routes import ai_template_recommendation as template_route

_USER = SimpleNamespace(id=uuid.uuid4(), email="user@example.com")


# ─── ai_template_recommendation ──────────────────────────────────────────────


class _SettingsWithModel:
    """VLLM_MODEL_NAME 是唯讀 property：包一層只覆寫模型名稱。"""

    def __init__(self, inner: Any, model_name: str) -> None:
        self._inner = inner
        self.VLLM_MODEL_NAME = model_name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _chat_request() -> ChatRequest:
    return ChatRequest(messages=[ChatMessage(role="user", content="我要架一個網站")])


async def test_template_chat_without_model_binding_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        template_route, "settings", _SettingsWithModel(template_route.settings, "")
    )
    with pytest.raises(HTTPException) as exc_info:
        await template_route.chat(
            request=_chat_request(), current_user=_USER, session=object()
        )
    assert exc_info.value.status_code == 503


async def test_template_chat_upstream_http_error_is_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def completion(*_args: Any, **_kwargs: Any) -> Any:
        raise httpx.ConnectError("vLLM unreachable")

    record = AsyncMock()
    monkeypatch.setattr(
        template_route,
        "settings",
        _SettingsWithModel(template_route.settings, "test-model"),
    )
    monkeypatch.setattr(
        options_service, "resolve_chat_gpu_options", lambda *_a, **_k: []
    )
    monkeypatch.setattr(template_route.client, "create_chat_completion", completion)
    monkeypatch.setattr(template_route, "_record_template_call", record)

    with pytest.raises(HTTPException) as exc_info:
        await template_route.chat(
            request=_chat_request(), current_user=_USER, session=object()
        )

    assert exc_info.value.status_code == 502
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)
    assert record.await_args.kwargs["status"] == "error"


def _patch_recommend(
    monkeypatch: pytest.MonkeyPatch, live_nodes: Any
) -> SimpleNamespace:
    resources: dict[str, Any] = {"application_templates": [], "gpu_options": []}
    captured: dict[str, Any] = {}

    async def plan(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], dict]:
        return {"summary": "建議 LXC"}, {"total_tokens": 15}

    def normalize(
        ai_result: dict[str, Any],
        merged_request: Any,
        device_nodes: list[Any],
        *,
        resource_options: dict[str, Any],
        fallback: bool,
    ) -> dict[str, Any]:
        captured["device_nodes"] = list(device_nodes)
        captured["fallback"] = fallback
        return dict(ai_result)

    def resolve_resources(*args: Any, **_kwargs: Any) -> dict[str, Any]:
        captured["resource_args"] = args
        return resources

    monkeypatch.setattr(
        template_route,
        "settings",
        _SettingsWithModel(template_route.settings, "test-model"),
    )
    monkeypatch.setattr(
        options_service, "resolve_recommend_gpu_options", lambda *_a, **_k: []
    )
    monkeypatch.setattr(options_service, "resolve_resource_options", resolve_resources)
    monkeypatch.setattr(options_service, "get_live_device_nodes_safely", live_nodes)
    monkeypatch.setattr(template_route, "generate_ai_plan", plan)
    monkeypatch.setattr(template_route, "normalize_ai_result", normalize)
    monkeypatch.setattr(template_route, "_record_template_call", AsyncMock())

    # 同一個 worker thread 第二次執行的 load_options 不會被 coverage 的 CTracer
    # 記到（離開 event loop 的行為由 test_template_recommendation_offloop 驗證），
    # 這裡改在呼叫端同步執行，確保巢狀函式本身真的跑過。
    async def inline_to_thread(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(template_route.asyncio, "to_thread", inline_to_thread)
    return SimpleNamespace(captured=captured, resources=resources)


async def test_template_recommend_uses_live_device_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = DeviceNode(node="pve1", maxcpu=32)

    async def live_nodes() -> list[DeviceNode]:
        return [node]

    patched = _patch_recommend(monkeypatch, live_nodes)

    result = await template_route.recommend(
        request=_chat_request(), current_user=_USER, session=object()
    )

    assert result["summary"] == "建議 LXC"
    assert result["live_device_nodes"] == [node.model_dump()]
    assert result["resource_options"] is patched.resources
    assert result["ai_metrics"] == {"total_tokens": 15}
    assert patched.captured["device_nodes"] == [node]
    assert patched.captured["resource_args"][3] is _USER


async def test_template_recommend_falls_back_when_live_nodes_are_slow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never = asyncio.Event()

    async def slow_live_nodes() -> list[DeviceNode]:
        await never.wait()
        return [DeviceNode(node="late")]

    patched = _patch_recommend(monkeypatch, slow_live_nodes)

    result = await template_route.recommend(
        request=_chat_request(), current_user=_USER, session=object()
    )

    assert result["live_device_nodes"] == []
    assert patched.captured["device_nodes"] == []


def test_template_usage_window_and_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = MagicMock()
    gateway.default_usage_window.return_value = ("start", "end")
    monkeypatch.setattr(template_route, "ai_gateway_service", gateway)
    session = MagicMock()

    result = template_route.get_my_template_usage(
        current_user=_USER, session=session, start_date=None, end_date=None, tz="UTC"
    )

    assert result is gateway.get_user_template_usage_stats.return_value
    gateway.get_user_template_usage_stats.assert_called_once_with(
        session=session,
        user_id=_USER.id,
        start_date="start",
        end_date="end",
        tz="UTC",
    )


# ─── ai_proxy ────────────────────────────────────────────────────────────────


def _http_request(body: bytes, content_type: str = "application/json") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/ai-proxy/chat/completions",
        "headers": [(b"content-type", content_type.encode())],
        "query_string": b"",
    }
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return Request(scope, receive)


def _credential(rate_limit: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        rate_limit=rate_limit,
        request_id=uuid.uuid4(),
        _rate_limit_legacy_ids=(),
    )


async def test_proxy_json_payload_accepts_finite_floats() -> None:
    payload = await proxy_route._json_payload(
        _http_request(b'{"model": "m", "temperature": 0.5}')
    )
    assert payload == {"model": "m", "temperature": 0.5}


async def test_proxy_json_payload_rejects_non_object() -> None:
    response = await proxy_route._json_payload(_http_request(b"[1, 2]"))
    assert isinstance(response, JSONResponse)
    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "invalid_request"


async def test_proxy_relay_returns_payload_error_before_relaying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay = AsyncMock()
    monkeypatch.setattr(proxy_route, "_enforce_rate_limit", AsyncMock())
    monkeypatch.setattr(proxy_route.relay_service, "relay_generation", relay)

    response = await proxy_route._relay_generation(
        endpoint="chat/completions",
        request=_http_request(b"{}", content_type="text/plain"),
        user_and_credential=(_USER, _credential()),
    )

    assert response.status_code == 415
    relay.assert_not_awaited()


async def test_proxy_relay_returns_model_error_before_relaying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay = AsyncMock()
    monkeypatch.setattr(proxy_route, "_enforce_rate_limit", AsyncMock())
    monkeypatch.setattr(proxy_route.relay_service, "relay_generation", relay)

    response = await proxy_route._relay_generation(
        endpoint="chat/completions",
        request=_http_request(b'{"messages": []}'),
        user_and_credential=(_USER, _credential()),
    )

    assert response.status_code == 400
    relay.assert_not_awaited()


@pytest.mark.parametrize(
    ("handler", "endpoint"),
    [("completions", "completions"), ("responses", "responses")],
)
async def test_proxy_generation_endpoints_forward(
    monkeypatch: pytest.MonkeyPatch, handler: str, endpoint: str
) -> None:
    relay = AsyncMock(return_value="relayed")
    monkeypatch.setattr(proxy_route, "_relay_generation", relay)
    request = _http_request(b"{}")
    pair = (_USER, _credential())

    result = await getattr(proxy_route, handler)(
        request=request, user_and_credential=pair
    )

    assert result == "relayed"
    relay.assert_awaited_once_with(
        endpoint=endpoint, request=request, user_and_credential=pair
    )


async def test_proxy_rate_limit_status_when_redis_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proxy_route, "get_redis", AsyncMock(return_value=None))

    status = await proxy_route.get_rate_limit_status(
        user_and_credential=(_USER, _credential(rate_limit=7))
    )

    assert status.disabled is True
    assert (status.limit_per_minute, status.remaining) == (7, 7)


async def test_proxy_rate_limit_status_when_peek_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proxy_route, "get_redis", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        proxy_route, "peek_rate_limit_by_key", AsyncMock(return_value=None)
    )

    status = await proxy_route.get_rate_limit_status(
        user_and_credential=(_USER, _credential(rate_limit=9))
    )

    assert status.error == "rate_limit_status_unavailable"
    assert (status.current_usage, status.remaining) == (0, 9)


# ─── ai_pve_log ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("error", "status_code"),
    [(PveHistoryValidationError("bad transcript"), 422), (RuntimeError("x"), 500)],
)
async def test_pve_log_chat_maps_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, status_code: int
) -> None:
    monkeypatch.setattr(pve_log_route, "pve_chat", AsyncMock(side_effect=error))

    with pytest.raises(HTTPException) as exc_info:
        await pve_log_route.chat(
            request=SimpleNamespace(message="hi", messages=[]),
            current_user=_USER,
            session=MagicMock(),
        )

    assert exc_info.value.status_code == status_code
    if status_code == 422:
        assert exc_info.value.detail == "bad transcript"


async def test_pve_log_ssh_confirm_failure_is_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pve_ssh_exec,
        "confirm_exec",
        AsyncMock(side_effect=RuntimeError("ssh refused")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await pve_log_route.post_ssh_confirm(
            request=SimpleNamespace(), current_user=_USER, session=MagicMock()
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "ssh refused"


# ─── ai_api ──────────────────────────────────────────────────────────────────


def test_ai_api_admin_and_owner_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = MagicMock()
    monkeypatch.setattr(ai_api_route, "ai_gateway_service", gateway)
    session = MagicMock()
    request_id = uuid.uuid4()
    credential_id = uuid.uuid4()

    assert (
        ai_api_route.list_all_ai_api_requests(
            session=session, _current_user=_USER, status=None, skip=0, limit=10
        )
        is gateway.list_all_requests.return_value
    )
    assert (
        ai_api_route.get_ai_api_request(
            request_id=request_id, session=session, current_user=_USER
        )
        is gateway.get_request.return_value
    )
    assert (
        ai_api_route.delete_my_ai_api_credential(
            credential_id=credential_id, session=session, current_user=_USER
        )
        is gateway.delete_credential.return_value
    )
    gateway.delete_credential.assert_called_once_with(
        session=session, credential_id=credential_id, current_user=_USER
    )


# ─── ai_assistant ────────────────────────────────────────────────────────────


async def test_assistant_chat_streams_events_and_ends_with_the_final_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai.assistant.schemas import AssistantChatResponse

    final = AssistantChatResponse(request_id="r1", reply="到防火牆頁設定。")
    seen: list[tuple[Any, ...]] = []

    async def chat_stream(request: Any, user: Any, *, session: Any) -> Any:
        seen.append((request, user, session))
        yield {"type": "status", "tool": "read_help"}
        yield {"type": "delta", "text": "到防火牆"}
        yield {"type": "reset"}
        yield {"type": "final", "response": final}

    monkeypatch.setattr(assistant_route, "chat_stream", chat_stream)
    session = MagicMock()

    events = [
        event
        async for event in assistant_route.assistant_chat(
            request="req", session=session, current_user=_USER
        )
    ]
    assert seen == [("req", _USER, session)]
    assert [(event.event, event.data) for event in events] == [
        ("status", {"tool": "read_help"}),
        ("delta", {"text": "到防火牆"}),
        ("reset", {}),
        ("final", final),
    ]


async def test_assistant_chat_reports_a_mid_stream_failure_as_an_error_event(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """標頭送出之後改不了狀態碼：前端靠 error 事件知道這一輪不會有回應。"""

    async def chat_stream(request: Any, user: Any, *, session: Any) -> Any:
        yield {"type": "delta", "text": "寫到一半"}
        raise RuntimeError("boom")

    monkeypatch.setattr(assistant_route, "chat_stream", chat_stream)
    with caplog.at_level("ERROR"):
        events = [
            event
            async for event in assistant_route.assistant_chat(
                request="req", session=MagicMock(), current_user=_USER
            )
        ]
    assert [(event.event, event.data) for event in events] == [
        ("delta", {"text": "寫到一半"}),
        ("error", {}),
    ]
    assert "Assistant chat stream failed" in caplog.text


def test_assistant_chat_is_served_as_server_sent_events() -> None:
    """走完整個 HTTP 堆疊：事件格式、不緩衝的標頭、最後一則是完整回應。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.ai.assistant.schemas import AssistantChatResponse
    from app.api.deps import get_current_user
    from app.api.deps.database import get_db

    final = AssistantChatResponse(request_id="r1", reply="到「防火牆」頁設定。")

    async def chat_stream(request: Any, user: Any, *, session: Any) -> Any:
        yield {"type": "delta", "text": "到「防火牆」"}
        yield {"type": "final", "response": final}

    app = FastAPI()
    app.include_router(assistant_route.router)
    app.dependency_overrides[get_current_user] = lambda: _USER
    app.dependency_overrides[get_db] = lambda: MagicMock()
    for route in app.routes:
        if getattr(route, "path", "") == "/ai/assistant/chat":
            for dependency in route.dependencies:
                app.dependency_overrides[dependency.dependency] = lambda: None

    original = assistant_route.chat_stream
    assistant_route.chat_stream = chat_stream
    try:
        with TestClient(app) as client:
            response = client.post(
                "/ai/assistant/chat",
                json={"messages": [{"role": "user", "content": "怎麼開 port"}]},
            )
    finally:
        assistant_route.chat_stream = original

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"
    blocks = [block for block in response.text.split("\n\n") if block]
    assert [block.split("\n")[0] for block in blocks] == [
        "event: delta",
        "event: final",
    ]
    assert json.loads(blocks[0].split("data: ", 1)[1]) == {"text": "到「防火牆」"}
    assert json.loads(blocks[1].split("data: ", 1)[1]) == final.model_dump(mode="json")


def test_assistant_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    surfaces = [
        SimpleNamespace(
            id="resources",
            path="/my-resources",
            title="我的資源",
            purpose="管理機器",
            when_to_use="要操作機器時",
            elements=[object()],
        ),
        SimpleNamespace(
            id="home",
            path="/",
            title="首頁",
            purpose="",
            when_to_use="",
            elements=[],
        ),
    ]
    monkeypatch.setattr(assistant_route, "get_surfaces_for_user", lambda user: surfaces)

    listed = assistant_route.list_surfaces(current_user=_USER)
    assert [(item.id, item.path, item.has_fields) for item in listed] == [
        ("resources", "/my-resources", True),
        ("home", "/", False),
    ]
    assert listed[0].when_to_use == "要操作機器時"
    # 欄位定義只在回答時進 prompt，不整包送到瀏覽器
    assert set(type(listed[0]).model_fields) == {
        "id",
        "path",
        "title",
        "purpose",
        "when_to_use",
        "has_fields",
    }


def test_assistant_chat_is_rate_limited_and_surfaces_is_not() -> None:
    """每一句話會打模型好幾次，沒有節流一個帳號就能把推論排隊塞滿。"""
    routes = {route.path: route for route in assistant_route.router.routes}
    assert set(routes) == {"/ai/assistant/chat", "/ai/assistant/surfaces"}
    assert routes["/ai/assistant/chat"].methods == {"POST"}
    assert len(routes["/ai/assistant/chat"].dependencies) == 1
    assert routes["/ai/assistant/surfaces"].methods == {"GET"}
    assert routes["/ai/assistant/surfaces"].dependencies == []


def test_assistant_routes_are_mounted_and_the_old_ones_are_gone() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/ai/assistant/chat" in paths
    assert "/api/v1/ai/assistant/surfaces" in paths
    for removed in (
        "/api/v1/ai/navigation/resolve",
        "/api/v1/ai/navigation/intake",
        "/api/v1/ai/contextual-help/explain",
        "/api/v1/ai/contextual-help/surfaces",
    ):
        assert removed not in paths
