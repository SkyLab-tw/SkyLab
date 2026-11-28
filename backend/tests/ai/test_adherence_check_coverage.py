"""Coverage tests for app.ai.adherence_check fail-closed parsing."""

import json

import pytest

from app.ai import adherence_check
from app.ai.role_contracts import (
    AdherenceReason,
    AdherenceVerdict,
    OutputMode,
    RoleContract,
    adherence_result_schema,
)
from app.infrastructure.ai.model_adapter import ModelAdapterError

_CONTRACT = RoleContract(
    role_id="pve_log",
    output_mode=OutputMode.MODEL_FREE_TEXT,
    contract_version="v1",
    fallback_key="k",
)


class _Client:
    def __init__(self, response):
        self.response = response

    async def create_chat_completion(self, payload, *, profile, timeout, request_id):
        del payload, profile, timeout, request_id
        return self.response


def _message(content, **extra):
    return {"choices": [{"message": {"content": content, **extra}}]}


@pytest.mark.parametrize(
    "response",
    [
        {"choices": []},
        {"choices": ["not-a-dict"]},
        {"choices": [{"finish_reason": "length", "message": {}}]},
        {"choices": [{"message": "text"}]},
        _message("{}", tool_calls=[{"id": "x"}]),
        _message('{"verdict": "allow"}'),
        _message("[]"),
    ],
)
async def test_invalid_responses_fail_closed(response) -> None:
    result = await adherence_check.check_adherence(
        _Client(response),
        _CONTRACT,
        "q",
        "candidate",
        {},
        "req-1",
        model_name="m",
        phase="respond",
    )
    assert result.verdict is AdherenceVerdict.INSUFFICIENT_CONTEXT
    assert result.reason_code is AdherenceReason.CHECK_FAILED


@pytest.mark.parametrize(("model", "request_id"), [(" ", "req"), ("m", " ")])
async def test_blank_model_or_request_id_fails_closed(model, request_id) -> None:
    result = await adherence_check.check_adherence(
        _Client({}),
        _CONTRACT,
        "q",
        "c",
        {},
        request_id,
        model_name=model,
        phase="respond",
    )
    assert result.reason_code is AdherenceReason.CHECK_FAILED
    assert result.completion_tokens == adherence_check.ADHERENCE_MAX_TOKENS


async def test_teacher_judge_policy_allows_partial_action_coverage() -> None:
    sent: list[dict] = []

    class _Recording(_Client):
        async def create_chat_completion(self, payload, *, profile, timeout, request_id):
            sent.append(payload)
            return await super().create_chat_completion(
                payload, profile=profile, timeout=timeout, request_id=request_id
            )

    contract = RoleContract(
        role_id="teacher_judge",
        output_mode=OutputMode.MODEL_ACTION,
        contract_version="v1",
        fallback_key="k",
    )
    result = await adherence_check.check_adherence(
        _Recording(_message('{"verdict": "allow", "reason_code": "none"}')),
        contract,
        "q",
        [],
        {},
        "req-1",
        model_name="m",
        phase="act",
    )

    assert result.allowed
    data = json.loads(sent[0]["messages"][1]["content"])
    policy = data["contract"]["role_policy"]
    assert "subset of the request" in policy
    assert "never a reason to block" in policy
    # The rule is scoped to Teacher Judge; other roles keep their own policy.
    assert "subset of the request" not in adherence_check._ROLE_POLICIES["pve_log"]


# ── 功能自帶的檢查提示詞與資料、模型設定檔指定的檢查 thinking ─────────────────


class _Recorder:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create_chat_completion(self, payload, **kwargs):
        self.calls.append((payload, kwargs))
        return self.response


_ALLOWED = _message('{"verdict": "allow", "reason_code": "none"}')


async def _check(client, *, model: str = "m", **extra):
    return await adherence_check.check_adherence(
        client,
        _CONTRACT,
        "q",
        "candidate",
        {"k": 1},
        "req-1",
        model_name=model,
        phase="respond",
        **extra,
    )


async def test_default_prompt_and_document_are_built_from_the_contract() -> None:
    client = _Recorder(_ALLOWED)
    result = await _check(client)
    assert result.allowed
    payload, kwargs = client.calls[0]
    assert payload["messages"][0] == {
        "role": "system",
        "content": adherence_check._SYSTEM_PROMPT,
    }
    document = json.loads(payload["messages"][1]["content"])
    assert set(document) == {"contract", "user_request", "candidate", "facts"}
    assert document["contract"]["role_id"] == "pve_log"
    assert document["contract"]["role_policy"]
    assert document["facts"] == {"k": 1}
    # 沒登錄的模型不覆寫 thinking，既有的 client 替身不必認得這個參數
    assert "thinking" not in kwargs


async def test_a_feature_can_supply_its_own_prompt_and_document() -> None:
    """通用提示詞不認識某個功能的正常行為時，換提示詞與資料，協定不變。"""
    client = _Recorder(_ALLOWED)
    document = {
        "user_request": "問題",
        "candidate": "回答",
        "tools_used": ["show_pages"],
    }
    result = await _check(client, system_prompt="只擋三種情況。", document=document)

    assert result.allowed
    payload, _kwargs = client.calls[0]
    assert payload["messages"][0] == {"role": "system", "content": "只擋三種情況。"}
    assert payload["messages"][1]["role"] == "user"
    assert json.loads(payload["messages"][1]["content"]) == document
    assert "contract" not in payload["messages"][1]["content"]
    assert payload["max_tokens"] == adherence_check.ADHERENCE_MAX_TOKENS
    assert payload["stream"] is False
    assert payload["response_format"]["type"] == "json_schema"
    assert (
        payload["response_format"]["json_schema"]["schema"] == adherence_result_schema()
    )


async def test_an_overridden_check_still_fails_closed() -> None:
    client = _Recorder(_message("not-json"))
    result = await _check(client, system_prompt="p", document={"candidate": "x"})
    assert result.verdict is AdherenceVerdict.INSUFFICIENT_CONTEXT
    assert result.reason_code is AdherenceReason.CHECK_FAILED


async def test_models_that_declare_check_thinking_get_it_passed_explicitly() -> None:
    """推理比較多話的模型在 128 token 內寫不完結果；設定檔指定檢查時關掉推理。"""
    client = _Recorder(_ALLOWED)
    await _check(client, model="BIRC-LLM")
    _payload, kwargs = client.calls[0]
    assert kwargs["thinking"] == "none"


@pytest.mark.parametrize(
    "model",
    ["gpt-oss-120B", "gemma4-26b-a4b-it", "Qwen/Qwen3.8-27B", "not-registered"],
)
async def test_other_models_keep_their_model_wide_thinking(model: str) -> None:
    client = _Recorder(_ALLOWED)
    await _check(client, model=model)
    _payload, kwargs = client.calls[0]
    assert "thinking" not in kwargs


async def test_a_broken_profile_file_does_not_hide_behind_the_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """讀不到模型設定檔時不覆寫，讓真正的 client 呼叫照實報錯。"""

    def broken(_model: str):
        raise ModelAdapterError("bad yaml")

    monkeypatch.setattr(adherence_check, "check_thinking_override", broken)
    client = _Recorder(_ALLOWED)
    result = await _check(client)
    assert result.allowed
    assert "thinking" not in client.calls[0][1]
