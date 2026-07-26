from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

from night_shifts.artifacts import ArtifactCollector
from night_shifts.backends.sandbox_worker import SandboxWorkerBackend
from night_shifts.composition import (
    CompositionError,
    ExecutionComponentSelection,
    TrustedExecutionRegistry,
)
from night_shifts.contracts import PreparedWorkspace, RetrievedArtifacts
from night_shifts.models import NightShiftEvent, SandboxRecord, SandboxSpec, SandboxStatus
from night_shifts.protocol import WorkerOutcome, WorkerResult, WorkerTask
from night_shifts.storage import ArtifactStore


class Provider:
    backend_name = "test-vm"

    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    def create(self, *, job_id: str, spec: SandboxSpec) -> SandboxRecord:
        self.trace.append("sandbox.create")
        return SandboxRecord(job_id, self.backend_name, spec)

    def start(self, sandbox: SandboxRecord) -> None:
        self.trace.append("sandbox.start")

    def status(self, sandbox: SandboxRecord) -> SandboxStatus:
        self.trace.append("sandbox.status")
        return SandboxStatus.RUNNING

    def pause(self, sandbox: SandboxRecord) -> None:
        return None

    def stop(self, sandbox: SandboxRecord) -> None:
        return None

    def destroy(self, sandbox: SandboxRecord) -> None:
        self.trace.append("sandbox.destroy")


class Channel:
    def __init__(self, trace: list[str], result: WorkerResult) -> None:
        self.trace = trace
        self.result = result

    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None:
        self.trace.append("channel.send")

    def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]:
        self.trace.append("channel.events")
        return ()

    def retrieve_result(self, sandbox: SandboxRecord) -> WorkerResult:
        self.trace.append("channel.result")
        return self.result

    def close(self, sandbox: SandboxRecord) -> None:
        self.trace.append("channel.close")


class Workspaces:
    def __init__(self, trace: list[str], root: Path) -> None:
        self.trace = trace
        self.root = root

    def prepare(
        self, *, job_id: str, repository_id: str, revision: str
    ) -> PreparedWorkspace:
        self.trace.append("workspace.prepare")
        return PreparedWorkspace(job_id, repository_id, revision, self.root)

    def destroy(self, workspace: PreparedWorkspace) -> None:
        self.trace.append("workspace.destroy")


class Injector:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.read_only: bool | None = None

    def inject(
        self,
        sandbox: SandboxRecord,
        workspace: PreparedWorkspace,
        *,
        read_only: bool,
    ) -> None:
        self.trace.append("workspace.inject")
        self.read_only = read_only


class Retriever:
    def __init__(self, trace: list[str], staging: Path) -> None:
        self.trace = trace
        self.staging = staging

    def retrieve(
        self, sandbox: SandboxRecord, references: Sequence[str]
    ) -> RetrievedArtifacts:
        self.trace.append("artifact.retrieve")
        self.staging.mkdir()
        (self.staging / "result.txt").write_text("bounded output\n", encoding="utf-8")
        return RetrievedArtifacts(self.staging, tuple(references))

    def cleanup(self, artifacts: RetrievedArtifacts) -> None:
        self.trace.append("artifact.cleanup")


def test_workspace_and_artifact_boundaries_have_fail_safe_ordering(tmp_path: Path) -> None:
    trace: list[str] = []
    job_id = "a" * 32
    result = WorkerResult(
        job_id,
        WorkerOutcome.SUCCESS,
        "done",
        artifacts=("guest-artifact/result.txt",),
    )
    provider = Provider(trace)
    channel = Channel(trace, result)
    workspaces = Workspaces(trace, tmp_path / "workspace")
    injector = Injector(trace)
    retriever = Retriever(trace, tmp_path / "staging")
    collector = ArtifactCollector(
        tmp_path / "trusted-artifacts",
        ArtifactStore(tmp_path / "operations.sqlite3"),
    )
    backend = SandboxWorkerBackend(
        provider,
        channel,
        workspace_provider=workspaces,
        workspace_injector=injector,
        artifact_retriever=retriever,
        artifact_collector=collector,
        poll_interval=0.001,
    )
    task = WorkerTask(
        job_id,
        "Review",
        "review-worker",
        repository_id="approved-repository",
        starting_revision="main",
    )

    observed = backend.run(task, timeout_seconds=1)

    assert observed == result
    assert injector.read_only is True
    assert trace == [
        "workspace.prepare",
        "sandbox.create",
        "workspace.inject",
        "sandbox.start",
        "sandbox.status",
        "channel.send",
        "channel.events",
        "channel.result",
        "channel.close",
        "artifact.retrieve",
        "artifact.cleanup",
        "sandbox.destroy",
        "workspace.destroy",
    ]


def test_trusted_registry_rejects_unknown_and_partial_component_selection() -> None:
    trace: list[str] = []
    registry = TrustedExecutionRegistry(
        sandbox_providers={"local-vm": Provider(trace)},
        worker_channels={
            "serial-v1": Channel(
                trace,
                WorkerResult("job-1", WorkerOutcome.SUCCESS, "done"),
            )
        },
    )

    backend = registry.build_backend(
        ExecutionComponentSelection("local-vm", "serial-v1")
    )
    assert backend.provider is not None
    assert backend.channel is not None

    with pytest.raises(CompositionError, match="Unknown approved worker channel"):
        registry.build_backend(ExecutionComponentSelection("local-vm", "from-task-text"))
    with pytest.raises(CompositionError, match="selected together"):
        registry.build_backend(
            ExecutionComponentSelection(
                "local-vm",
                "serial-v1",
                workspace_provider="git-v1",
            )
        )
