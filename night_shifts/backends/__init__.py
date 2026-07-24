"""Execution backends for night-shift workers."""

from night_shifts.backends.base import WorkerBackend
from night_shifts.backends.hyperv import (
    HyperVConfig,
    HyperVError,
    HyperVSandboxController,
    SubprocessPowerShellRunner,
)
from night_shifts.backends.hyperv_serial import (
    HyperVSerialTransport,
    WindowsNamedPipeConnector,
)
from night_shifts.backends.process import ProcessWorkerBackend

__all__ = [
    "HyperVConfig",
    "HyperVError",
    "HyperVSandboxController",
    "HyperVSerialTransport",
    "ProcessWorkerBackend",
    "SubprocessPowerShellRunner",
    "WindowsNamedPipeConnector",
    "WorkerBackend",
]
