"""Explicit unelevated fixed-build candidate; never an installer or starter.

Requires separately reviewed source/profile/pins and trusted Windows/.NET plus
builder-runtime/load policy BEFORE use. Matching hashes cannot establish these
prerequisites. No CLI, live tool wiring, pin discovery or production defaults.
"""
from __future__ import annotations

from collections.abc import Callable

from night_shifts import bootstrap_native_build_owner as owner
from night_shifts.bootstrap_native_build_windows import _Window, _WindowsBuildKernel


def build_validation_candidate(
    review: object, *, source_files: object, toolchain_files: object,
    deadline: float, cancelled: Callable[[], bool] = lambda: False,
) -> owner.LocalBuildObservation:
    """Create ONE fresh private stage and compile ONLY the two fixed executables.

    The absolute deadline MUST be from this process's time.monotonic domain;
    all preparation, both compiles, verification and closes share that window.
    No output is installed, published or launched. Files are retained, including
    partial failures. Caller must retain/review the stage, not sweep or retry.

    Return hashes are local observations, NOT independent finished-artifact pins
    or acceptance. Disposal/reconciliation is intentionally not exposed here.
    Unknown process/close outcomes retain the actual owner and held inputs.
    This candidate has no independent out-of-process watchdog; it cannot bound
    a blocked OS/CLR call or survive its own death. It is not a protected route.
    """
    if not callable(cancelled):
        raise owner.ValidatorBuildOwnerRefused('build_cancellation_context')
    window = _Window(deadline, cancelled)
    kernel = _WindowsBuildKernel(window)
    transaction = owner._ValidatorBuildOwner(
        review, source_files=source_files, toolchain_files=toolchain_files,
        kernel=kernel, clock=window.seconds, deadline=deadline,
    )
    return transaction.run()
