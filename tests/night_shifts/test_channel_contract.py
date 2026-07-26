from collections.abc import Iterable

from night_shifts.contracts import WorkerChannel
from night_shifts.models import NightShiftEvent, SandboxRecord
from night_shifts.protocol import WorkerResult, WorkerTask


class CompleteChannel:
    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None:
        return None

    def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]:
        return ()

    def retrieve_result(self, sandbox: SandboxRecord) -> WorkerResult:
        raise RuntimeError("no result")

    def close(self, sandbox: SandboxRecord) -> None:
        return None


class IncompleteChannel:
    pass


def test_worker_channel_is_structural_and_backend_independent():
    assert isinstance(CompleteChannel(), WorkerChannel)
    assert not isinstance(IncompleteChannel(), WorkerChannel)
