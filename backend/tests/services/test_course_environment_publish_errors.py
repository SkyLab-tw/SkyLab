"""發布草稿的驗證錯誤要變成看得懂、依語系的一句話，不能是 pydantic 原文。"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core import i18n
from app.core.i18n import translate
from app.core.request_context import DEFAULT_LANGUAGE
from app.schemas.course_environment import EnvironmentCreate
from app.services.course_environment.publish_errors import publish_validation_message

TEMPLATE_ID = str(uuid.uuid4())


def tr(key: str, **params: object) -> str:
    return translate(key, DEFAULT_LANGUAGE, **params)


def _node(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "node_key": "web",
        "source_type": "template",
        "source_template_id": TEMPLATE_ID,
        "name": "Web",
        "role": "server",
        "resource_type": "qemu",
        "cpu": 2,
        "memory_mb": 2048,
        "disk_gb": 20,
    }
    data.update(overrides)
    return data


def _edge(index: int, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source_node_key": "web",
        "target_node_key": "db",
        "protocol": "tcp",
        "port": 1000 + index,
    }
    data.update(overrides)
    return data


def _publication(index: int, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "node_key": "web",
        "mode": "port_forward",
        "port": 8000 + index,
    }
    data.update(overrides)
    return data


def _configuration(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"name": "Lab", "nodes": [_node()]}
    data.update(overrides)
    return data


def _message(configuration: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as caught:
        EnvironmentCreate.model_validate(configuration)
    message = publish_validation_message(caught.value, configuration)
    # 不論哪一種錯，都不能把 pydantic 的原文帶出去
    assert "validation error" not in message
    assert "[type=" not in message
    return message


def test_blank_environment_name() -> None:
    assert _message(_configuration(name="")) == tr("course_env.publish_name_required")


def test_environment_name_too_long() -> None:
    assert _message(_configuration(name="x" * 256)) == tr(
        "course_env.publish_name_too_long", max=255
    )


def test_description_too_long() -> None:
    assert _message(_configuration(description="x" * 2001)) == tr(
        "course_env.publish_description_too_long", max=2000
    )


@pytest.mark.parametrize(
    "configuration", [{"name": "Lab"}, {"name": "Lab", "nodes": []}]
)
def test_no_machines(configuration: dict[str, Any]) -> None:
    assert _message(configuration) == tr("course_env.publish_no_machines")


def test_too_many_machines() -> None:
    nodes = [_node(node_key=f"n{index}") for index in range(4)]
    assert _message(_configuration(nodes=nodes)) == tr(
        "course_env.publish_too_many_machines", max=3
    )


def test_too_many_connections() -> None:
    edges = [_edge(index) for index in range(7)]
    assert _message(_configuration(edges=edges)) == tr(
        "course_env.publish_too_many_edges", max=6
    )


def test_too_many_published_services() -> None:
    publications = [_publication(index) for index in range(7)]
    assert _message(_configuration(publications=publications)) == tr(
        "course_env.publish_too_many_publications", max=6
    )


def test_unnamed_machine_is_identified_by_position() -> None:
    nodes = [_node(), _node(node_key="db", name="")]
    assert _message(_configuration(nodes=nodes)) == tr(
        "course_env.publish_machine_field_blank",
        machine=tr("course_env.publish_machine_numbered", index=2),
        field=tr("course_env.field_name"),
    )


def test_machine_without_role_is_identified_by_name() -> None:
    assert _message(_configuration(nodes=[_node(role="")])) == tr(
        "course_env.publish_machine_field_blank",
        machine=tr("course_env.publish_machine_named", name="Web"),
        field=tr("course_env.field_role"),
    )


def test_machine_role_too_long() -> None:
    assert _message(_configuration(nodes=[_node(role="r" * 121)])) == tr(
        "course_env.publish_machine_field_too_long",
        machine=tr("course_env.publish_machine_named", name="Web"),
        field=tr("course_env.field_role"),
        max=120,
    )


def test_machine_spec_out_of_range() -> None:
    assert _message(_configuration(nodes=[_node(cpu=0)])) == tr(
        "course_env.publish_machine_field_invalid",
        machine=tr("course_env.publish_machine_named", name="Web"),
        field=tr("course_env.field_cpu"),
    )


def test_machine_field_without_a_label_uses_the_generic_one() -> None:
    assert _message(_configuration(nodes=[_node(resource_type="bare-metal")])) == tr(
        "course_env.publish_machine_field_invalid",
        machine=tr("course_env.publish_machine_named", name="Web"),
        field=tr("course_env.field_setting"),
    )


def test_machine_validator_message_names_the_machine() -> None:
    message = _message(_configuration(nodes=[_node(source_template_id=None)]))
    assert message == tr(
        "course_env.publish_machine_detail",
        machine=tr("course_env.publish_machine_named", name="Web"),
        detail=tr("course_env.node_template_required"),
    )


def test_machine_that_is_not_an_object() -> None:
    assert _message(_configuration(nodes=["oops"])) == tr(
        "course_env.publish_machine_field_invalid",
        machine=tr("course_env.publish_machine_numbered", index=1),
        field=tr("course_env.field_setting"),
    )


def test_connection_validator_message_is_passed_through() -> None:
    edges = [_edge(0, target_node_key="web")]
    assert _message(_configuration(edges=edges)) == tr("course_env.edge_same_node")


def test_invalid_connection_is_identified_by_position() -> None:
    edges = [_edge(0), _edge(1, port=70000)]
    assert _message(_configuration(edges=edges)) == tr(
        "course_env.publish_edge_invalid", index=2
    )


def test_invalid_published_service_is_identified_by_position() -> None:
    publications = [_publication(0, port=0)]
    assert _message(_configuration(publications=publications)) == tr(
        "course_env.publish_publication_invalid", index=1
    )


def test_anything_else_falls_back_to_a_generic_sentence() -> None:
    assert _message(_configuration(usage_scope="nowhere")) == tr(
        "course_env.publish_configuration_invalid"
    )


@pytest.mark.parametrize("lang", ["zh-TW", "en", "ja"])
def test_every_language_has_the_publish_messages(lang: str) -> None:
    keys = [
        "course_env.publish_name_required",
        "course_env.publish_name_too_long",
        "course_env.publish_description_too_long",
        "course_env.publish_no_machines",
        "course_env.publish_too_many_machines",
        "course_env.publish_too_many_edges",
        "course_env.publish_too_many_publications",
        "course_env.publish_machine_named",
        "course_env.publish_machine_numbered",
        "course_env.publish_machine_field_blank",
        "course_env.publish_machine_field_too_long",
        "course_env.publish_machine_field_invalid",
        "course_env.publish_machine_detail",
        "course_env.publish_edge_invalid",
        "course_env.publish_publication_invalid",
        "course_env.publish_configuration_invalid",
        "course_env.field_name",
        "course_env.field_role",
        "course_env.field_cpu",
        "course_env.field_memory",
        "course_env.field_disk",
        "course_env.field_username",
        "course_env.field_source",
        "course_env.field_setting",
    ]
    # translate() 找不到會退回預設語系，所以直接讀該語系的檔案確認真的有翻
    path = Path(i18n.__file__).resolve().parent.parent / "locales" / lang
    catalog = json.loads((path / "routes_c.json").read_text(encoding="utf-8"))
    assert [key for key in keys if not catalog.get(key)] == []
