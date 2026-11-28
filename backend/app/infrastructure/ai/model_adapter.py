"""Small, model-wide request contracts for the direct-vLLM System AI client."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONFIG_FILE = Path(__file__).resolve().parents[3] / "config" / "llm-model-profiles.yaml"
logger = logging.getLogger(__name__)

ResponseFormat = Literal["json_object", "json_schema"]
ToolChoiceMode = Literal["auto", "none", "required", "named"]
# 單次請求可以指定的 thinking 等級；None 代表沿用模型設定檔的全模型預設。
ThinkingLevel = Literal["none", "low", "medium", "high"]
_THINKING_LEVELS = frozenset({"none", "low", "medium", "high"})
ModelName = Annotated[str, Field(min_length=1)]
_LEGACY_THINKING = frozenset({"none", "off", "low", "medium", "high"})


class ModelAdapterError(ValueError):
    """Invalid configuration or an unsupported model request contract."""


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    thinking: Literal["none", "low"]
    thinking_parameter: Literal[
        "reasoning_effort", "enable_thinking", "chat_template_reasoning_effort"
    ]
    response_formats: tuple[ResponseFormat, ...]
    native_tool_calls: bool
    tool_choice_modes: tuple[ToolChoiceMode, ...]
    # 遵循檢查的輸出上限很緊（128 token，推理也算在內）。推理比較多話的模型開著
    # 推理會在寫出結果前就被截斷，可以在這裡指定檢查改用「關」；不設就沿用 thinking。
    check_thinking: Literal["none"] | None = None

    @field_validator("response_formats", "tool_choice_modes", mode="before")
    @classmethod
    def freeze_lists(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_contract(self) -> ModelProfile:
        if (
            self.thinking_parameter == "chat_template_reasoning_effort"
            and self.thinking != "low"
        ):
            raise ValueError("reasoning_effort requires thinking='low'")
        if not self.native_tool_calls and self.tool_choice_modes:
            raise ValueError("tool_choice_modes require native_tool_calls")
        if len(set(self.response_formats)) != len(self.response_formats):
            raise ValueError("duplicate response_formats")
        if len(set(self.tool_choice_modes)) != len(self.tool_choice_modes):
            raise ValueError("duplicate tool_choice_modes")
        return self


class ModelProfiles(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: int
    models: dict[ModelName, ModelProfile] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def validate_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported schema_version")
        return value

    @field_validator("models")
    @classmethod
    def validate_names(cls, value: dict[str, ModelProfile]) -> dict[str, ModelProfile]:
        if any(name != name.strip() for name in value):
            raise ValueError("model keys must not have surrounding whitespace")
        return value


class _UniqueKeyLoader(yaml.SafeLoader):  # type: ignore[misc]
    """SafeLoader scoped to this file; never silently replace a duplicate key."""


def _unique_mapping(loader: Any, node: Any) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            if key in result:
                raise ModelAdapterError(f"Duplicate YAML key: {key!r}")
            result[key] = loader.construct_object(value_node, deep=True)
        except TypeError as exc:
            raise ModelAdapterError("YAML mapping keys must be scalar values") from exc
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


@lru_cache(maxsize=1)
def load_model_profiles() -> ModelProfiles:
    """Read the fixed backend config once, independent of the working directory."""
    try:
        raw = yaml.load(
            CONFIG_FILE.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader
        )
        return ModelProfiles.model_validate(raw)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ModelAdapterError(f"Invalid {CONFIG_FILE}: {exc}") from exc


def check_thinking_override(model: str) -> ThinkingLevel | None:
    """遵循檢查該用的 thinking 等級；設定檔沒有指定（或模型沒登錄）就回 None。"""
    profile = load_model_profiles().models.get(model)
    return profile.check_thinking if profile is not None else None


def adapt_chat_request(
    payload: dict[str, Any], *, thinking: ThinkingLevel | None = None
) -> dict[str, Any]:
    """Copy and adapt only model-owned fields; leave budgets and business data alone.

    ``thinking`` 是呼叫端（功能模組）明確要求的等級，只能由後端程式傳入；payload 裡的
    legacy 欄位仍一律被覆寫。沒給就用設定檔的全模型預設。只有開／關的模型
    （``enable_thinking``）把 low／medium／high 都當成「開」。
    """
    if thinking is not None and thinking not in _THINKING_LEVELS:
        raise ModelAdapterError(f"Invalid thinking level: {thinking!r}")
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ModelAdapterError("A non-empty model is required")
    profile = load_model_profiles().models.get(model)
    if profile is None:
        raise ModelAdapterError(
            f"No model contract for {model!r} in {CONFIG_FILE.name}"
        )

    template = payload.get("chat_template_kwargs")
    if template is not None and not isinstance(template, dict):
        raise ModelAdapterError("chat_template_kwargs must be an object")
    template_kwargs = dict(template or {})
    if (
        "enable_thinking" in template_kwargs
        and type(template_kwargs["enable_thinking"]) is not bool
    ):
        raise ModelAdapterError("Legacy enable_thinking must be a boolean")
    valid_efforts = _LEGACY_THINKING
    if profile.thinking_parameter == "chat_template_reasoning_effort":
        valid_efforts = valid_efforts | {"xhigh"}
    for source in (payload, template_kwargs):
        if "reasoning_effort" in source:
            effort = source["reasoning_effort"]
            if not isinstance(effort, str) or effort not in valid_efforts:
                raise ModelAdapterError("Invalid legacy reasoning_effort")

    response_format = payload.get("response_format")
    if response_format is not None:
        if (
            not isinstance(response_format, dict)
            or response_format.get("type") not in profile.response_formats
        ):
            raise ModelAdapterError(
                f"Model {model!r} does not support this response_format"
            )
    if payload.get("tools"):
        if not profile.native_tool_calls:
            raise ModelAdapterError(
                f"Model {model!r} does not support native tool calls"
            )
        choice = payload.get("tool_choice")
        mode = "named" if isinstance(choice, dict) else choice
        if mode not in profile.tool_choice_modes:
            raise ModelAdapterError(
                f"Model {model!r} does not support this tool_choice"
            )

    level: str = thinking if thinking is not None else profile.thinking
    wire = dict(payload)
    wire.pop("reasoning_effort", None)
    template_kwargs.pop("reasoning_effort", None)
    template_kwargs.pop("enable_thinking", None)
    if profile.thinking_parameter == "reasoning_effort":
        # 頂層 reasoning_effort 能不能送 "none" 看模型：設定檔的 thinking 或
        # check_thinking 寫了 "none"，代表這個模型收得下（例如 BIRC-LLM）；沒寫的
        # 模型只有強度、沒有開關，要求關閉時不能默默改成最低強度。
        if level == "none" and "none" not in {profile.thinking, profile.check_thinking}:
            raise ModelAdapterError(f"Model {model!r} cannot disable reasoning")
        wire["reasoning_effort"] = level
        if template_kwargs:
            wire["chat_template_kwargs"] = template_kwargs
        else:
            wire.pop("chat_template_kwargs", None)
    elif profile.thinking_parameter == "chat_template_reasoning_effort":
        if level == "none":
            wire["chat_template_kwargs"] = {**template_kwargs, "enable_thinking": False}
        else:
            wire["chat_template_kwargs"] = {
                **template_kwargs,
                "enable_thinking": True,
                "reasoning_effort": level,
            }
    else:
        wire["chat_template_kwargs"] = {
            **template_kwargs,
            "enable_thinking": level != "none",
        }
    logger.debug(
        "System AI model contract: model=%s thinking=%s parameter=%s",
        model,
        level,
        profile.thinking_parameter,
    )
    return wire
