"""Orchestrator-only final workspace retrieval over an already bound tool session.

This is not a real Hyper-V serial adapter. It never interprets a guest request
as an instruction to execute a host tool. The backend must destroy the sandbox
and persist incomplete evidence even if this retrieval fails.
"""

from __future__ import annotations

from night_shifts.final_workspace import FinalWorkspace, decode_final_workspace
from night_shifts.snapshot import MAX_SNAPSHOT_BYTES, Snapshot
from night_shifts.tool_session import SandboxToolSession

CHUNK_BYTES = 16 * 1024


def retrieve_final_workspace(session: SandboxToolSession, base: Snapshot) -> FinalWorkspace:
    """Read a complete bounded export, reject mismatched identity and close on exit.

    No retry after an uncertain finalize/export. The model cannot call finalize
    or export through the WorkerToolProvider facade.
    """
    try:
        if base.job_id != session.job_id:
            raise ValueError("final workspace job does not match the tool session")
        session.finalize()
        data = bytearray()
        while True:
            remaining = MAX_SNAPSHOT_BYTES - len(data)
            if remaining <= 0:
                raise ValueError("final workspace export exceeds transfer limit")
            chunk, eof = session.export_chunk(offset=len(data), limit_bytes=min(CHUNK_BYTES, remaining))
            data.extend(chunk)
            if eof:
                return decode_final_workspace(bytes(data), base=base,
                                              sandbox_id=session.sandbox_id,
                                              session_id=session.session_id)
    finally:
        session.close()
