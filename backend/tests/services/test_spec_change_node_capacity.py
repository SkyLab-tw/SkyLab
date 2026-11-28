"""規格調整核准／套用時檢查機器所在節點的容量（spec_change_service._check_node_capacity）。

機器不會搬家：調大的 CPU／RAM 落在它現在的節點、磁碟長在它現在的儲存區。
只看「增加的部分」，並先扣掉其他帳本還沒反映在 PVE 上的量（含其他已核准、
還沒套用的規格調整）。
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.domain.placement.models import PlacementTuning, WorkingStoragePool
from app.domain.placement.schemas import NodeCapacity, ResourceSnapshot
from app.exceptions import BadRequestError
from app.infrastructure.proxmox import operations as ops
from app.models import SpecChangeRequest, SpecChangeRequestStatus, SpecChangeType
from app.schemas import SpecChangeRequestReview
from app.services.vm import pending_capacity, placement_support
from app.services.vm import spec_change_service as svc
from tests.services.test_spec_change_service_coverage import (
    REASON,
    _reload,
    _resource,
    _user,
    _vmid,
)

GIB = 1024**3


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(svc, "_open_session", lambda: Session(engine))
    with Session(engine) as session:
        yield session


def _tuning() -> PlacementTuning:
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


def _capacity(name: str, *, cores: float, memory_gb: float) -> NodeCapacity:
    return NodeCapacity(
        node=name,
        status="online",
        total_cpu_cores=cores,
        allocatable_cpu_cores=cores,
        total_memory_bytes=int(memory_gb * GIB),
        allocatable_memory_bytes=int(memory_gb * GIB),
        total_disk_bytes=1024 * GIB,
        allocatable_disk_bytes=1024 * GIB,
    )


def _pool(storage: str, *, avail_gb: float) -> WorkingStoragePool:
    return WorkingStoragePool(
        storage=storage,
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


@pytest.fixture
def cluster(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """假的 PVE：一台 node-a，上面有測試要調整的機器。"""
    state: dict[str, Any] = {
        "capacity": _capacity("node-a", cores=4, memory_gb=8),
        "guests": [],
        "pools": {},
        "managed": False,
        "disk": "local-lvm:vm-1-disk-0,size=20G",
        "pve_calls": 0,
    }

    def load_cluster_state():
        state["pve_calls"] += 1
        if isinstance(state.get("error"), Exception):
            raise state["error"]
        return [], [ResourceSnapshot(**guest) for guest in state["guests"]]

    monkeypatch.setattr(placement_support, "load_cluster_state", load_cluster_state)
    monkeypatch.setattr(
        placement_support,
        "build_live_node_capacities",
        lambda **_kw: [state["capacity"].model_copy(deep=True)],
    )
    monkeypatch.setattr(
        placement_support,
        "build_storage_pool_state",
        lambda *, session, node_names: (
            # 每次給新的物件，和真的一樣：試放不會留到下一次查詢
            {name: copy.deepcopy(state["pools"].get(name, [])) for name in node_names},
            state["managed"],
        ),
    )
    policy = svc.placement_service.placement_policy
    monkeypatch.setattr(policy, "get_overcommit_ratios", lambda _s: (1.0, 1.0))
    monkeypatch.setattr(policy, "get_memory_overcommit_ratio", lambda _s: 1.0)
    monkeypatch.setattr(policy, "get_placement_tuning", lambda *, session: _tuning())
    monkeypatch.setattr(
        svc,
        "proxmox_service",
        SimpleNamespace(
            find_resource=lambda vmid: {"node": "node-a", "type": "qemu", "vmid": vmid},
            get_current_specs=lambda *_a, **_k: {"cpu": 2, "memory": 2048, "disk": 20},
            get_config=lambda *_a, **_k: (
                state.get("config") or {"scsi0": state["disk"]}
            ),
            main_disk=ops.main_disk,
        ),
    )
    return state


def _spec(
    session: Session,
    *,
    user,
    vmid: int,
    status: SpecChangeRequestStatus = SpecChangeRequestStatus.pending,
    **fields: Any,
) -> SpecChangeRequest:
    values: dict[str, Any] = {
        "vmid": vmid,
        "resource_vmid": vmid,
        "user_id": user.id,
        "change_type": SpecChangeType.combined,
        "reason": REASON,
        "current_cpu": 2,
        "current_memory": 2048,
        "current_disk": 20,
        "status": status,
        "created_at": datetime.now(timezone.utc),
    }
    values.update(fields)
    request = SpecChangeRequest(**values)
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def _approve(session: Session, request: SpecChangeRequest, reviewer) -> None:
    svc.review(
        session=session,
        request_id=request.id,
        review_data=SpecChangeRequestReview(
            status=SpecChangeRequestStatus.approved, review_comment=None
        ),
        reviewer=reviewer,
    )


@pytest.fixture
def no_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc.quota_service, "check_quota", lambda *_a, **_k: None)


# ---------------------------------------------------------------- review


def test_approval_blocked_when_node_cpu_cannot_take_the_increase(
    db: Session, cluster, no_quota
) -> None:
    user, admin = _user(db), _user(db, admin=True)
    vmid = _vmid()
    _resource(db, user=user, vmid=vmid)
    # 2 → 8 核：要再 6 核，節點只剩 4
    request = _spec(db, user=user, vmid=vmid, requested_cpu=8)

    with pytest.raises(BadRequestError) as exc:
        _approve(db, request, admin)

    assert "node-a" in exc.value.message and "CPU" in exc.value.message
    assert _reload(db, request.id).status == SpecChangeRequestStatus.pending


def test_approval_counts_other_approved_but_unapplied_changes(
    db: Session, cluster, no_quota
) -> None:
    """兩張單各自看都放得下，但第一張核准後還沒套用，第二張不能再用同一份空間。"""
    user, admin = _user(db), _user(db, admin=True)
    first_vmid, second_vmid = _vmid(), _vmid()
    for vmid in (first_vmid, second_vmid):
        _resource(db, user=user, vmid=vmid)
    cluster["guests"] = [
        {"vmid": first_vmid, "node": "node-a", "resource_type": "qemu"},
        {"vmid": second_vmid, "node": "node-a", "resource_type": "qemu"},
    ]
    first = _spec(db, user=user, vmid=first_vmid, requested_cpu=5)  # +3
    second = _spec(db, user=user, vmid=second_vmid, requested_cpu=5)  # +3

    _approve(db, first, admin)
    with pytest.raises(BadRequestError):
        _approve(db, second, admin)

    assert _reload(db, first.id).status == SpecChangeRequestStatus.approved
    assert _reload(db, second.id).status == SpecChangeRequestStatus.pending


def test_approval_blocked_when_ram_cannot_take_the_increase(
    db: Session, cluster, no_quota
) -> None:
    user, admin = _user(db), _user(db, admin=True)
    vmid = _vmid()
    _resource(db, user=user, vmid=vmid)
    # 2 GB → 12 GB：要再 10 GB，節點只剩 8 GB
    request = _spec(db, user=user, vmid=vmid, requested_memory=12 * 1024)

    with pytest.raises(BadRequestError) as exc:
        _approve(db, request, admin)

    assert "RAM" in exc.value.message and "10.0" in exc.value.message


def test_approval_checks_the_storage_the_disk_lives_on(
    db: Session, cluster, no_quota
) -> None:
    user, admin = _user(db), _user(db, admin=True)
    vmid = _vmid()
    _resource(db, user=user, vmid=vmid)
    cluster["managed"] = True
    # 另一個儲存區很空，但磁碟在 local-lvm，只能在那裡長
    cluster["pools"] = {
        "node-a": [_pool("local-lvm", avail_gb=5), _pool("ceph", avail_gb=500)]
    }
    request = _spec(db, user=user, vmid=vmid, requested_disk=40)  # +20 GB

    with pytest.raises(BadRequestError) as exc:
        _approve(db, request, admin)

    assert "local-lvm" in exc.value.message


def test_unmanaged_storage_does_not_block_disk_growth(
    db: Session, cluster, no_quota
) -> None:
    user, admin = _user(db), _user(db, admin=True)
    vmid = _vmid()
    _resource(db, user=user, vmid=vmid)
    cluster["managed"] = True
    cluster["pools"] = {"node-a": [_pool("ceph", avail_gb=1)]}  # local-lvm 沒納管
    request = _spec(db, user=user, vmid=vmid, requested_disk=40)

    _approve(db, request, admin)

    assert _reload(db, request.id).status == SpecChangeRequestStatus.approved


def test_shrinking_or_unchanged_specs_skip_the_capacity_lookup(
    db: Session, cluster, no_quota
) -> None:
    user, admin = _user(db), _user(db, admin=True)
    vmid = _vmid()
    _resource(db, user=user, vmid=vmid)
    cluster["error"] = RuntimeError("PVE down")
    request = _spec(db, user=user, vmid=vmid, requested_cpu=1)

    _approve(db, request, admin)

    assert _reload(db, request.id).status == SpecChangeRequestStatus.approved


def test_capacity_lookup_failure_blocks_approval(
    db: Session, cluster, no_quota
) -> None:
    user, admin = _user(db), _user(db, admin=True)
    vmid = _vmid()
    _resource(db, user=user, vmid=vmid)
    cluster["error"] = RuntimeError("PVE down")
    request = _spec(db, user=user, vmid=vmid, requested_cpu=3)

    with pytest.raises(BadRequestError) as exc:
        _approve(db, request, admin)

    assert exc.value.message == svc.t("spec_change.capacity_check_failed")


# ---------------------------------------------------------------- apply


def test_apply_rechecks_capacity_without_counting_itself(
    db: Session, cluster, no_quota, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user(db)
    vmid = _vmid()
    _resource(db, user=user, vmid=vmid)
    cluster["guests"] = [{"vmid": vmid, "node": "node-a", "resource_type": "qemu"}]
    # 已核准、還沒套用的 +2 核：自己在帳本裡，套用時不能把自己也算進去
    request = _spec(
        db,
        user=user,
        vmid=vmid,
        status=SpecChangeRequestStatus.approved,
        requested_cpu=4,
    )
    monkeypatch.setattr(svc.background_tasks, "is_active", lambda _tid: False)
    monkeypatch.setattr(svc.background_tasks, "submit_sync", lambda *_a, **_k: "task")

    svc.apply(session=db, request_id=request.id, user=user)
    assert _reload(db, request.id).apply_started_at is not None


def test_apply_blocked_when_node_filled_up_after_approval(
    db: Session, cluster, no_quota, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user(db)
    vmid = _vmid()
    _resource(db, user=user, vmid=vmid)
    request = _spec(
        db,
        user=user,
        vmid=vmid,
        status=SpecChangeRequestStatus.approved,
        requested_cpu=4,
    )
    cluster["capacity"] = _capacity("node-a", cores=1, memory_gb=8)
    monkeypatch.setattr(svc.background_tasks, "is_active", lambda _tid: False)

    with pytest.raises(BadRequestError):
        svc.apply(session=db, request_id=request.id, user=user)
    assert _reload(db, request.id).apply_started_at is None


# ---------------------------------------------------------------- ledger


def test_ledger_lists_only_approved_unapplied_growth(db: Session, cluster) -> None:
    user = _user(db)
    vmids = [_vmid() for _ in range(5)]
    cluster["guests"] = [
        {"vmid": vmid, "node": f"n{index}", "resource_type": "lxc"}
        for index, vmid in enumerate(vmids)
    ]
    approved = SpecChangeRequestStatus.approved
    counted = _spec(
        db,
        user=user,
        vmid=vmids[0],
        status=approved,
        requested_cpu=4,
        requested_memory=4096,
        requested_disk=30,
    )
    _spec(db, user=user, vmid=vmids[1], requested_cpu=4)  # 還沒核准
    _spec(
        db,
        user=user,
        vmid=vmids[2],
        status=approved,
        requested_cpu=4,
        applied_at=datetime.now(timezone.utc),
    )
    _spec(db, user=user, vmid=vmids[3], status=approved, requested_cpu=1)  # 調小
    _spec(
        db,
        user=user,
        vmid=vmids[4],
        status=approved,
        change_type=SpecChangeType.expiry,
        requested_cpu=None,
    )

    machines = pending_capacity.approved_spec_change_machines(db)

    assert machines == [
        pending_capacity.PendingMachine(
            node="n0",
            cpu_cores=2.0,
            memory_bytes=2048 * 1024**2,
            disk_gb=10,
            resource_type="lxc",
        )
    ]
    assert pending_capacity.approved_spec_change_machines(
        db, exclude_request_id=counted.id
    ) == []


def test_request_placement_also_counts_approved_spec_changes(
    db: Session, cluster
) -> None:
    user = _user(db)
    vmid = _vmid()
    cluster["guests"] = [{"vmid": vmid, "node": "node-a", "resource_type": "qemu"}]
    _spec(
        db,
        user=user,
        vmid=vmid,
        status=SpecChangeRequestStatus.approved,
        requested_cpu=5,
    )

    load = pending_capacity.request_external_load(
        db, active_at=datetime.now(timezone.utc)
    )

    assert [(item.node, item.cpu_cores) for item in load] == [("node-a", 3.0)]


def test_disk_storage_reads_the_main_disk(cluster) -> None:
    assert svc._disk_storage("node-a", 1, "qemu") == "local-lvm"
    cluster["disk"] = ""
    assert svc._disk_storage("node-a", 1, "qemu") is None


def test_disk_storage_follows_the_boot_disk_when_it_is_not_scsi0(cluster) -> None:
    # Windows 沒裝 VirtIO 驅動的機器：開機磁碟在 sata0，另掛驅動光碟
    cluster["config"] = {
        "sata0": "ceph-vm:vm-1-disk-0,size=60G",
        "ide2": "local:iso/virtio-win.iso,media=cdrom",
    }
    assert svc._disk_storage("node-a", 1, "qemu") == "ceph-vm"


def test_disk_storage_of_a_container_is_where_rootfs_lives(cluster) -> None:
    cluster["config"] = {"rootfs": "local-zfs:subvol-1-disk-0,size=8G"}
    assert svc._disk_storage("node-a", 1, "lxc") == "local-zfs"
