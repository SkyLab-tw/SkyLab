"""Regression tests for the disk-resize guard in ``_apply_spec_changes``.

Proxmox resize takes a DELTA. The old code treated an unknown
``current_disk`` (None) as 0, turning the requested TOTAL size into a delta —
over-growing the disk to current + requested. Non-positive deltas (possible
via ``combined`` requests, which skip the growth validation at create time)
must also be rejected.

The disk that gets resized is the machine's main disk: the boot disk of a VM
(not necessarily ``scsi0`` — Windows guests without VirtIO drivers boot from
``sata0``／``ide0``) and ``rootfs`` of a container.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.exceptions import ProxmoxError
from app.infrastructure.proxmox import operations as ops
from app.services.vm import spec_change_service as scs


@pytest.fixture()
def fake_proxmox(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    calls = SimpleNamespace(
        resize=[],
        update_config=[],
        resource_type="qemu",
        config={"scsi0": "local-lvm:vm-150-disk-0,size=20G"},
    )

    # 開機磁碟的判斷用真的（ops.main_disk_key），只把它讀 PVE config 那一步換掉
    monkeypatch.setattr(ops, "get_config", lambda *_a, **_k: calls.config)
    fake = SimpleNamespace(
        find_resource=lambda vmid: {
            "node": "pve1",
            "type": calls.resource_type,
            "vmid": vmid,
        },
        update_config=lambda *a, **k: calls.update_config.append((a, k)),
        resize_disk=lambda *a, **k: calls.resize.append((a, k)),
        get_current_specs=lambda *a, **k: {},
        main_disk_key=ops.main_disk_key,
    )
    monkeypatch.setattr(scs, "proxmox_service", fake)
    return calls


def _request(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "vmid": 150,
        "requested_cpu": None,
        "requested_memory": None,
        "requested_disk": None,
        "current_cpu": 2,
        "current_memory": 2048,
        "current_disk": 20,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_unknown_current_disk_is_rejected(fake_proxmox: SimpleNamespace) -> None:
    req = _request(requested_disk=30, current_disk=None)

    with pytest.raises(ProxmoxError):
        scs._apply_spec_changes(db_request=req)

    assert fake_proxmox.resize == []  # nothing was applied


def test_non_positive_disk_delta_is_rejected(fake_proxmox: SimpleNamespace) -> None:
    req = _request(requested_disk=20, current_disk=20)

    with pytest.raises(ProxmoxError):
        scs._apply_spec_changes(db_request=req)

    assert fake_proxmox.resize == []


def test_valid_disk_growth_applies_delta(fake_proxmox: SimpleNamespace) -> None:
    req = _request(requested_disk=30, current_disk=20)

    changes = scs._apply_spec_changes(db_request=req)

    assert fake_proxmox.resize == [(("pve1", 150, "qemu", "scsi0", "+10G"), {})]
    assert any("Disk" in c for c in changes)


@pytest.mark.parametrize(
    ("config", "disk_key"),
    [
        (
            {
                "sata0": "local-lvm:vm-150-disk-0,size=20G",
                "ide2": "local:iso/virtio-win.iso,media=cdrom",
            },
            "sata0",
        ),
        ({"ide0": "local-lvm:vm-150-disk-0,size=20G"}, "ide0"),
        ({"virtio0": "local-lvm:vm-150-disk-0,size=20G"}, "virtio0"),
        (
            {
                "bootdisk": "virtio0",
                "scsi0": "local-lvm:vm-150-disk-1,size=100G",
                "virtio0": "local-lvm:vm-150-disk-0,size=20G",
            },
            "virtio0",
        ),
    ],
)
def test_disk_growth_targets_the_boot_disk(
    fake_proxmox: SimpleNamespace, config: dict[str, str], disk_key: str
) -> None:
    fake_proxmox.config = config
    req = _request(requested_disk=30, current_disk=20)

    scs._apply_spec_changes(db_request=req)

    assert fake_proxmox.resize == [(("pve1", 150, "qemu", disk_key, "+10G"), {})]


def test_vm_without_boot_disk_is_rejected_instead_of_guessing_scsi0(
    fake_proxmox: SimpleNamespace,
) -> None:
    fake_proxmox.config = {"cores": 2, "net0": "virtio=AA:BB:CC:DD:EE:FF"}
    req = _request(requested_disk=30, current_disk=20)

    with pytest.raises(ProxmoxError):
        scs._apply_spec_changes(db_request=req)

    assert fake_proxmox.resize == []


def test_container_disk_growth_targets_rootfs(fake_proxmox: SimpleNamespace) -> None:
    fake_proxmox.resource_type = "lxc"
    fake_proxmox.config = {"rootfs": "local-lvm:subvol-150-disk-0,size=20G"}
    req = _request(requested_disk=30, current_disk=20)

    scs._apply_spec_changes(db_request=req)

    assert fake_proxmox.resize == [(("pve1", 150, "lxc", "rootfs", "+10G"), {})]
