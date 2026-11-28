"""需要 GPU 時，規劃挑的 VM 來源要是申請表單上真的能選 GPU 的那種。

申請表單只在來源需要 GPU 時才顯示 GPU 欄位（名稱結尾 -GPU，或範本標記需要 GPU）；
挑到一般的來源，規劃出來的 GPU 填進表單時會被擋下。
"""

from __future__ import annotations

from typing import Any

from app.ai.template_recommendation import recommendation_service as svc
from app.ai.template_recommendation.schemas import (
    RecommendationFormContext,
    RecommendationRequest,
)

_GPU = {
    "mapping_id": "gpu-a",
    "description": "NVIDIA L4",
    "model": "L4",
    "available_count": 1,
}


def _resources(**overrides: Any) -> dict[str, Any]:
    resources: dict[str, Any] = {
        "lxc_os_images": [
            {"value": "local:vztmpl/debian-12.tar.zst", "label": "debian-12"}
        ],
        "vm_operating_systems": [
            {"template_id": 9001, "label": "Windows 11"},
            {"template_id": 9002, "label": "Ubuntu 24.04 Desktop"},
            {"template_id": 9003, "label": "Ubuntu-24.04-GPU"},
            {"template_id": 9004, "label": "Windows-11-gpu"},
        ],
        "application_templates": [],
        "gpu_options": [_GPU],
    }
    resources.update(overrides)
    return resources


def _plan(
    request: RecommendationRequest, ai: dict[str, Any] | None = None, **overrides: Any
) -> dict[str, Any]:
    result = svc.normalize_ai_result(
        ai or {}, request, [], resource_options=_resources(**overrides)
    )
    return result["final_plan"]["form_prefill"]


def test_gpu_request_picks_a_gpu_marked_source() -> None:
    prefill = _plan(RecommendationRequest(goal="訓練 YOLO 模型", requires_gpu=True))
    assert prefill["resource_type"] == "vm"
    assert prefill["vm_template_id"] == 9003
    assert prefill["gpu_mapping_id"] == "gpu-a"


def test_gpu_request_for_windows_picks_the_windows_gpu_source() -> None:
    prefill = _plan(
        RecommendationRequest(
            goal="跑 CUDA 範例", requires_gpu=True, needs_windows=True
        )
    )
    assert prefill["vm_template_id"] == 9004


def test_a_template_flagged_as_requiring_gpu_counts_without_the_name_marker() -> None:
    prefill = _plan(
        RecommendationRequest(goal="訓練影像模型", requires_gpu=True),
        vm_operating_systems=[
            {"template_id": 9001, "label": "Windows 11"},
            {"template_id": 9002, "label": "Ubuntu 24.04 Desktop"},
        ],
        application_templates=[
            {
                "template_id": 500,
                "name": "PyTorch 訓練環境",
                "resource_type": "vm",
                "requires_gpu": True,
            }
        ],
    )
    assert prefill["vm_template_id"] == 500


def test_model_choice_of_a_non_gpu_source_is_replaced_when_gpu_is_needed() -> None:
    prefill = _plan(
        RecommendationRequest(goal="訓練 YOLO 模型", requires_gpu=True),
        {"form_prefill": {"resource_type": "vm", "vm_template_id": 9002}},
    )
    assert prefill["vm_template_id"] == 9003


def test_model_choice_of_a_gpu_source_is_kept() -> None:
    prefill = _plan(
        RecommendationRequest(goal="跑 CUDA 範例", requires_gpu=True),
        {"form_prefill": {"resource_type": "vm", "vm_template_id": 9004}},
    )
    assert prefill["vm_template_id"] == 9004


def test_source_the_user_already_selected_in_the_form_is_not_overridden() -> None:
    request = RecommendationRequest(
        goal="訓練 YOLO 模型",
        requires_gpu=True,
        form_context=RecommendationFormContext(resource_type="vm", vm_template_id=9002),
    )
    assert _plan(request)["vm_template_id"] == 9002


def test_without_any_gpu_capable_source_the_previous_choice_stands() -> None:
    prefill = _plan(
        RecommendationRequest(goal="訓練 YOLO 模型", requires_gpu=True),
        vm_operating_systems=[
            {"template_id": 9001, "label": "Windows 11"},
            {"template_id": 9002, "label": "Ubuntu 24.04 Desktop"},
        ],
    )
    assert prefill["vm_template_id"] == 9002
    assert prefill["gpu_mapping_id"] == "gpu-a"


def test_gpu_source_is_not_preferred_when_no_gpu_is_needed_or_none_is_free() -> None:
    assert (
        _plan(RecommendationRequest(goal="遠端桌面寫報告", needs_desktop=True))[
            "vm_template_id"
        ]
        == 9002
    )
    no_free_card = _plan(
        RecommendationRequest(
            goal="訓練 YOLO 模型", requires_gpu=True, needs_desktop=True
        ),
        gpu_options=[{**_GPU, "available_count": 0}],
    )
    assert no_free_card["vm_template_id"] == 9002
    assert no_free_card["gpu_mapping_id"] == ""
