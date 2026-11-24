"""Normalize model-emitted rubric items and check steps into schema objects (package-internal)."""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from app.ai.teacher_judge.automation_support import (
    missing_step_information,
    non_empty_argv,
)
from app.ai.teacher_judge.schemas import (
    TeacherJudgeRubricCheckStep,
    TeacherJudgeRubricItem,
    sanitize_rubric_missing_information,
)
from app.ai.teacher_judge.template_command_service import (
    DEFAULT_SYSTEM_COMMAND_TIMEOUT_SECONDS,
    coerce_timeout_seconds,
    sanitize_check_step_parameters,
    validate_check_steps,
)
from app.ai.utils import safe_bool
from app.models.teacher_judge_template_command import TeacherJudgeTemplateCommand


def _normalize_check_steps(
    raw_steps: Any,
    template_key: str | None = None,
    template_commands: list[TeacherJudgeTemplateCommand] | None = None,
) -> list[TeacherJudgeRubricCheckStep]:
    if not isinstance(raw_steps, list):
        return []

    if any(
        isinstance(raw_step, dict) and isinstance(raw_step.get("collector"), dict)
        for raw_step in raw_steps
    ):
        typed_or_legacy: list[TeacherJudgeRubricCheckStep] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                continue
            if isinstance(raw_step.get("collector"), dict):
                try:
                    typed_or_legacy.append(TeacherJudgeRubricCheckStep(**raw_step))
                except ValueError:
                    continue
            else:
                typed_or_legacy.extend(
                    _normalize_check_steps(
                        [raw_step],
                        template_key=template_key,
                        template_commands=template_commands,
                    )
                )
        return typed_or_legacy

    if template_commands is not None:
        general_command = next(
            (
                command
                for command in template_commands
                if command.command_key == "system.run_command"
            ),
            None,
        )
        canonical_steps: list[Any] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                canonical_steps.append(raw_step)
                continue
            canonical_step = dict(raw_step)
            if (
                general_command is not None
                and str(raw_step.get("command_key") or "").strip()
                == general_command.command_key
            ):
                canonical_step["template_key"] = general_command.template_key
                raw_parameters = raw_step.get("parameters")
                parameters = (
                    dict(raw_parameters) if isinstance(raw_parameters, dict) else {}
                )
                for key in ("argv", "cwd", "timeout_seconds"):
                    if key not in parameters and key in raw_step:
                        parameters[key] = raw_step[key]
                canonical_step["parameters"] = parameters
            canonical_steps.append(canonical_step)

        validated_items = validate_check_steps(
            template_key or "",
            [{"check_steps": canonical_steps}],
            template_commands,
        )
        validated_steps = [
            TeacherJudgeRubricCheckStep(**step)
            for step in validated_items[0].get("check_steps", [])
        ]
        valid_raw_references = {
            (step.template_key, step.command_key) for step in validated_steps
        }
        if general_command is None:
            return validated_steps

        recovered_steps: list[dict[str, Any]] = []
        for raw_step in canonical_steps:
            if not isinstance(raw_step, dict):
                continue
            raw_template_key = str(
                raw_step.get("template_key") or template_key or ""
            ).strip()
            raw_command_key = str(raw_step.get("command_key") or "").strip()
            if (raw_template_key, raw_command_key) in valid_raw_references:
                continue
            raw_parameters = raw_step.get("parameters")
            recovered_parameters: dict[str, Any] = (
                dict(raw_parameters) if isinstance(raw_parameters, dict) else {}
            )
            argv = recovered_parameters.get("argv")
            if not non_empty_argv(argv):
                continue
            for key in ("path", "file_path", "target"):
                recovered_parameters.pop(key, None)
            recovered_parameters = {
                key: value
                for key, value in recovered_parameters.items()
                if key in {"argv", "cwd", "timeout_seconds"}
            }
            recovered_steps.append(
                {
                    "template_key": general_command.template_key,
                    "command_key": general_command.command_key,
                    "parameters": recovered_parameters,
                }
            )

        if recovered_steps:
            recovered_items = validate_check_steps(
                template_key or "",
                [{"check_steps": recovered_steps}],
                template_commands,
            )
            validated_steps.extend(
                TeacherJudgeRubricCheckStep(**step)
                for step in recovered_items[0].get("check_steps", [])
            )
        return validated_steps

    normalized: list[TeacherJudgeRubricCheckStep] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            continue

        command_key = str(raw_step.get("command_key") or "").strip()
        step_template_key = str(
            raw_step.get("template_key") or template_key or ""
        ).strip()
        raw_parameters = raw_step.get("parameters")
        parameters = dict(raw_parameters) if isinstance(raw_parameters, dict) else {}
        for key in ("argv", "cwd", "timeout_seconds"):
            if key not in parameters and key in raw_step:
                parameters[key] = raw_step[key]
        parameters = sanitize_check_step_parameters(parameters)

        if not command_key and "argv" in parameters:
            argv = parameters.get("argv")
            if not non_empty_argv(argv):
                continue
            timeout = coerce_timeout_seconds(parameters.get("timeout_seconds"))
            normalized.append(
                TeacherJudgeRubricCheckStep(
                    argv=argv,
                    cwd=(
                        parameters.get("cwd").strip()
                        if isinstance(parameters.get("cwd"), str)
                        and parameters.get("cwd").strip()
                        else None
                    ),
                    timeout_seconds=(timeout or DEFAULT_SYSTEM_COMMAND_TIMEOUT_SECONDS),
                )
            )
            continue

        if not command_key or not step_template_key:
            continue

        command_label = raw_step.get("command_label")

        normalized.append(
            TeacherJudgeRubricCheckStep(
                template_key=step_template_key,
                command_key=command_key,
                command_label=str(command_label) if command_label else None,
                parameters=parameters,
            )
        )

    return normalized


def normalize_rubric_items(
    raw_items: Any,
    template_key: str | None = None,
    template_commands: list[TeacherJudgeTemplateCommand] | None = None,
    strip_auto_fallback: bool = True,
) -> list[TeacherJudgeRubricItem]:
    """Normalize item fields while preserving explicitly recorded information gaps."""
    if not isinstance(raw_items, list):
        return []

    normalized: list[TeacherJudgeRubricItem] = []
    for i, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            continue

        item_id = str(raw.get("id") or f"item-{i + 1}")
        title = str(raw.get("title") or raw.get("name") or "").strip() or "未命名項目"
        checked = safe_bool(raw.get("checked", raw.get("is_checked")), default=False)

        raw_detectable = raw.get("detectable")
        if isinstance(raw_detectable, bool):
            detectable_raw = "auto" if raw_detectable else "manual"
        else:
            detectable_raw = str(raw_detectable or "manual").strip().lower()
        if detectable_raw not in {"auto", "partial", "manual"}:
            detectable_raw = "manual"
        detectable: Literal["auto", "partial", "manual"] = cast(
            "Literal['auto', 'partial', 'manual']", detectable_raw
        )
        judgement_mode_raw = str(raw.get("judgement_mode") or "ai").strip().lower()
        if judgement_mode_raw not in {"ai", "teacher"}:
            judgement_mode_raw = "ai"
        judgement_mode: Literal["ai", "teacher"] = cast(
            "Literal['ai', 'teacher']", judgement_mode_raw
        )

        detection_method = raw.get("detection_method") or raw.get("detection")
        fallback = raw.get("fallback") or raw.get("suggestion")
        raw_missing_information = raw.get("missing_information")
        missing_information = (
            list(
                dict.fromkeys(
                    str(value).strip()
                    for value in raw_missing_information
                    if isinstance(value, str) and value.strip()
                )
            )
            if isinstance(raw_missing_information, list)
            else []
        )
        missing_information = sanitize_rubric_missing_information(missing_information)
        check_steps = _normalize_check_steps(
            raw.get("check_steps"),
            template_key=template_key,
            template_commands=template_commands,
        )
        system_command_steps = [
            step for step in check_steps if step.command_key == "system.run_command"
        ]
        if system_command_steps:
            for step in system_command_steps:
                missing_information.extend(missing_step_information(step))
        if template_commands is not None and detectable == "auto" and not check_steps:
            detectable = "manual"
            missing_information = []
            detection_method = (
                str(detection_method).strip()
                if detection_method is not None
                else "目前沒有可引用的有效 command_key，缺少自動取得客觀證據的能力"
            )
            fallback = fallback or "目前平台不支援此項目的安全腳本取證。"
        if detectable == "auto" and (
            detection_method is None or not str(detection_method).strip()
        ):
            detectable = "partial"
            missing_information.append("腳本取證方式")
        if detectable == "auto":
            for step in check_steps:
                missing_information.extend(missing_step_information(step))
            if missing_information:
                detectable = "partial"
        if detectable == "partial" and not missing_information:
            missing_information.append("完整的服務名稱、程式位置、連接埠或取證範圍")
        missing_information = list(dict.fromkeys(missing_information))
        if strip_auto_fallback and detectable == "auto":
            fallback = None

        normalized.append(
            TeacherJudgeRubricItem(
                id=item_id,
                title=title,
                checked=checked,
                detectable=detectable,
                judgement_mode=judgement_mode,
                detection_method=str(detection_method)
                if detection_method is not None
                else None,
                fallback=str(fallback) if fallback is not None else None,
                missing_information=missing_information,
                target_node_key=(str(raw.get("target_node_key") or "").strip() or None),
                peer_node_key=(str(raw.get("peer_node_key") or "").strip() or None),
                check_steps=check_steps,
            )
        )

    return normalized


def normalize_items_for_export(raw_items: Any) -> list[TeacherJudgeRubricItem]:
    """Public helper for robust export parsing."""
    # Export accepts legacy/teacher-authored payloads and must not silently
    # discard an explicitly supplied fallback while normalizing field aliases.
    return normalize_rubric_items(raw_items, strip_auto_fallback=False)


def rubric_context_data(rubric_context: str) -> dict[str, Any]:
    try:
        parsed = json.loads(rubric_context or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def raw_items_by_id(raw_items: Any) -> dict[str, dict[str, Any]]:
    """Index model-emitted raw items by id.

    Missing ids fall back to ``item-<n>`` exactly like
    ``normalize_rubric_items`` so raw rows line up with normalized items.
    """
    if not isinstance(raw_items, list):
        return {}
    return {
        str(raw.get("id") or f"item-{index + 1}"): raw
        for index, raw in enumerate(raw_items)
        if isinstance(raw, dict)
    }


def raw_item_detectable(raw: dict[str, Any] | None) -> str:
    return str((raw or {}).get("detectable") or "").strip().lower()
