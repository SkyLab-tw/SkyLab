"""兩套分配帳本互相扣量（app.services.vm.pending_capacity）與它的使用端。

- 班級容量預檢要扣掉已核准、還沒建出來的申請單（快速練習、一般申請）。
- 申請單選點要扣掉班級已預留、還沒建出來的機器。
- 快速練習照整組預檢算好的落點建，不讓第一台自己挑叢集。
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.domain.placement.models import WorkingStoragePool
from app.domain.placement.schemas import NodeCapacity
from app.models import (
    ClassCapacityReservation,
    TeachingClassMachineNode,
    VMProvisioningStatus,
    VMRequest,
    VMRequestStatus,
)
from app.services import quick_practice
from app.services.teaching import class_capacity_service
from app.services.vm import pending_capacity, placement_service, placement_support
from app.services.vm.pending_capacity import PendingMachine

GIB = 1024**3
MIB = 1024**2
NOW = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _request(**overrides) -> VMRequest:
    defaults = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        reason="ledger",
        resource_type="lxc",
        hostname="ledger",
        cores=2,
        memory=2048,
        rootfs_size=8,
        password="encrypted",
        storage="local-lvm",
        environment_type="Test",
        ostemplate="local:vztmpl/debian.tar.zst",
        status=VMRequestStatus.approved,
        provisioning_status=VMProvisioningStatus.idle,
        assigned_node="pve1",
        start_at=NOW,
        end_at=NOW + timedelta(hours=2),
        created_at=NOW - timedelta(days=1),
    )
    defaults.update(overrides)
    return VMRequest(**defaults)


def _capacity(name: str, *, cores: float = 16.0, memory_gb: int = 32) -> NodeCapacity:
    return NodeCapacity(
        node=name,
        status="online",
        running_resources=0,
        guest_soft_limit=100,
        total_cpu_cores=cores,
        allocatable_cpu_cores=cores,
        total_memory_bytes=memory_gb * GIB,
        allocatable_memory_bytes=memory_gb * GIB,
        total_disk_bytes=1024 * GIB,
        allocatable_disk_bytes=1024 * GIB,
    )


# ---------------------------------------------------------------- ledger


def test_unbuilt_requests_only_count_approved_machines_still_to_build(session):
    counted = _request(hostname="queued", cores=3, memory=4096, rootfs_size=12)
    cloning = _request(
        hostname="cloning",
        provisioning_status=VMProvisioningStatus.running,
        assigned_node=None,
        desired_node="pve2",
    )
    no_end = _request(hostname="forever", end_at=None, assigned_node="pve3")
    ignored = [
        _request(hostname="built", vmid=101),
        _request(hostname="failed", provisioning_status=VMProvisioningStatus.failed),
        _request(hostname="pending", status=VMRequestStatus.pending),
        _request(hostname="cancelled", status=VMRequestStatus.cancelled),
        _request(hostname="expired", end_at=NOW - timedelta(minutes=1)),
        _request(hostname="unplaced", assigned_node=None),
    ]
    session.add_all([counted, cloning, no_end, *ignored])
    session.commit()

    machines = pending_capacity.unbuilt_request_machines(session, now=NOW)

    by_node = {machine.node: machine for machine in machines}
    assert set(by_node) == {"pve1", "pve2", "pve3"}
    assert by_node["pve1"] == PendingMachine(
        node="pve1",
        cpu_cores=3.0,
        memory_bytes=4096 * MIB,
        disk_gb=12,
        resource_type="lxc",
    )


def test_class_reservations_can_exclude_one_class(session):
    mine, other = uuid.uuid4(), uuid.uuid4()
    for class_id in (mine, other):
        spec = TeachingClassMachineNode(
            id=uuid.uuid4(),
            class_id=class_id,
            node_key="lab",
            source_type="custom",
            name="lab",
            role="target",
            resource_type="vm",
            cpu=2,
            memory_mb=1024,
            disk_gb=20,
            network="lab-net",
        )
        session.add(spec)
        session.add(
            ClassCapacityReservation(
                class_id=class_id,
                course_version_id=uuid.uuid4(),
                student_count=1,
                machine_count=1,
                cpu_cores=2,
                memory_mb=1024,
                disk_gb=20,
                ip_count=1,
                network_count=1,
                placement_plan={},
                student_placements={str(spec.id): {str(uuid.uuid4()): f"n-{class_id}"}},
            )
        )
    session.commit()

    machines = pending_capacity.class_reservation_machines(
        session, exclude_class_id=mine
    )
    assert [machine.node for machine in machines] == [f"n-{other}"]
    assert machines[0].disk_gb == 20 and machines[0].resource_type == "vm"


def test_legacy_reservation_counts_cpu_and_ram_without_disk(session):
    session.add(
        ClassCapacityReservation(
            class_id=uuid.uuid4(),
            course_version_id=uuid.uuid4(),
            student_count=1,
            machine_count=1,
            cpu_cores=4,
            memory_mb=1,
            disk_gb=1,
            ip_count=1,
            network_count=1,
            placement_plan={"a1": {"cpu_cores": 4, "memory_bytes": 2 * GIB}},
            student_placements={},
        )
    )
    session.commit()
    [machine] = pending_capacity.class_reservation_machines(session)
    assert (machine.node, machine.cpu_cores, machine.memory_bytes, machine.disk_gb) == (
        "a1",
        4.0,
        2 * GIB,
        0,
    )


def test_subtract_from_capacities_clamps_and_clears_candidate():
    capacities = [_capacity("pve1", cores=4, memory_gb=4), _capacity("pve2")]
    pending_capacity.subtract_from_capacities(
        capacities,
        [
            PendingMachine("pve1", 3.0, 2 * GIB, 0, "vm"),
            PendingMachine("pve1", 3.0, 3 * GIB, 0, "vm"),
            PendingMachine("unknown", 1.0, GIB, 0, "vm"),
        ],
    )
    assert capacities[0].allocatable_cpu_cores == 0.0
    assert capacities[0].allocatable_memory_bytes == 0
    assert capacities[0].candidate is False
    assert capacities[1].allocatable_cpu_cores == 16.0


def test_lock_allocation_is_a_noop_without_postgres(session):
    pending_capacity.lock_allocation(session)
    pending_capacity.lock_allocation(session)


# ------------------------------------------------- class capacity precheck


def test_class_precheck_counts_queued_quick_practice_machines(session, monkeypatch):
    """快速練習已核准、還在排隊 clone 的機器不能被當成空位分給整班。"""
    # 不設到期時間：服務端以實際時間判斷是否到期
    session.add(_request(assigned_node="a1", cores=1, memory=7 * 1024, end_at=None))
    session.commit()
    machine = TeachingClassMachineNode(
        id=uuid.uuid4(),
        class_id=uuid.uuid4(),
        node_key="lab",
        source_type="custom",
        name="lab",
        role="target",
        resource_type="lxc",
        cpu=1,
        memory_mb=2048,
        disk_gb=8,
        network="lab-net",
    )
    monkeypatch.setattr(
        class_capacity_service,
        "class_eligibility",
        lambda _s, *, nodes: ({machine.id: {"a1"}}, {1}, []),
    )
    monkeypatch.setattr(
        class_capacity_service.placement_support, "load_cluster_state", lambda: ([], [])
    )
    monkeypatch.setattr(
        class_capacity_service.placement_support,
        "build_live_node_capacities",
        lambda **_kw: [_capacity("a1", memory_gb=8)],
    )
    monkeypatch.setattr(
        class_capacity_service.placement_service,
        "get_overcommit_ratios",
        lambda _s: (1.0, 1.0),
    )
    monkeypatch.setattr(class_capacity_service, "get_connection_id_for_node", lambda _n: 1)

    _plan, _placements, issues = class_capacity_service._evaluate_cluster_capacity(
        session, nodes=[machine], student_ids=[uuid.uuid4()]
    )

    # 8 GB 被排隊中的 7 GB 佔走，只剩 1 GB，放不下 2 GB 的班級機器
    assert len(issues) == 1 and "RAM" in issues[0]


def test_student_added_after_reservation_follows_reserved_cluster(session):
    machine_id, class_id = uuid.uuid4(), uuid.uuid4()
    session.add(
        ClassCapacityReservation(
            class_id=class_id,
            course_version_id=uuid.uuid4(),
            student_count=3,
            machine_count=3,
            cpu_cores=1,
            memory_mb=1,
            disk_gb=1,
            ip_count=1,
            network_count=1,
            placement_plan={},
            student_placements={
                str(machine_id): {
                    str(uuid.uuid4()): "b2",
                    str(uuid.uuid4()): "b1",
                    str(uuid.uuid4()): "b1",
                }
            },
        )
    )
    session.commit()
    # 沒有逐位落點的學生：跟著同一台機器最多同學的節點，不另外挑叢集
    assert (
        class_capacity_service._reserved_placement(
            session, class_id=class_id, machine_node_id=machine_id, user_id=uuid.uuid4()
        )
        == "b1"
    )
    # 這台機器整個沒有落點（舊資料）時維持回 None
    assert (
        class_capacity_service._reserved_placement(
            session,
            class_id=class_id,
            machine_node_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
        )
        is None
    )


# -------------------------------------------------- quick-practice precheck


def test_quick_practice_precheck_returns_planned_nodes(monkeypatch):
    from tests.services.test_quick_practice_publication_retry import _capacity_nodes

    nodes = _capacity_nodes()
    user_id = uuid.uuid4()
    monkeypatch.setattr(quick_practice, "_node_disk_gb", lambda _s, _n: 8)
    monkeypatch.setattr(
        class_capacity_service,
        "_evaluate_cluster_capacity",
        lambda _s, *, nodes, student_ids, **_kw: (
            {},
            {node.id: {student_ids[0]: "pve3"} for node in nodes},
            [],
        ),
    )
    assert quick_practice._assert_cluster_capacity(
        None, nodes=nodes, user_id=user_id
    ) == {node.id: "pve3" for node in nodes}


# ------------------------------------------------------- request placement


@pytest.fixture
def placement_env(monkeypatch):
    state = {
        "nodes": [_capacity("pve1"), _capacity("pve2"), _capacity("other")],
        "class_machines": [],
        "pools": {},
        "managed": False,
    }
    monkeypatch.setattr(
        pending_capacity,
        "class_reservation_machines",
        lambda _s, **_kw: list(state["class_machines"]),
    )
    monkeypatch.setattr(placement_support, "load_cluster_state", lambda: ([], []))
    monkeypatch.setattr(
        placement_support,
        "build_live_node_capacities",
        lambda **_kw: [item.model_copy(deep=True) for item in state["nodes"]],
    )

    def _pool_state(*, session, node_names):
        # 和真的一樣每次給新的物件，試放不會留到下一次查詢
        return (
            {name: copy.deepcopy(state["pools"].get(name, [])) for name in node_names},
            state["managed"],
        )

    monkeypatch.setattr(placement_support, "build_storage_pool_state", _pool_state)
    policy = placement_service.placement_policy
    monkeypatch.setattr(policy, "get_overcommit_ratios", lambda _s: (1.0, 1.0))
    monkeypatch.setattr(policy, "get_memory_overcommit_ratio", lambda _s: 1.0)
    monkeypatch.setattr(policy, "get_placement_tuning", lambda *, session: _tuning())
    # pve1 優先：沒有其他條件時策略會選它
    monkeypatch.setattr(
        policy, "get_node_priorities", lambda _s: {"pve1": 1, "pve2": 2, "other": 3}
    )
    monkeypatch.setattr(
        policy, "get_placement_strategy", lambda _s: "priority_dominant_share"
    )
    monkeypatch.setattr(
        placement_service.vm_request_repo,
        "get_approved_vm_requests_overlapping_window",
        lambda **_kw: [],
    )
    monkeypatch.setattr(
        placement_support, "allowed_template_nodes_for_request", lambda _r: None
    )
    monkeypatch.setattr(
        placement_support, "allowed_affinity_nodes_for_request", lambda **_kw: None
    )
    monkeypatch.setattr(placement_support, "template_source_node", lambda _r: None)
    monkeypatch.setattr(
        placement_support,
        "connection_nodes_of",
        lambda node: {"pve1", "pve2"} if node in {"pve1", "pve2"} else {node},
    )
    return state


def _tuning():
    from app.domain.placement.models import PlacementTuning

    return PlacementTuning(
        reassignment_cost=0.15,
        peak_cpu_margin=1.1,
        peak_memory_margin=1.05,
        loadavg_warn_per_core=0.8,
        loadavg_max_per_core=1.5,
        loadavg_penalty_weight=0.9,
        disk_contention_warn_share=0.7,
        disk_contention_high_share=0.9,
        disk_penalty_weight=0.75,
    )


def _pool(name: str, *, avail_gb: float) -> WorkingStoragePool:
    return WorkingStoragePool(
        storage=name,
        total_gb=avail_gb,
        avail_gb=avail_gb,
        active=True,
        enabled=True,
        can_vm=True,
        can_lxc=True,
        is_shared=False,
        speed_tier="ssd",
        user_priority=5,
    )


def test_request_placement_skips_capacity_reserved_by_a_class(placement_env):
    placement_env["nodes"] = [_capacity("pve1", cores=4), _capacity("pve2", cores=4)]
    # 班級在 pve1 預留了 3 核還沒建：pve1 只剩 1 核，放不下 2 核的申請
    placement_env["class_machines"] = [PendingMachine("pve1", 3.0, GIB, 0, "lxc")]

    selection = placement_service.select_reserved_target_node(
        session=None, db_request=_request()
    )

    assert selection.node == "pve2"


def test_request_placement_skips_storage_reserved_by_a_class(placement_env):
    placement_env["managed"] = True
    placement_env["pools"] = {
        "pve1": [_pool("local-lvm", avail_gb=10)],
        "pve2": [_pool("local-lvm", avail_gb=10)],
    }
    # 班級在 pve1 的儲存區預留了 8 GB：剩 2 GB，放不下 8 GB 的申請
    placement_env["class_machines"] = [PendingMachine("pve1", 0.0, 0, 8, "lxc")]

    selection = placement_service.select_reserved_target_node(
        session=None, db_request=_request()
    )

    assert selection.node == "pve2"


def test_preferred_node_wins_over_strategy(placement_env):
    selection = placement_service.select_reserved_target_node(
        session=None, db_request=_request(), preferred_node="pve2"
    )
    assert selection.node == "pve2"


def test_preferred_node_falls_back_inside_its_cluster_only(placement_env):
    # 預檢選的 pve2 剛好滿了：退回同叢集的 pve1，不能跑去別的叢集
    placement_env["nodes"] = [
        _capacity("pve1"),
        _capacity("pve2", cores=1),
        _capacity("other"),
    ]
    selection = placement_service.select_reserved_target_node(
        session=None, db_request=_request(), preferred_node="pve2"
    )
    assert selection.node == "pve1"

    placement_env["nodes"] = [
        _capacity("pve1", cores=1),
        _capacity("pve2", cores=1),
        _capacity("other"),
    ]
    selection = placement_service.select_reserved_target_node(
        session=None, db_request=_request(), preferred_node="pve2"
    )
    # 整個叢集都放不下就明確失敗，不建到 other
    assert selection.node is None


# ------------------------------------------------------------ time windows


def test_unbuilt_requests_outside_the_window_do_not_block(session):
    """下週才開始的一般申請，不能擋掉現在要開、兩小時後到期的練習。"""
    soon = _request(hostname="soon", start_at=NOW + timedelta(hours=1))
    next_week = _request(
        hostname="next-week",
        start_at=NOW + timedelta(days=7),
        end_at=NOW + timedelta(days=8),
    )
    session.add_all([soon, next_week])
    session.commit()

    within_two_hours = pending_capacity.unbuilt_request_machines(
        session, now=NOW, until=NOW + timedelta(hours=2)
    )
    no_limit = pending_capacity.unbuilt_request_machines(session, now=NOW)

    assert len(within_two_hours) == 1
    assert len(no_limit) == 2


def _teaching_class(session, *, end_date, end_time):
    from datetime import time as dtime

    from app.models import TeachingClass

    item = TeachingClass(
        owner_id=uuid.uuid4(),
        name="Net",
        code="NET",
        term="115-1",
        start_date=end_date - timedelta(days=90),
        end_date=end_date,
        weekday=0,
        start_time=dtime(9, 0),
        end_time=end_time,
        timezone="Asia/Taipei",
    )
    session.add(item)
    session.flush()
    return item


def test_class_reservations_stop_counting_after_the_class_ends(session):
    from datetime import time as dtime

    item = _teaching_class(session, end_date=NOW.date(), end_time=dtime(12, 0))
    spec = TeachingClassMachineNode(
        id=uuid.uuid4(),
        class_id=item.id,
        node_key="lab",
        source_type="custom",
        name="lab",
        role="target",
        resource_type="lxc",
        cpu=2,
        memory_mb=1024,
        disk_gb=8,
        network="lab-net",
    )
    session.add(spec)
    session.add(
        ClassCapacityReservation(
            class_id=item.id,
            course_version_id=uuid.uuid4(),
            student_count=1,
            machine_count=1,
            cpu_cores=2,
            memory_mb=1024,
            disk_gb=8,
            ip_count=1,
            network_count=1,
            placement_plan={},
            student_placements={str(spec.id): {str(uuid.uuid4()): "pve1"}},
        )
    )
    session.commit()

    # 台北 12:00 = UTC 04:00 結束
    end = pending_capacity.class_end_at(item)
    assert end == datetime(NOW.year, NOW.month, NOW.day, 4, 0, tzinfo=UTC)
    before = pending_capacity.class_reservation_machines(
        session, active_at=end - timedelta(minutes=1)
    )
    after = pending_capacity.class_reservation_machines(session, active_at=end)
    assert len(before) == 1
    assert after == []
