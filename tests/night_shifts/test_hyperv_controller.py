import hashlib
from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

from night_shifts.backends.hyperv import (
    HyperVConfig,
    HyperVError,
    HyperVSandboxController,
)
from night_shifts.models import NightShiftEvent, SandboxRecord, SandboxSpec, SandboxStatus
from night_shifts.protocol import (
    WorkerOutcome,
    WorkerResult,
    WorkerTask,
    decode_task,
    encode_event,
    encode_result,
)
from night_shifts.storage import SandboxStore


class FakeRunner:
    def __init__(self):
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.outputs: dict[str, str] = {"preflight.ps1": "ready"}
        self.error_for: str | None = None

    def run(self, script: Path, arguments: Sequence[str]) -> str:
        self.calls.append((script.name, tuple(arguments)))
        if script.name == self.error_for:
            raise HyperVError("simulated host failure")
        return self.outputs.get(script.name, "")


class FakeTransport:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.sent: list[str] = []
        self.closed: list[str] = []

    def send(self, sandbox: SandboxRecord, message: str) -> None:
        self.sent.append(message)

    def event_messages(self, sandbox: SandboxRecord) -> Iterable[str]:
        yield encode_event(
            NightShiftEvent(
                job_id=self.job_id,
                event_type="progress_updated",
                actor="worker",
                payload={"percent": 50},
            )
        )

    def result_message(self, sandbox: SandboxRecord) -> str:
        return encode_result(
            WorkerResult(self.job_id, WorkerOutcome.SUCCESS, "completed")
        )

    def close(self, sandbox: SandboxRecord) -> None:
        self.closed.append(sandbox.sandbox_id)


def build_controller(
    tmp_path: Path,
    *,
    runner: FakeRunner | None = None,
    transport: FakeTransport | None = None,
    switch_name: str | None = None,
):
    image = tmp_path / "base.vhdx"
    image.write_bytes(b"reviewed base image")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    database = tmp_path / "operations.sqlite3"
    selected_runner = runner or FakeRunner()
    controller = HyperVSandboxController(
        HyperVConfig(
            base_image=image,
            base_image_sha256=digest,
            workspace_root=tmp_path / "sandboxes",
            switch_name=switch_name,
        ),
        SandboxStore(database),
        runner=selected_runner,
        transport=transport,
    )
    return controller, selected_runner


def test_create_uses_trusted_names_fixed_scripts_and_persists_policy(tmp_path: Path):
    controller, runner = build_controller(tmp_path)

    sandbox = controller.create(
        job_id="job with untrusted text",
        spec=SandboxSpec(cpu_count=4, memory_mb=8192, disk_gb=40),
    )

    assert sandbox.external_id == f"night-shift-{sandbox.sandbox_id}"
    assert sandbox.status is SandboxStatus.CREATED
    assert controller.store.get(sandbox.sandbox_id) == sandbox
    assert [call[0] for call in runner.calls] == ["preflight.ps1", "create.ps1"]
    create_arguments = runner.calls[-1][1]
    assert "job with untrusted text" not in create_arguments
    assert create_arguments[create_arguments.index("-CpuCount") + 1] == "4"
    assert create_arguments[create_arguments.index("-MemoryBytes") + 1] == str(
        8192 * 1024 * 1024
    )
    assert create_arguments[create_arguments.index("-ComPortPipe") + 1] == (
        rf"\\.\pipe\night-shift-{sandbox.sandbox_id}-com1"
    )
    assert create_arguments[create_arguments.index("-SwitchName") + 1] == ""


def test_lifecycle_updates_durable_host_observed_state(tmp_path: Path):
    controller, runner = build_controller(tmp_path)
    sandbox = controller.create(job_id="job-1", spec=SandboxSpec())

    controller.start(sandbox)
    assert sandbox.status is SandboxStatus.STARTING
    runner.outputs["status.ps1"] = "Running"
    assert controller.status(sandbox) is SandboxStatus.RUNNING
    controller.pause(sandbox)
    assert sandbox.status is SandboxStatus.PAUSED
    controller.stop(sandbox)
    assert sandbox.status is SandboxStatus.STOPPED
    controller.destroy(sandbox)

    assert sandbox.status is SandboxStatus.DESTROYED
    assert controller.store.get(sandbox.sandbox_id) == sandbox
    assert [call[0] for call in runner.calls] == [
        "preflight.ps1",
        "create.ps1",
        "start.ps1",
        "status.ps1",
        "pause.ps1",
        "stop.ps1",
        "destroy.ps1",
    ]


def test_create_rejects_changed_base_image_before_hyperv_call(tmp_path: Path):
    controller, runner = build_controller(tmp_path)
    controller.config.base_image.write_bytes(b"tampered")

    with pytest.raises(HyperVError, match="SHA-256"):
        controller.create(job_id="job-1", spec=SandboxSpec())

    assert runner.calls == []
    assert controller.store.list() == []


def test_create_failure_is_persisted_for_restart_cleanup(tmp_path: Path):
    runner = FakeRunner()
    runner.error_for = "create.ps1"
    controller, _ = build_controller(tmp_path, runner=runner)

    with pytest.raises(HyperVError, match="simulated host failure"):
        controller.create(job_id="job-1", spec=SandboxSpec())

    failed = controller.store.list()[0]
    assert failed.status is SandboxStatus.ERROR
    assert failed.external_id == f"night-shift-{failed.sandbox_id}"
    assert failed.last_error == "simulated host failure"
    assert not (controller.config.workspace_root / failed.sandbox_id).exists()


def test_network_requires_a_trusted_switch(tmp_path: Path):
    controller, runner = build_controller(tmp_path)

    with pytest.raises(HyperVError, match="approved Hyper-V switch"):
        controller.create(
            job_id="job-1",
            spec=SandboxSpec(network_enabled=True),
        )

    assert runner.calls == []


def test_lifecycle_failure_is_persisted(tmp_path: Path):
    runner = FakeRunner()
    controller, _ = build_controller(tmp_path, runner=runner)
    sandbox = controller.create(job_id="job-1", spec=SandboxSpec())
    runner.error_for = "status.ps1"

    with pytest.raises(HyperVError, match="simulated host failure"):
        controller.status(sandbox)

    assert sandbox.status is SandboxStatus.ERROR
    assert controller.store.get(sandbox.sandbox_id) == sandbox


def test_transport_round_trips_only_validated_protocol_messages(tmp_path: Path):
    transport = FakeTransport("job-1")
    controller, _ = build_controller(tmp_path, transport=transport)
    sandbox = controller.create(job_id="job-1", spec=SandboxSpec())
    task = WorkerTask("job-1", "Work", "coding-worker")

    controller.send_task(sandbox, task)
    events = list(controller.events(sandbox))
    result = controller.retrieve_results(sandbox)

    assert decode_task(transport.sent[0]) == task
    assert events[0].event_type == "progress_updated"
    assert result.outcome is WorkerOutcome.SUCCESS


def test_default_transport_fails_closed(tmp_path: Path):
    controller, _ = build_controller(tmp_path)
    sandbox = controller.create(job_id="job-1", spec=SandboxSpec())

    with pytest.raises(HyperVError, match="No Hyper-V guest transport"):
        controller.send_task(
            sandbox,
            WorkerTask("job-1", "Work", "coding-worker"),
        )


def test_controller_rejects_forged_external_identity(tmp_path: Path):
    controller, _ = build_controller(tmp_path)
    sandbox = controller.create(job_id="job-1", spec=SandboxSpec())
    sandbox.external_id = "some-personal-vm"

    with pytest.raises(HyperVError, match="external ID"):
        controller.start(sandbox)


def test_reconcile_destroys_persisted_and_owned_orphan_vms(tmp_path: Path):
    controller, runner = build_controller(tmp_path)
    persisted = controller.create(job_id="job-1", spec=SandboxSpec())
    orphan_id = "a" * 32
    runner.outputs["list_owned.ps1"] = (
        f"{persisted.sandbox_id}\tRunning\n{orphan_id}\tOff"
    )

    report = controller.reconcile()

    assert report.succeeded
    assert report.reconciled == (persisted.sandbox_id,)
    assert report.destroyed == (persisted.sandbox_id,)
    assert report.orphaned_destroyed == (orphan_id,)
    assert controller.store.get(persisted.sandbox_id).status is SandboxStatus.DESTROYED
    destroy_calls = [call for call in runner.calls if call[0] == "destroy.ps1"]
    assert len(destroy_calls) == 2
    assert destroy_calls[1][1][1] == f"night-shift-{orphan_id}"
    assert destroy_calls[1][1][3] == f"night-shift-owner:{orphan_id}"


def test_reconcile_cleans_record_when_vm_is_already_missing(tmp_path: Path):
    controller, runner = build_controller(tmp_path)
    persisted = controller.create(job_id="job-1", spec=SandboxSpec())
    runner.outputs["list_owned.ps1"] = ""

    report = controller.reconcile()

    assert report.succeeded
    assert report.reconciled == ()
    assert report.destroyed == (persisted.sandbox_id,)
    assert controller.store.get(persisted.sandbox_id).status is SandboxStatus.DESTROYED


def test_reconcile_validates_complete_inventory_before_cleanup(tmp_path: Path):
    controller, runner = build_controller(tmp_path)
    persisted = controller.create(job_id="job-1", spec=SandboxSpec())
    runner.outputs["list_owned.ps1"] = f"{persisted.sandbox_id}\tNotAState"

    with pytest.raises(HyperVError, match="unknown state"):
        controller.reconcile()

    assert not any(call[0] == "destroy.ps1" for call in runner.calls)
    assert controller.store.get(persisted.sandbox_id).status is SandboxStatus.CREATED


def test_reconcile_refuses_cross_backend_identity_conflict(tmp_path: Path):
    controller, runner = build_controller(tmp_path)
    conflicting = SandboxRecord(
        job_id="job-1",
        backend="another-backend",
        spec=SandboxSpec(),
        sandbox_id="b" * 32,
        external_id="another-external-id",
    )
    controller.store.create(conflicting)
    runner.outputs["list_owned.ps1"] = f"{conflicting.sandbox_id}\tRunning"

    report = controller.reconcile()

    assert not report.succeeded
    assert "conflicts with persisted backend" in report.errors[0]
    assert not any(call[0] == "destroy.ps1" for call in runner.calls)


def test_destroy_removes_vm_even_when_transport_close_fails(tmp_path: Path):
    class FailingCloseTransport(FakeTransport):
        def close(self, sandbox: SandboxRecord) -> None:
            raise HyperVError("pipe close failed")

    runner = FakeRunner()
    controller, _ = build_controller(
        tmp_path,
        runner=runner,
        transport=FailingCloseTransport("job-1"),
    )
    sandbox = controller.create(job_id="job-1", spec=SandboxSpec())

    with pytest.raises(HyperVError, match="destroyed.*transport failed to close"):
        controller.destroy(sandbox)

    assert any(call[0] == "destroy.ps1" for call in runner.calls)
    assert controller.store.get(sandbox.sandbox_id).status is SandboxStatus.DESTROYED


def test_reconcile_continues_after_individual_cleanup_failure(tmp_path: Path):
    class SelectiveFailureRunner(FakeRunner):
        def run(self, script: Path, arguments: Sequence[str]) -> str:
            self.calls.append((script.name, tuple(arguments)))
            if script.name == "destroy.ps1" and arguments[1].endswith("c" * 32):
                raise HyperVError("first cleanup failed")
            return self.outputs.get(script.name, "")

    runner = SelectiveFailureRunner()
    controller, _ = build_controller(tmp_path, runner=runner)
    first_id = "c" * 32
    second_id = "d" * 32
    runner.outputs["list_owned.ps1"] = f"{first_id}\tRunning\n{second_id}\tPaused"

    report = controller.reconcile()

    assert not report.succeeded
    assert report.orphaned_destroyed == (second_id,)
    assert "first cleanup failed" in report.errors[0]
    assert len([call for call in runner.calls if call[0] == "destroy.ps1"]) == 2
