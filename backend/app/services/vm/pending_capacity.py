"""已預留、還沒建出來的機器：兩套分配系統要互相扣掉的量。

平台上的容量分配有三本帳：

- 申請單（``VMRequest``）：一般申請與快速練習，核准時就定好 ``assigned_node``，
  之後才由 worker clone。
- 班級容量預留（``ClassCapacityReservation``）：整班送出時就定好每位學生每台
  機器的落點，管理員審核通過後才由批次建機照落點建。
- 規格調整（``SpecChangeRequest``）：核准後由申請人自己挑時間套用，機器已經
  在 PVE 上，但增加的 CPU／RAM／磁碟要等套用才會寫進去。

機器建出來（規格套用）之後，都會出現在 PVE 的已分配量裡
（``apply_committed_allocations``）；在那之前 PVE 上看不到，只能從對方的帳本讀。
少了這一步，每一邊都會把別人已經核准的容量當成空的再分出去，等到真正建機
或套用才撞上放不下。

各自帳本內部的量仍由原本的流程處理：申請單看重疊時段的已核准申請，班級
預檢看其他班的預留（也是這裡的 ``class_reservation_machines``）。

``lock_allocation`` 讓「讀帳本 → 決定落點 → 寫回帳本」這一段在整個平台上
一次只有一個交易在做，兩個同時進來的分配才不會都以為容量還在。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlmodel import Session, col, select

from app.domain.placement import storage as placement_storage
from app.domain.placement.models import PlacementTuning, WorkingStoragePool
from app.domain.placement.schemas import NodeCapacity
from app.models import (
    ClassCapacityReservation,
    SpecChangeRequest,
    SpecChangeRequestStatus,
    SpecChangeType,
    TeachingClass,
    TeachingClassMachineNode,
    TeachingClassStudent,
    TeachingClassStudentMachine,
    VMProvisioningStatus,
    VMRequest,
    VMRequestStatus,
    VMTemplate,
)
from app.services.vm import placement_support

MIB = 1024**2
GIB = 1024**3

#: 容量分配鎖的 key（pg_advisory_xact_lock 只吃 bigint；任意固定值即可）
_ALLOCATION_LOCK_KEY = 0x5C1A_B0C0_0001


@dataclass(frozen=True)
class PendingMachine:
    """一台已經定好落點、還沒建出來的機器。"""

    node: str
    cpu_cores: float
    memory_bytes: int
    #: 0 代表不試放儲存區（只有逐節點加總、沒有逐台規格的舊預留）
    disk_gb: int
    resource_type: str
    #: 平台範本的母機節點：落在別的節點時只能放共享儲存；None = 不限
    template_node: str | None = None


def lock_allocation(session: Session) -> None:
    """取得平台層級的容量分配鎖，交易結束（commit／rollback）時自動釋放。

    必須在交易裡任何 ``FOR UPDATE`` 之前呼叫：核准路徑之後會鎖重疊時段的申請單，
    先拿列鎖再等這把鎖，就會和「先拿這把鎖、再鎖同一批申請單」的交易互相等待。
    同一個交易重複呼叫沒有副作用。非 PostgreSQL（單元測試的 SQLite）沒有
    advisory lock，直接略過。
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _ALLOCATION_LOCK_KEY},
    )


def _json_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    try:
        data = json.loads(value or "{}")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def class_end_at(teaching_class: TeachingClass) -> datetime:
    """班級機器佔著容量到什麼時候（UTC）。

    與排程器判斷班級到期（``recurrence_scheduler._class_expired``）同一個時間點：
    到了就封存、放掉預留、回收機器。時區無效時退回 UTC，寧可早一點也不讓
    整個判斷失敗。
    """
    try:
        tz = ZoneInfo(teaching_class.timezone or "UTC")
    except (KeyError, ValueError, OSError):
        tz = ZoneInfo("UTC")
    return datetime.combine(
        teaching_class.end_date, teaching_class.end_time, tzinfo=tz
    ).astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _machine_template_node(
    session: Session,
    machine_node: TeachingClassMachineNode,
    cache: dict[uuid.UUID | None, str | None],
) -> str | None:
    if machine_node.source_type != "template":
        return None
    key = machine_node.source_template_id
    if key not in cache:
        template = session.get(VMTemplate, key) if key else None
        cache[key] = template.node if template else None
    return cache[key]


def class_reservation_machines(
    session: Session,
    *,
    exclude_class_id: uuid.UUID | None = None,
    active_at: datetime | None = None,
) -> list[PendingMachine]:
    """各班已預留、但機器還沒建出來的量。

    預留在班級存續期間都是 reserved；這段期間已經建好的機器會出現在 PVE 上、
    由已分配量算進去，這裡只列還沒建的，避免同一台被算兩次。沒有逐位落點的
    舊預留只有逐節點加總，轉成每個節點一筆、磁碟記 0。

    ``active_at``：只列到這個時間點還沒結束的班級。排在班級結束之後才開始的
    申請不會和它搶容量（到期就封存回收）。查不到班級的預留一律算進去。
    """
    pending: list[PendingMachine] = []
    template_nodes: dict[uuid.UUID | None, str | None] = {}
    statement = select(ClassCapacityReservation).where(
        ClassCapacityReservation.status == "reserved"
    )
    if exclude_class_id is not None:
        statement = statement.where(
            ClassCapacityReservation.class_id != exclude_class_id
        )
    for reservation in session.exec(statement).all():
        if active_at is not None:
            teaching_class = session.get(TeachingClass, reservation.class_id)
            if teaching_class is not None and class_end_at(
                teaching_class
            ) <= _as_utc(active_at):
                continue
        placements = _json_dict(reservation.student_placements)
        if not placements:
            for node_name, values in _json_dict(reservation.placement_plan).items():
                if not isinstance(values, dict):
                    continue
                pending.append(
                    PendingMachine(
                        node=str(node_name),
                        cpu_cores=float(values.get("cpu_cores") or 0),
                        memory_bytes=int(values.get("memory_bytes") or 0),
                        disk_gb=0,
                        resource_type="vm",
                    )
                )
            continue
        specs = {
            str(row.id): row
            for row in session.exec(
                select(TeachingClassMachineNode).where(
                    TeachingClassMachineNode.class_id == reservation.class_id
                )
            ).all()
        }
        built = {
            (str(machine.machine_node_id), str(student.user_id))
            for machine, student in session.exec(
                select(TeachingClassStudentMachine, TeachingClassStudent)
                .join(
                    TeachingClassStudent,
                    col(TeachingClassStudentMachine.class_student_id)
                    == col(TeachingClassStudent.id),
                )
                .where(TeachingClassStudent.class_id == reservation.class_id)
            ).all()
            if machine.vmid is not None
        }
        for machine_node_id, per_student in placements.items():
            spec = specs.get(str(machine_node_id))
            if spec is None or not isinstance(per_student, dict):
                continue
            for user_id, node_name in per_student.items():
                if not node_name or (str(machine_node_id), str(user_id)) in built:
                    continue
                pending.append(
                    PendingMachine(
                        node=str(node_name),
                        cpu_cores=float(spec.cpu),
                        memory_bytes=int(spec.memory_mb) * MIB,
                        disk_gb=int(spec.disk_gb),
                        resource_type=(
                            "lxc" if spec.resource_type.lower() == "lxc" else "vm"
                        ),
                        template_node=_machine_template_node(
                            session, spec, template_nodes
                        ),
                    )
                )
    return pending


def unbuilt_request_machines(
    session: Session, *, now: datetime, until: datetime | None = None
) -> list[PendingMachine]:
    """已核准、已選好節點、還沒建出來，而且時段和 [now, until) 重疊的申請單。

    ``until`` 是呼叫端需要容量到什麼時候：班級是班級結束、快速練習是這組
    的到期時間；None 代表沒有盡頭（任何還沒到期的申請都算）。下個月才開始
    的排程申請不會和兩小時的練習重疊，不能拿來擋人。
    正在 clone 的也算（它的 vmid 要 clone 完才寫回）；建失敗的不算。
    """
    statement = select(VMRequest).where(
        VMRequest.status == VMRequestStatus.approved,
        col(VMRequest.vmid).is_(None),
        VMRequest.provisioning_status != VMProvisioningStatus.failed,
        sa.or_(col(VMRequest.end_at).is_(None), col(VMRequest.end_at) > now),
    )
    if until is not None:
        statement = statement.where(
            sa.or_(
                col(VMRequest.start_at).is_(None), col(VMRequest.start_at) < until
            )
        )
    rows = session.exec(statement).all()
    pending: list[PendingMachine] = []
    for request in rows:
        node = str(
            request.actual_node or request.assigned_node or request.desired_node or ""
        ).strip()
        if not node:
            continue
        cpu_cores, memory_bytes, _disk_bytes = placement_support.request_capacity_tuple(
            request
        )
        pending.append(
            PendingMachine(
                node=node,
                cpu_cores=cpu_cores,
                memory_bytes=memory_bytes,
                disk_gb=placement_support.request_disk_gb(
                    resource_type=request.resource_type,
                    disk_size=request.disk_size,
                    rootfs_size=request.rootfs_size,
                ),
                resource_type="lxc" if request.resource_type == "lxc" else "vm",
            )
        )
    return pending


def _growth(requested: int | None, current: int | None) -> int:
    """與配額的 ``quota_service.spec_change_delta`` 同一套：調小或沒動算 0。"""
    if requested is None:
        return 0
    return max(0, int(requested) - int(current or 0))


def approved_spec_change_machines(
    session: Session, *, exclude_request_id: uuid.UUID | None = None
) -> list[PendingMachine]:
    """已核准、還沒套用的規格調整會多佔的量（只算增加的部分）。

    機器本身已經在 PVE 的已分配量裡，這裡只列「核准了、但還沒寫進機器」的
    增量。套用成功（applied_at 有值）後 PVE 已是新規格，不再列入；套用失敗
    仍保留核准，申請人可以重試，所以照樣列入。所在節點從 PVE 快照查，
    查不到（機器已不在）就略過。磁碟不知道確切在哪個儲存區，``preplace_storage``
    會在節點上挑一個放得下的先扣，屬保守估計。
    """
    statement = select(SpecChangeRequest).where(
        SpecChangeRequest.status == SpecChangeRequestStatus.approved,
        col(SpecChangeRequest.applied_at).is_(None),
        col(SpecChangeRequest.resource_vmid).is_not(None),
        SpecChangeRequest.change_type != SpecChangeType.expiry,
    )
    if exclude_request_id is not None:
        statement = statement.where(SpecChangeRequest.id != exclude_request_id)
    rows = session.exec(statement).all()
    if not rows:
        return []
    _nodes, resources = placement_support.load_cluster_state()
    guests = {int(guest.vmid): guest for guest in resources}
    pending: list[PendingMachine] = []
    for request in rows:
        guest = guests.get(int(request.vmid))
        if guest is None:
            continue
        cores = _growth(request.requested_cpu, request.current_cpu)
        memory_mb = _growth(request.requested_memory, request.current_memory)
        disk_gb = _growth(request.requested_disk, request.current_disk)
        if not (cores or memory_mb or disk_gb):
            continue
        pending.append(
            PendingMachine(
                node=str(guest.node),
                cpu_cores=float(cores),
                memory_bytes=memory_mb * MIB,
                disk_gb=disk_gb,
                resource_type="lxc" if guest.resource_type == "lxc" else "vm",
            )
        )
    return pending


def request_external_load(
    session: Session, *, active_at: datetime
) -> list[PendingMachine]:
    """申請單選點要另外扣的量：申請單帳本以外、PVE 上還看不到的部分。

    班級已預留未建（到 ``active_at`` 還沒結束的班級），加上已核准未套用的
    規格調整增量。其他已核准的申請單由選點自己依重疊時段扣。
    """
    return [
        *class_reservation_machines(session, active_at=active_at),
        *approved_spec_change_machines(session),
    ]


def subtract_from_capacities(
    capacities: Iterable[NodeCapacity], machines: Iterable[PendingMachine]
) -> None:
    """把待建機器的 CPU／RAM 從所在節點的可用量扣掉（就地修改）。

    磁碟不在這裡扣：節點層的 disk 是 PVE 主機系統碟，磁碟由 ``preplace_storage``
    依儲存區處理。
    """
    by_node = {item.node: item for item in capacities}
    for machine in machines:
        capacity = by_node.get(machine.node)
        if capacity is None:
            continue
        capacity.allocatable_cpu_cores = max(
            0.0, float(capacity.allocatable_cpu_cores) - machine.cpu_cores
        )
        capacity.allocatable_memory_bytes = max(
            0, int(capacity.allocatable_memory_bytes) - machine.memory_bytes
        )
        capacity.candidate = (
            capacity.candidate
            and capacity.allocatable_cpu_cores > 0
            and capacity.allocatable_memory_bytes > 0
        )


def place_on_storage(
    pools_by_node: dict[str, list[WorkingStoragePool]],
    *,
    node: str,
    disk_gb: int,
    resource_type: str,
    template_node: str | None,
    disk_overcommit_ratio: float,
    tuning: PlacementTuning,
) -> bool:
    """照 placement 的規則在節點上挑一個儲存區並扣掉空間；放不下回 False。"""
    pools = pools_by_node.get(node, [])
    if template_node is not None and node != template_node:
        # 範本 clone 到其他節點只能放共享儲存
        pools = [pool for pool in pools if pool.is_shared]
    selection = placement_storage.select_best_storage_for_request(
        storage_pools=pools,
        resource_type=resource_type,  # type: ignore[arg-type]
        disk_gb=int(disk_gb),
        disk_overcommit_ratio=disk_overcommit_ratio,
        tuning=tuning,
    )
    if selection is None:
        return False
    placement_storage.reserve_storage_pool(
        selection=selection,
        disk_gb=int(disk_gb),
        disk_overcommit_ratio=disk_overcommit_ratio,
    )
    return True


def storage_room_gb(
    session: Session,
    *,
    node: str,
    storage: str,
    machines: Iterable[PendingMachine],
    disk_overcommit_ratio: float,
    tuning: PlacementTuning,
) -> float | None:
    """節點上指定儲存區先扣掉待建機器後，還能放多少 GB。

    沒有受管儲存紀錄、或這個儲存區沒有納管時回 None（無從判斷，交給呼叫端
    放行，與 placement「沒有受管儲存池時不判斷磁碟」一致）。
    """
    with_disk = [machine for machine in machines if machine.disk_gb > 0]
    pools_by_node, has_managed_storage = placement_support.build_storage_pool_state(
        session=session,
        node_names=sorted({node} | {machine.node for machine in with_disk}),
    )
    if not has_managed_storage:
        return None
    pool = next(
        (item for item in pools_by_node.get(node, []) if item.storage == storage),
        None,
    )
    if pool is None:
        return None
    preplace_storage(
        pools_by_node,
        with_disk,
        disk_overcommit_ratio=disk_overcommit_ratio,
        tuning=tuning,
    )
    return placement_storage.remaining_gb(pool, disk_overcommit_ratio)


def preplace_storage(
    pools_by_node: dict[str, list[WorkingStoragePool]],
    machines: Iterable[PendingMachine],
    *,
    disk_overcommit_ratio: float,
    tuning: PlacementTuning,
) -> None:
    """先把待建機器的磁碟放進儲存區，後面試放的才看得到剩下多少。

    別人放不下是別人的問題，這裡只是先把它的份占掉，所以結果不回報。
    """
    for machine in machines:
        if machine.disk_gb <= 0:
            continue
        place_on_storage(
            pools_by_node,
            node=machine.node,
            disk_gb=machine.disk_gb,
            resource_type=machine.resource_type,
            template_node=machine.template_node,
            disk_overcommit_ratio=disk_overcommit_ratio,
            tuning=tuning,
        )


__all__ = [
    "PendingMachine",
    "approved_spec_change_machines",
    "class_end_at",
    "class_reservation_machines",
    "lock_allocation",
    "place_on_storage",
    "preplace_storage",
    "request_external_load",
    "storage_room_gb",
    "subtract_from_capacities",
    "unbuilt_request_machines",
]
