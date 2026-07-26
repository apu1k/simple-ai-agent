"""Small bounded Markdown-file protocol for worker handoffs."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from collections.abc import Iterable
from pathlib import Path

from night_shifts.models import NightShiftEvent, SandboxRecord
from night_shifts.protocol import WorkerOutcome, WorkerResult, WorkerTask

TASK_FILE = "TASK.md"
PROGRESS_FILE = "PROGRESS.md"
RESULT_FILE = "RESULT.md"
_SANDBOX_ID = re.compile(r"[0-9a-f]{32}")
_OUTCOMES = {item.value: item for item in WorkerOutcome}


class MarkdownMailboxError(RuntimeError):
    """Raised when a mailbox violates the bounded protocol."""


class MarkdownMailboxChannel:
    """Exchange one task and result through fixed Markdown files."""

    def __init__(self, root: Path, *, max_file_bytes: int = 256 * 1024) -> None:
        if max_file_bytes <= 0 or max_file_bytes > 4 * 1024 * 1024:
            raise ValueError("mailbox file limit must be between 1 byte and 4 MiB")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_file_bytes = max_file_bytes
        self._progress_hashes: dict[str, str] = {}
        self._closed: set[str] = set()

    def send_task(self, sandbox: SandboxRecord, task: WorkerTask) -> None:
        self._require_open(sandbox)
        if task.job_id != sandbox.job_id:
            raise MarkdownMailboxError("task job ID does not match sandbox job ID")
        directory = self._directory(sandbox)
        directory.mkdir(mode=0o700, exist_ok=True)
        content = _render_task(task)
        self._write_once(directory / TASK_FILE, content)

    def events(self, sandbox: SandboxRecord) -> Iterable[NightShiftEvent]:
        self._require_open(sandbox)
        path = self._directory(sandbox) / PROGRESS_FILE
        if not path.exists():
            return
        content = self._read_file(path)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if self._progress_hashes.get(sandbox.sandbox_id) == digest:
            return
        self._progress_hashes[sandbox.sandbox_id] = digest
        yield NightShiftEvent(
            job_id=sandbox.job_id,
            event_type="worker_progress",
            actor="worker",
            payload={"markdown": content},
        )

    def retrieve_result(self, sandbox: SandboxRecord) -> WorkerResult:
        self._require_open(sandbox)
        content = self._read_file(self._directory(sandbox) / RESULT_FILE)
        return _parse_result(sandbox.job_id, content)

    def close(self, sandbox: SandboxRecord) -> None:
        self._closed.add(sandbox.sandbox_id)

    def _directory(self, sandbox: SandboxRecord) -> Path:
        if not _SANDBOX_ID.fullmatch(sandbox.sandbox_id):
            raise MarkdownMailboxError("sandbox ID is not a trusted mailbox identifier")
        return self.root / sandbox.sandbox_id

    def _require_open(self, sandbox: SandboxRecord) -> None:
        if sandbox.sandbox_id in self._closed:
            raise MarkdownMailboxError("worker mailbox is closed")

    def _read_file(self, path: Path) -> str:
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise MarkdownMailboxError(f"mailbox file is not available: {path.name}") from exc
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise MarkdownMailboxError(f"mailbox file is not a regular file: {path.name}")
        if metadata.st_size > self.max_file_bytes:
            raise MarkdownMailboxError(f"mailbox file exceeds the size limit: {path.name}")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise MarkdownMailboxError(f"could not read mailbox file: {path.name}") from exc
        if len(content) > self.max_file_bytes:
            raise MarkdownMailboxError(f"mailbox file exceeds the size limit: {path.name}")
        try:
            return content.decode("utf-8").replace("\r\n", "\n")
        except UnicodeDecodeError as exc:
            raise MarkdownMailboxError(f"mailbox file is not UTF-8: {path.name}") from exc

    def _write_once(self, path: Path, content: str) -> None:
        payload = content.encode("utf-8")
        if len(payload) > self.max_file_bytes:
            raise MarkdownMailboxError(f"mailbox file exceeds the size limit: {path.name}")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
        except FileExistsError as exc:
            raise MarkdownMailboxError(f"mailbox file already exists: {path.name}") from exc
        except OSError as exc:
            raise MarkdownMailboxError(f"could not publish mailbox file: {path.name}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)


def _render_task(task: WorkerTask) -> str:
    criteria = "\n".join(f"- {item}" for item in task.acceptance_criteria) or "- None supplied"
    repository = task.repository_id or "None"
    revision = task.starting_revision or "None"
    return (
        "# Night Shift Task\n\n"
        "## Objective\n\n"
        f"{task.objective}\n\n"
        "## Acceptance Criteria\n\n"
        f"{criteria}\n\n"
        "## Repository\n\n"
        f"- Repository ID: {repository}\n"
        f"- Starting revision: {revision}\n\n"
        "## Worker\n\n"
        f"- Profile: {task.worker_profile}\n"
        f"- Plan: {task.plan.value}\n\n"
        "## Result Contract\n\n"
        f"Write `{RESULT_FILE}` beginning with `# Night Shift Result` and "
        "`Outcome: <success|failed|cancelled|timed_out>`.\n"
    )


def _parse_result(job_id: str, content: str) -> WorkerResult:
    normalized = content.replace("\r\n", "\n")
    lines = normalized.splitlines()
    if len(lines) < 3 or lines[0] != "# Night Shift Result":
        raise MarkdownMailboxError("RESULT.md has an invalid heading")
    if not lines[1].startswith("Outcome: "):
        raise MarkdownMailboxError("RESULT.md has no outcome line")
    outcome_text = lines[1].removeprefix("Outcome: ").strip()
    try:
        outcome = _OUTCOMES[outcome_text]
    except KeyError as exc:
        raise MarkdownMailboxError("RESULT.md has an unknown outcome") from exc
    summary = "\n".join(lines[2:]).strip()
    if not summary:
        raise MarkdownMailboxError("RESULT.md has no result body")
    return WorkerResult(
        job_id=job_id,
        outcome=outcome,
        summary=summary,
        error=summary if outcome is WorkerOutcome.FAILED else None,
    )
