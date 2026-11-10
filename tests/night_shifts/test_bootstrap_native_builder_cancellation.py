"""Ordinary native compiler cancellation; never launch produced executables.

Reuses the random-tree fixture whose cleanup requires an explicitly known
outcome and unchanged uncertainty registries. No live owner registry is reset.
"""
from __future__ import annotations

import time

import pytest

from night_shifts import bootstrap_native_build_owner as owner
from night_shifts import bootstrap_native_builder as builder
from tests.night_shifts.test_bootstrap_native_builder import _native_case


def test_native_cancellation_after_actual_resume_stops_exact_job_and_observes_root_and_job_absence(monkeypatch):
    original, recorded = builder._WindowsBuildKernel, []
    cancelled = False

    class CancelAfterResume(original):
        def __init__(self, window):
            super().__init__(window)
            self.stage_lease = None
            self.stops = 0
            recorded.append(self)

        def prepare(self, recipe):
            self.stage_lease = super().prepare(recipe)
            return self.stage_lease

        def resume(self, thread):
            nonlocal cancelled
            result = super().resume(thread)
            assert result == 1
            cancelled = True
            return result

        def stop(self, job):
            self.stops += 1
            return super().stop(job)

    monkeypatch.setattr(builder, '_WindowsBuildKernel', CancelAfterResume)
    with _native_case() as case:
        with pytest.raises(owner.ValidatorBuildOwnerRefused) as caught:
            builder.build_validation_candidate(
                case.review, source_files=case.sources, toolchain_files=case.tools,
                deadline=time.monotonic() + 25, cancelled=lambda: cancelled,
            )
        assert type(caught.value) is owner.ValidatorBuildOwnerRefused
        assert str(caught.value) == 'build_cancelled'
        assert len(recorded) == 1
        kernel = recorded[0]
        assert kernel.created == kernel.stops == 1 and len(kernel.jobs) == 1
        assert kernel.jobs[0].root_exited and kernel.jobs[0].empty and kernel.jobs[0].closed
        assert kernel.stage_lease.closed and all(handle.value == 0 for handle in kernel.stage_lease.all)
        assert case.stage.exists()  # transaction did NOT remove partial staging
        case.clean = True
