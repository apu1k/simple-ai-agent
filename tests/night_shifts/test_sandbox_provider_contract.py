from night_shifts.contracts import SandboxProvider
from night_shifts.models import SandboxRecord, SandboxSpec, SandboxStatus


class CompleteProvider:
    @property
    def backend_name(self) -> str:
        return "test"

    def create(self, *, job_id: str, spec: SandboxSpec) -> SandboxRecord:
        return SandboxRecord(job_id=job_id, backend=self.backend_name, spec=spec)

    def start(self, sandbox: SandboxRecord) -> None:
        return None

    def status(self, sandbox: SandboxRecord) -> SandboxStatus:
        return SandboxStatus.RUNNING

    def pause(self, sandbox: SandboxRecord) -> None:
        return None

    def stop(self, sandbox: SandboxRecord) -> None:
        return None

    def destroy(self, sandbox: SandboxRecord) -> None:
        return None


class IncompleteProvider:
    pass


def test_sandbox_provider_is_structural_and_has_no_channel_methods():
    provider = CompleteProvider()

    assert isinstance(provider, SandboxProvider)
    assert not isinstance(IncompleteProvider(), SandboxProvider)
    assert not hasattr(provider, "send_task")
    assert not hasattr(provider, "events")
    assert not hasattr(provider, "retrieve_result")
