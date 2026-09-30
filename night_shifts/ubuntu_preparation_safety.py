"""Shared GUID and exclusive-operation guards for preparation launch/discard.

These are local input/coordination checks, not host isolation evidence. An
administrator must still review directory ACLs and exclude other host actors.
"""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from night_shifts.hyperv_image_preflight import _checked_path
from night_shifts.ubuntu_image_preparation import PreparationError

_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def checked_vm_guid(value: object) -> str:
    """Require a canonical, nonzero host-observed GUID, never derive from name."""
    if not isinstance(value, str) or not _GUID.fullmatch(value) or uuid.UUID(value).int == 0:
        raise PreparationError("VM GUID must be a nonzero canonical lowercase GUID")
    return value


@contextmanager
def preparation_operation(workspace: Path, operation: str) -> Iterator[None]:
    """Exclude overlapping launch/retirement wrappers with an exclusive file.

    A normal return or exception releases ONLY this exact guard. A process
    crash or failed release leaves it for manual inspection, not stale-lock
    guessing. Permanent launch/retirement claims are never removed here.
    """
    if operation not in {"launch", "retire"}:
        raise PreparationError("unsupported preparation operation")
    root = _checked_path(workspace, "preparation operation workspace")
    checkout = Path(__file__).resolve().parents[1]
    if not root.is_dir() or checkout == root or checkout in root.parents:
        raise PreparationError("operation workspace must be outside checkout")
    guard = root / "vm-operation.lock"
    token = (json.dumps({"operation": operation, "token": uuid.uuid4().hex}, sort_keys=True) + "\n").encode("ascii")
    try:
        with guard.open("xb") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
            identity = os.fstat(stream.fileno())
    except FileExistsError as exc:
        raise PreparationError("preparation operation busy or interrupted; inspect exact workspace before retry") from exc
    except OSError as exc:
        raise PreparationError("preparation operation guard uncertain; inspect exact workspace") from exc
    try:
        yield
    finally:
        try:
            current = guard.lstat()
            if not stat.S_ISREG(current.st_mode) or current.st_size != len(token) or (
                current.st_dev, current.st_ino
            ) != (identity.st_dev, identity.st_ino):
                raise PreparationError("preparation operation guard changed; inspect, never delete blindly")
            with guard.open("rb") as stream:
                if stream.read(len(token) + 1) != token:
                    raise PreparationError("preparation operation guard changed; inspect, never delete blindly")
            guard.unlink()  # only our transient, identity/content-verified guard
        except OSError as exc:
            raise PreparationError("preparation operation guard release uncertain; inspect exact workspace") from exc
