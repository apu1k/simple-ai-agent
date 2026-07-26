from collections.abc import Sequence
from pathlib import Path

from night_shifts.contracts import (
    ArtifactRetriever,
    PreparedWorkspace,
    RetrievedArtifacts,
    WorkspaceInjector,
    WorkspaceProvider,
)
from night_shifts.models import SandboxRecord, SandboxSpec


class CompleteWorkspaceProvider:
    def prepare(
        self, *, job_id: str, repository_id: str, revision: str
    ) -> PreparedWorkspace:
        return PreparedWorkspace(job_id, repository_id, revision, Path("repository"))

    def destroy(self, workspace: PreparedWorkspace) -> None:
        return None


class CompleteWorkspaceInjector:
    def inject(
        self,
        sandbox: SandboxRecord,
        workspace: PreparedWorkspace,
        *,
        read_only: bool,
    ) -> None:
        return None


class CompleteArtifactRetriever:
    def retrieve(
        self, sandbox: SandboxRecord, references: Sequence[str]
    ) -> RetrievedArtifacts:
        return RetrievedArtifacts(Path("staging"), tuple(references))

    def cleanup(self, artifacts: RetrievedArtifacts) -> None:
        return None


class Incomplete:
    pass


def test_workspace_contracts_are_structural_and_independent() -> None:
    assert isinstance(CompleteWorkspaceProvider(), WorkspaceProvider)
    assert isinstance(CompleteWorkspaceInjector(), WorkspaceInjector)
    assert not isinstance(Incomplete(), WorkspaceProvider)
    assert not isinstance(Incomplete(), WorkspaceInjector)


def test_artifact_retriever_contract_is_structural_and_independent() -> None:
    retriever = CompleteArtifactRetriever()
    sandbox = SandboxRecord("job-1", "test", SandboxSpec())

    assert isinstance(retriever, ArtifactRetriever)
    assert retriever.retrieve(sandbox, ("guest-artifact/result.txt",)).references == (
        "guest-artifact/result.txt",
    )
    assert not isinstance(Incomplete(), ArtifactRetriever)
