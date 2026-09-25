"""Trusted host orchestration of a fixed, non-model sandbox transfer fixture.

No real transport or VM is enabled by importing this module. A caller must
supply an explicitly approved SandboxProvider and bound ToolSessionTransport.
Guest check claims are data, not trusted proof of repository correctness.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from night_shifts.contracts.sandbox import SandboxProvider
from night_shifts.models import SandboxRecord, SandboxSpec, SandboxStatus
from night_shifts.snapshot import MAX_SNAPSHOT_BYTES, Snapshot, encode_snapshot
from night_shifts.tool_session import SandboxToolSession

CHUNK_BYTES = 16 * 1024


class FixtureResultError(RuntimeError):
    """The guest report is invalid or cannot be retrieved completely."""


@dataclass(frozen=True)
class FixtureEvidence:
    snapshot_sha256: str
    report_sha256: str
    reported_pass: bool
    reported_output: str
    report: bytes


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FixtureResultError("duplicate guest result field")
        result[key] = value
    return result


def _check_report(raw: bytes, snapshot: Snapshot, archive: bytes) -> FixtureEvidence:
    try:
        report = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise FixtureResultError("guest report is not UTF-8 JSON") from exc
    if (not isinstance(report, dict) or set(report) != {"version", "job_id", "revision",
            "image_sha256", "snapshot_sha256", "check", "output"}
            or type(report["version"]) is not int or report["version"] != 1
            or report["job_id"] != snapshot.job_id or report["revision"] != snapshot.revision
            or report["image_sha256"] != snapshot.image_sha256
            or report["snapshot_sha256"] != hashlib.sha256(archive).hexdigest()):
        raise FixtureResultError("guest report identity or snapshot digest mismatch")
    check, output = report["check"], report["output"]
    if (not isinstance(check, dict) or set(check) != {"name", "passed", "output"}
            or check["name"] != "fixed-fixture-text" or type(check["passed"]) is not bool
            or not isinstance(check["output"], str)
            or check["output"] not in {"fixed fixture matched", "fixed fixture did not match"}
            or not isinstance(output, dict) or set(output) != {"path", "text"}
            or output["path"] != "fixture-result.txt" or not isinstance(output["text"], str)
            or output["text"] != check["output"] + "\n"
            or check["passed"] != (check["output"] == "fixed fixture matched")):
        raise FixtureResultError("guest check or output shape is invalid")
    return FixtureEvidence(report["snapshot_sha256"], hashlib.sha256(raw).hexdigest(),
                           check["passed"], output["text"], raw)


def transfer_fixture(session: SandboxToolSession, snapshot: Snapshot) -> FixtureEvidence:
    """Send the whole exact snapshot and receive all bounded result bytes.

    A failed/unknown mutating acknowledgement is terminal: the session is
    closed; caller must destroy the sandbox, never replay the load.
    """
    archive = encode_snapshot(snapshot)
    try:
        session.start()
        for offset in range(0, len(archive), CHUNK_BYTES):
            end = min(offset + CHUNK_BYTES, len(archive))
            session.load_chunk(archive[offset:end], offset=offset, final=end == len(archive))
        session.finalize()
        result = bytearray()
        while True:
            if len(result) >= MAX_SNAPSHOT_BYTES:
                raise FixtureResultError("guest report exceeds transfer limit")
            limit = min(CHUNK_BYTES, MAX_SNAPSHOT_BYTES - len(result))
            chunk, eof = session.export_chunk(offset=len(result), limit_bytes=limit)
            result.extend(chunk)
            if eof:
                return _check_report(bytes(result), snapshot, archive)
    finally:
        session.close()


@dataclass(frozen=True)
class FixtureRun:
    evidence: FixtureEvidence | None
    error: str | None
    cleanup_error: str | None
    sandbox_id: str | None

    @property
    def succeeded(self) -> bool:
        return (self.evidence is not None and self.evidence.reported_pass
                and not self.error and not self.cleanup_error)


def run_fixture_in_sandbox(
    provider: SandboxProvider,
    session_factory: Callable[[SandboxRecord, float], SandboxToolSession],
    snapshot: Snapshot,
    *,
    reviewed_image_sha256: str,
    spec: SandboxSpec,
    timeout_seconds: float = 90.0,
    poll_interval_seconds: float = 0.1,
) -> FixtureRun:
    """One opt-in caller-managed VM path; always attempt exact-ID destruction.

    No host checkout is mutated. Does not reconcile or sweep other VMs. The
    factory must bind a reviewed pipe to this sandbox and the same deadline.
    No automatic retry after a failed start, load, finalize or export.
    """
    if not 0 < timeout_seconds <= 3600 or not 0 < poll_interval_seconds <= 5:
        raise ValueError("fixture runtime limits are invalid")
    if (snapshot.image_sha256 != reviewed_image_sha256 or spec.network_enabled):
        raise ValueError("fixture image identity or network-off policy is not approved")
    encode_snapshot(snapshot)  # reject before VM creation
    deadline = time.monotonic() + timeout_seconds
    sandbox: SandboxRecord | None = None
    session: SandboxToolSession | None = None
    evidence: FixtureEvidence | None = None
    error: str | None = None
    cleanup: list[str] = []
    try:
        sandbox = provider.create(job_id=snapshot.job_id, spec=spec)
        if (sandbox.backend != "hyperv" or sandbox.job_id != snapshot.job_id
                or sandbox.spec != spec
                or not re.fullmatch(r"[0-9a-f]{32}", sandbox.sandbox_id)
                or sandbox.external_id != f"night-shift-{sandbox.sandbox_id}"):
            raise FixtureResultError("provider returned an unbound sandbox")
        provider.start(sandbox)
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("fixture VM start deadline expired")
            status = provider.status(sandbox)
            if status is SandboxStatus.RUNNING:
                break
            if status not in {SandboxStatus.STARTING, SandboxStatus.CREATED}:
                raise FixtureResultError("fixture sandbox stopped before session started")
            time.sleep(min(poll_interval_seconds, deadline - time.monotonic()))
        session = session_factory(sandbox, deadline)
        evidence = transfer_fixture(session, snapshot)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as exc:
                cleanup.append(f"session close: {exc}")
        if sandbox is not None:
            try:
                provider.destroy(sandbox)
            except Exception as exc:
                cleanup.append(f"sandbox destroy: {exc}")
    return FixtureRun(evidence, error, "; ".join(cleanup) if cleanup else None,
                      sandbox.sandbox_id if sandbox is not None else None)
