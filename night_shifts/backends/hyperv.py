"""Trusted-host Hyper-V lifecycle controller.

The controller invokes only repository-owned PowerShell scripts with structured
arguments. Agent text is never used in VM names, command text, or host paths.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from night_shifts.models import (
    SandboxRecord,
    SandboxSpec,
    SandboxStatus,
    utc_now,
)
from night_shifts.storage import SandboxStore

_SANDBOX_ID = re.compile(r"^[0-9a-f]{32}$")
_VM_PREFIX = "night-shift-"
_STATE_MAP = {
    "off": SandboxStatus.STOPPED,
    "running": SandboxStatus.RUNNING,
    "paused": SandboxStatus.PAUSED,
    "saved": SandboxStatus.PAUSED,
    "starting": SandboxStatus.STARTING,
    "stopping": SandboxStatus.STARTING,
    "missing": SandboxStatus.DESTROYED,
}


class HyperVError(RuntimeError):
    """Raised when host validation or a Hyper-V operation fails."""


class PowerShellCommandRunner(Protocol):
    """Execute a fixed PowerShell script with separate arguments."""

    def run(self, script: Path, arguments: Sequence[str]) -> str: ...


@dataclass(frozen=True)
class HyperVReconciliationReport:
    """Outcome of one fail-safe startup reconciliation pass."""

    reconciled: tuple[str, ...]
    destroyed: tuple[str, ...]
    orphaned_destroyed: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def succeeded(self) -> bool:
        """Return whether every eligible sandbox was cleaned up."""

        return not self.errors


@dataclass(frozen=True)
class HyperVConfig:
    """Trusted host configuration; never populated from an agent task."""

    base_image: Path
    base_image_sha256: str
    workspace_root: Path
    switch_name: str | None = None
    powershell_executable: str = "powershell.exe"
    command_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        digest = self.base_image_sha256.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("base_image_sha256 must be a 64-character SHA-256 digest")
        if self.command_timeout_seconds <= 0:
            raise ValueError("Hyper-V command timeout must be positive")
        if self.switch_name is not None and not self.switch_name.strip():
            raise ValueError("Hyper-V switch name must not be blank")


class SubprocessPowerShellRunner:
    """Default non-shell PowerShell script runner."""

    def __init__(self, executable: str = "powershell.exe", *, timeout_seconds: float = 120.0):
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def run(self, script: Path, arguments: Sequence[str]) -> str:
        command = (
            self.executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "RemoteSigned",
            "-File",
            str(script),
            *arguments,
        )
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            stderr = getattr(exc, "stderr", None)
            detail = str(stderr).strip() if stderr else str(exc)
            raise HyperVError(f"PowerShell operation failed: {detail}") from exc
        return completed.stdout.strip()


class HyperVSandboxController:
    """Manage owned generation-2 Hyper-V VMs and disposable differencing disks."""

    def __init__(
        self,
        config: HyperVConfig,
        store: SandboxStore,
        *,
        runner: PowerShellCommandRunner | None = None,
        scripts_dir: Path | None = None,
    ):
        self.config = config
        self.store = store
        self.runner = runner or SubprocessPowerShellRunner(
            config.powershell_executable,
            timeout_seconds=config.command_timeout_seconds,
        )
        self.scripts_dir = scripts_dir or Path(__file__).with_name("hyperv_scripts")

    @property
    def backend_name(self) -> str:
        return "hyperv"

    def check_prerequisites(self) -> None:
        self._verify_base_image()
        self._run("preflight.ps1", ())

    def reconcile(
        self,
        *,
        sandbox_ids: frozenset[str] | None = None,
    ) -> HyperVReconciliationReport:
        """Destroy sandboxes left behind when a previous controller stopped.

        Inventory is validated completely before cleanup starts. Only VMs whose
        trusted name and ownership marker agree are returned by the fixed host
        script. Persisted records are authoritative for identity conflicts, and
        cleanup continues after individual failures so one bad VM cannot strand
        every other owned sandbox.

        ``sandbox_ids`` restricts cleanup to exact orchestrator-generated IDs.
        Normal startup leaves it unset. The restricted form exists so real-host
        validation can prove orphan cleanup without touching another workload.
        """

        if sandbox_ids is not None:
            invalid_ids = sorted(
                value for value in sandbox_ids if not _SANDBOX_ID.fullmatch(value)
            )
            if invalid_ids:
                raise HyperVError("Reconciliation scope contains an invalid sandbox ID")

        self._run("preflight.ps1", ())
        inventory = self._owned_inventory()
        records = {record.sandbox_id: record for record in self.store.list()}
        if sandbox_ids is not None:
            inventory = {
                sandbox_id: status
                for sandbox_id, status in inventory.items()
                if sandbox_id in sandbox_ids
            }
            records = {
                sandbox_id: record
                for sandbox_id, record in records.items()
                if sandbox_id in sandbox_ids
            }
        reconciled: list[str] = []
        destroyed: list[str] = []
        orphaned_destroyed: list[str] = []
        errors: list[str] = []

        for sandbox_id, record in records.items():
            host_status = inventory.pop(sandbox_id, None)
            if record.backend != self.backend_name:
                if host_status is not None:
                    errors.append(
                        f"{sandbox_id}: owned Hyper-V VM conflicts with persisted "
                        f"backend {record.backend!r}"
                    )
                continue
            if record.status is SandboxStatus.DESTROYED and host_status is None:
                continue
            try:
                self._validate_record(record)
                if host_status is not None:
                    self._set_state(record, host_status)
                    reconciled.append(sandbox_id)
                self.destroy(record)
                destroyed.append(sandbox_id)
            except Exception as exc:
                errors.append(f"{sandbox_id}: {exc}")

        for sandbox_id in sorted(inventory):
            try:
                self._destroy_orphan(sandbox_id)
                orphaned_destroyed.append(sandbox_id)
            except Exception as exc:
                errors.append(f"{sandbox_id}: {exc}")

        return HyperVReconciliationReport(
            reconciled=tuple(reconciled),
            destroyed=tuple(destroyed),
            orphaned_destroyed=tuple(orphaned_destroyed),
            errors=tuple(errors),
        )

    def create(self, *, job_id: str, spec: SandboxSpec) -> SandboxRecord:
        if spec.network_enabled and self.config.switch_name is None:
            raise HyperVError("Network-enabled sandboxes require an approved Hyper-V switch")
        self.check_prerequisites()

        sandbox = SandboxRecord(job_id=job_id, backend=self.backend_name, spec=spec)
        vm_name = self._vm_name(sandbox)
        sandbox.external_id = vm_name
        self.store.create(sandbox)
        disk_path = self._disk_path(sandbox)
        disk_path.parent.mkdir(parents=True, exist_ok=False)
        try:
            self._run(
                "create.ps1",
                (
                    "-VmName", vm_name,
                    "-OwnerMarker", self._owner_marker(sandbox),
                    "-BaseImage", str(self.config.base_image.resolve()),
                    "-BaseImageSha256", self.config.base_image_sha256.lower(),
                    "-DiskPath", str(disk_path),
                    "-ComPortPipe", self._serial_pipe_path(sandbox),
                    "-CpuCount", str(spec.cpu_count),
                    "-MemoryBytes", str(spec.memory_mb * 1024 * 1024),
                    "-DiskSizeBytes", str(spec.disk_gb * 1024 * 1024 * 1024),
                    "-SwitchName", self.config.switch_name or "",
                ),
            )
        except Exception as exc:
            try:
                disk_path.parent.rmdir()
            except OSError:
                pass
            self._set_state(sandbox, SandboxStatus.ERROR, error=str(exc))
            raise
        self._set_state(sandbox, SandboxStatus.CREATED)
        return sandbox

    def start(self, sandbox: SandboxRecord) -> None:
        self._operate(sandbox, "start.ps1")
        self._set_state(sandbox, SandboxStatus.STARTING)

    def status(self, sandbox: SandboxRecord) -> SandboxStatus:
        self._validate_record(sandbox)
        try:
            state = self._run(
                "status.ps1",
                (
                    "-VmName", self._vm_name(sandbox),
                    "-OwnerMarker", self._owner_marker(sandbox),
                ),
            ).strip().lower()
        except Exception as exc:
            self._set_state(sandbox, SandboxStatus.ERROR, error=str(exc))
            raise
        mapped = _STATE_MAP.get(state, SandboxStatus.ERROR)
        self._set_state(
            sandbox,
            mapped,
            error=None if mapped is not SandboxStatus.ERROR else f"Unknown Hyper-V state: {state}",
        )
        return mapped

    def pause(self, sandbox: SandboxRecord) -> None:
        self._operate(sandbox, "pause.ps1")
        self._set_state(sandbox, SandboxStatus.PAUSED)

    def stop(self, sandbox: SandboxRecord) -> None:
        self._operate(sandbox, "stop.ps1")
        self._set_state(sandbox, SandboxStatus.STOPPED)

    def destroy(self, sandbox: SandboxRecord) -> None:
        self._validate_record(sandbox)
        try:
            self._run(
                "destroy.ps1",
                (
                    "-VmName", self._vm_name(sandbox),
                    "-OwnerMarker", self._owner_marker(sandbox),
                    "-DiskPath", str(self._disk_path(sandbox)),
                ),
            )
            self._remove_workspace(sandbox)
        except Exception as exc:
            self._set_state(sandbox, SandboxStatus.ERROR, error=str(exc))
            raise
        self._set_state(sandbox, SandboxStatus.DESTROYED)

    def _owned_inventory(self) -> dict[str, SandboxStatus]:
        output = self._run("list_owned.ps1", ())
        inventory: dict[str, SandboxStatus] = {}
        for line in output.splitlines():
            fields = line.strip().split("\t")
            if len(fields) != 2 or not _SANDBOX_ID.fullmatch(fields[0]):
                raise HyperVError("Hyper-V owned-VM inventory returned malformed output")
            sandbox_id, raw_state = fields
            state = _STATE_MAP.get(raw_state.lower())
            if state is None or state is SandboxStatus.DESTROYED:
                raise HyperVError(
                    f"Hyper-V owned-VM inventory returned unknown state: {raw_state}"
                )
            if sandbox_id in inventory:
                raise HyperVError("Hyper-V owned-VM inventory returned a duplicate ID")
            inventory[sandbox_id] = state
        return inventory

    def _destroy_orphan(self, sandbox_id: str) -> None:
        sandbox = SandboxRecord(
            job_id="orphaned-host-vm",
            backend=self.backend_name,
            spec=SandboxSpec(),
            sandbox_id=sandbox_id,
            external_id=f"{_VM_PREFIX}{sandbox_id}",
        )
        self._validate_record(sandbox)
        self._run(
            "destroy.ps1",
            (
                "-VmName", self._vm_name(sandbox),
                "-OwnerMarker", self._owner_marker(sandbox),
                "-DiskPath", str(self._disk_path(sandbox)),
            ),
        )
        self._remove_workspace(sandbox)

    def _operate(self, sandbox: SandboxRecord, script: str) -> None:
        self._validate_record(sandbox)
        try:
            self._run(
                script,
                ("-VmName", self._vm_name(sandbox), "-OwnerMarker", self._owner_marker(sandbox)),
            )
        except Exception as exc:
            self._set_state(sandbox, SandboxStatus.ERROR, error=str(exc))
            raise

    def _verify_base_image(self) -> None:
        image = self.config.base_image
        if not image.is_file():
            raise HyperVError(f"Hyper-V base image does not exist: {image}")
        with image.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if not hmac.compare_digest(actual, self.config.base_image_sha256.lower()):
            raise HyperVError("Hyper-V base image SHA-256 does not match trusted configuration")

    def _validate_record(self, sandbox: SandboxRecord) -> None:
        if sandbox.backend != self.backend_name:
            raise HyperVError(f"Sandbox belongs to backend {sandbox.backend!r}, not Hyper-V")
        expected = self._vm_name(sandbox)
        if sandbox.external_id != expected:
            raise HyperVError("Sandbox external ID does not match its trusted sandbox ID")

    @staticmethod
    def _owner_marker(sandbox: SandboxRecord) -> str:
        return f"night-shift-owner:{sandbox.sandbox_id}"

    @staticmethod
    def _vm_name(sandbox: SandboxRecord) -> str:
        if not _SANDBOX_ID.fullmatch(sandbox.sandbox_id):
            raise HyperVError("Sandbox ID is not a trusted 32-character hexadecimal ID")
        return f"{_VM_PREFIX}{sandbox.sandbox_id}"

    @staticmethod
    def _serial_pipe_path(sandbox: SandboxRecord) -> str:
        if not _SANDBOX_ID.fullmatch(sandbox.sandbox_id):
            raise HyperVError("Sandbox ID is not a trusted 32-character hexadecimal ID")
        return rf"\\.\pipe\{_VM_PREFIX}{sandbox.sandbox_id}-com1"

    def _disk_path(self, sandbox: SandboxRecord) -> Path:
        root = self.config.workspace_root.resolve()
        path = (root / sandbox.sandbox_id / "worker.vhdx").resolve()
        if root not in path.parents:
            raise HyperVError("Sandbox disk path escaped the configured workspace")
        return path

    def _remove_workspace(self, sandbox: SandboxRecord) -> None:
        workspace = self._disk_path(sandbox).parent
        try:
            workspace.rmdir()
        except FileNotFoundError:
            pass

    def _run(self, script_name: str, arguments: Sequence[str]) -> str:
        script = (self.scripts_dir / script_name).resolve()
        if script.parent != self.scripts_dir.resolve() or not script.is_file():
            raise HyperVError(f"Trusted Hyper-V script is missing: {script_name}")
        return self.runner.run(script, arguments)

    def _set_state(
        self,
        sandbox: SandboxRecord,
        status: SandboxStatus,
        *,
        error: str | None = None,
    ) -> None:
        sandbox.status = status
        sandbox.updated_at = utc_now()
        sandbox.last_error = error
        self.store.update(sandbox)
