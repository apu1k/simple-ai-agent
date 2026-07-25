"""Opt-in destructive integration tests for a dedicated Hyper-V validation host."""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import pytest

from night_shifts.backends import (
    HyperVConfig,
    HyperVSandboxController,
    HyperVSerialTransport,
    SandboxWorkerBackend,
)
from night_shifts.models import NightShiftEvent, SandboxSpec, SandboxStatus
from night_shifts.protocol import WorkerOutcome, WorkerTask
from night_shifts.storage import SandboxStore

_ENABLE_VARIABLE = "NIGHT_SHIFT_HYPERV_INTEGRATION"

if os.environ.get(_ENABLE_VARIABLE) != "1":
    pytest.skip(
        f"real-host Hyper-V tests require {_ENABLE_VARIABLE}=1",
        allow_module_level=True,
    )
if sys.platform != "win32":
    pytest.skip("real-host Hyper-V tests require Windows", allow_module_level=True)


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        pytest.fail(f"{name} must be set when real-host Hyper-V tests are enabled")
    return value


def _positive_environment(name: str, default: str) -> float:
    value = float(os.environ.get(name, default))
    if value <= 0:
        pytest.fail(f"{name} must be positive")
    return value


@pytest.fixture
def host_config() -> HyperVConfig:
    base_image = Path(_required_environment("NIGHT_SHIFT_HYPERV_BASE_IMAGE"))
    workspace = Path(_required_environment("NIGHT_SHIFT_HYPERV_WORKSPACE"))
    if not base_image.is_absolute() or not workspace.is_absolute():
        pytest.fail("Hyper-V base-image and workspace paths must be absolute")
    return HyperVConfig(
        base_image=base_image,
        base_image_sha256=_required_environment("NIGHT_SHIFT_HYPERV_BASE_IMAGE_SHA256"),
        workspace_root=workspace,
        powershell_executable=os.environ.get(
            "NIGHT_SHIFT_HYPERV_POWERSHELL", "powershell.exe"
        ),
        command_timeout_seconds=_positive_environment(
            "NIGHT_SHIFT_HYPERV_COMMAND_TIMEOUT_SECONDS", "180"
        ),
    )


@pytest.fixture
def sandbox_spec() -> SandboxSpec:
    return SandboxSpec(
        cpu_count=int(os.environ.get("NIGHT_SHIFT_HYPERV_CPU_COUNT", "2")),
        memory_mb=int(os.environ.get("NIGHT_SHIFT_HYPERV_MEMORY_MB", "2048")),
        disk_gb=int(os.environ.get("NIGHT_SHIFT_HYPERV_DISK_GB", "20")),
        network_enabled=False,
    )


@pytest.fixture
def real_controller(tmp_path: Path, host_config: HyperVConfig):
    store = SandboxStore(tmp_path / "operations.sqlite3")
    controller = HyperVSandboxController(
        host_config,
        store,
        transport=HyperVSerialTransport(
            connect_timeout_seconds=_positive_environment(
                "NIGHT_SHIFT_HYPERV_SERIAL_TIMEOUT_SECONDS", "90"
            )
        ),
    )
    yield controller
    cleanup_errors = []
    for sandbox in store.list():
        if sandbox.status is SandboxStatus.DESTROYED:
            continue
        try:
            controller.destroy(sandbox)
        except Exception as exc:  # pragma: no cover - exercised only on a real host
            cleanup_errors.append(f"{sandbox.sandbox_id}: {exc}")
    if cleanup_errors:
        pytest.fail("real-host cleanup failed: " + "; ".join(cleanup_errors))


def _task(objective: str) -> WorkerTask:
    return WorkerTask(
        job_id=f"phase3-real-host-{uuid.uuid4().hex}",
        objective=objective,
        worker_profile="protocol-test-worker",
    )


def _assert_destroyed(controller: HyperVSandboxController) -> None:
    records = controller.store.list()
    assert records
    record = records[-1]
    assert record.status is SandboxStatus.DESTROYED
    assert not (controller.config.workspace_root / record.sandbox_id).exists()


def test_real_host_prerequisites(real_controller: HyperVSandboxController):
    real_controller.check_prerequisites()


def test_real_host_serial_round_trip_and_cleanup(
    real_controller: HyperVSandboxController,
    sandbox_spec: SandboxSpec,
):
    events: list[NightShiftEvent] = []
    backend = SandboxWorkerBackend(real_controller, spec=sandbox_spec, poll_interval=0.1)

    result = backend.run(
        _task("phase3-protocol-success"),
        timeout_seconds=_positive_environment("NIGHT_SHIFT_HYPERV_JOB_TIMEOUT_SECONDS", "180"),
        on_event=events.append,
    )

    assert result.outcome is WorkerOutcome.SUCCESS
    assert "protocol validation succeeded" in result.summary
    assert any(event.event_type == "protocol_test_echo" for event in events)
    _assert_destroyed(real_controller)


def test_real_host_cancellation_forces_cleanup_while_guest_is_blocked(
    real_controller: HyperVSandboxController,
    sandbox_spec: SandboxSpec,
):
    task_sent_at: list[float] = []

    def on_event(event: NightShiftEvent) -> None:
        if event.event_type == "sandbox_task_sent":
            task_sent_at.append(time.monotonic())

    def cancellation_requested() -> bool:
        return bool(task_sent_at) and time.monotonic() - task_sent_at[0] >= 1.0

    backend = SandboxWorkerBackend(real_controller, spec=sandbox_spec, poll_interval=0.1)
    result = backend.run(
        _task("phase3-protocol-sleep:600"),
        timeout_seconds=_positive_environment("NIGHT_SHIFT_HYPERV_JOB_TIMEOUT_SECONDS", "180"),
        cancellation_requested=cancellation_requested,
        on_event=on_event,
    )

    assert result.outcome is WorkerOutcome.CANCELLED
    _assert_destroyed(real_controller)


def test_real_host_timeout_forces_cleanup(
    real_controller: HyperVSandboxController,
    sandbox_spec: SandboxSpec,
):
    events: list[NightShiftEvent] = []
    backend = SandboxWorkerBackend(real_controller, spec=sandbox_spec, poll_interval=0.1)

    result = backend.run(
        _task("phase3-protocol-sleep:600"),
        timeout_seconds=_positive_environment(
            "NIGHT_SHIFT_HYPERV_TIMEOUT_TEST_SECONDS", "90"
        ),
        on_event=events.append,
    )

    assert result.outcome is WorkerOutcome.TIMED_OUT
    assert any(event.event_type == "protocol_test_sleeping" for event in events)
    _assert_destroyed(real_controller)


def test_real_host_reconciliation_removes_only_the_generated_orphan(
    real_controller: HyperVSandboxController,
    sandbox_spec: SandboxSpec,
    host_config: HyperVConfig,
    tmp_path: Path,
):
    sandbox = real_controller.create(job_id=_task("unused").job_id, spec=sandbox_spec)
    orphan_controller = HyperVSandboxController(
        host_config,
        SandboxStore(tmp_path / "fresh-operations.sqlite3"),
    )

    report = orphan_controller.reconcile(sandbox_ids=frozenset({sandbox.sandbox_id}))

    assert report.succeeded
    assert report.orphaned_destroyed == (sandbox.sandbox_id,)
    assert not (host_config.workspace_root / sandbox.sandbox_id).exists()
