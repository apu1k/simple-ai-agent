# Night-shift Hyper-V backend

Phase 3 uses **Hyper-V on Windows** as the first local VM backend. The process backend remains available only for fast protocol tests and is not a security boundary.

## Implementation status

The trusted-host controller now implements Hyper-V prerequisite checks, pinned-image verification, generation-2 VM creation, disposable differencing disks, resource configuration, status, start, pause, stop, and idempotent destruction. Every operation derives names and paths from a trusted sandbox ID and the PowerShell scripts verify the persisted VM ownership marker before acting.

Task, event, and result handling uses the existing versioned JSONL protocol through a narrow `HyperVTransport` interface. A Linux-compatible host transport is available through an explicitly configured VM COM1 ↔ Windows named-pipe channel. The default transport still fails closed. A reviewed guest image configured to consume `/dev/ttyS0` is required before real tasks can run.

## Host prerequisites

- Windows 11 Pro, Enterprise, or Education with hardware virtualization enabled in firmware.
- Hyper-V and its PowerShell management module enabled.
- An administrator-managed, generation-2 Linux base image stored outside the repository.
- A dedicated Hyper-V virtual switch. Start with no external network connectivity; network access must be an explicit policy exception.
- Enough host capacity for the configured CPU, memory, and differencing-disk limits.
- The orchestrator host process must have narrowly scoped permission to manage only VMs carrying the night-shift ownership marker. Do not expose raw Hyper-V commands to either agent.

Useful host checks (run manually from an elevated PowerShell prompt):

```powershell
Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
Get-Command Get-VM, New-VM, Start-VM, Stop-VM, Remove-VM
Get-VMSwitch
```

## Base-image requirements

The Linux image must be built and reviewed separately. It must contain only the guest worker bootstrap and required tools, with:

- no personal files, host mounts, publishing credentials, SSH private keys, or cloud credentials;
- no default password or remotely accessible administrator account;
- cloud metadata and private/local network ranges blocked;
- a read-only base disk and one disposable differencing disk per job;
- guest services limited to the narrow versioned task/event/result transport;
- COM1 exposed as `/dev/ttyS0`, with any serial console/getty disabled and the worker bootstrap holding exclusive access;
- terminal echo, input translation, and output translation disabled on `/dev/ttyS0` so UTF-8 JSONL bytes are not altered;
- automatic shutdown after the job deadline or loss of the host controller.

Pin and record the image SHA-256 digest. `HyperVSandboxController` verifies it before every creation and rejects an unexpected image rather than silently using a changed image. The base image virtual disk must be no larger than the job's configured disk limit.

## Default sandbox policy

`SandboxSpec` currently defaults to 2 virtual CPUs, 4096 MiB memory, a 20 GiB disposable disk, and networking disabled. These are host-enforced limits, not instructions to the model.

## Agent plan

Every night-shift job has an `AgentPlan`:

- `flex` (default): permits cost-optimized, delay-tolerant model processing;
- `normal`: requests standard low-latency processing for a faster implementation.

The plan is persisted with the job and included in the version-1 worker task. It does not weaken sandbox, tool, network, approval, or publication policies. Provider-specific mapping will be implemented with the restricted worker runtime in Phase 4.

## Safety invariants for the controller

1. Generate VM names and paths from trusted sandbox IDs, never task text.
2. Invoke fixed PowerShell commands with structured arguments; do not build shell command strings.
3. Verify ownership markers before every start, pause, stop, or destroy operation.
4. Deny networking unless the persisted policy explicitly enables an approved switch/profile.
5. Persist the external VM ID immediately after creation so controller restart cleanup can find it.
6. Make stop and destroy idempotent and reconcile orphaned records at startup.
7. Destroy differencing disks after completion, cancellation, timeout, and failed provisioning while retaining operational records and approved artifacts.

## Trusted configuration example

```python
from pathlib import Path

from night_shifts.backends import (
    HyperVConfig,
    HyperVSandboxController,
    HyperVSerialTransport,
)
from night_shifts.storage import SandboxStore

config = HyperVConfig(
    base_image=Path(r"C:\ProgramData\NightShift\images\worker.vhdx"),
    base_image_sha256="<64-character reviewed digest>",
    workspace_root=Path(r"C:\ProgramData\NightShift\sandboxes"),
    switch_name=None,  # networking disabled by default
)
controller = HyperVSandboxController(
    config,
    SandboxStore(Path(".agent_runtime/operations.sqlite3")),
    transport=HyperVSerialTransport(),
)
controller.check_prerequisites()
```

Run the host process with only the permissions needed for its owned VMs and workspace. Do not accept these paths, the image digest, switch name, PowerShell executable, or pipe name from an agent task.

## Serial guest channel

Each VM's COM1 port is attached to `\\.\pipe\night-shift-<sandbox-id>-com1`. The name is derived from the orchestrator-generated sandbox ID and passed to a fixed `Set-VMComPort` invocation during creation. Task text cannot influence it. `HyperVSerialTransport` opens that pipe directly without a shell, sends exactly one bounded UTF-8 task frame, streams bounded event frames, and retains exactly one terminal result frame.

Inside the reviewed Linux image, the worker bootstrap must open `/dev/ttyS0` in raw mode, read one protocol-version-1 task line, and write protocol-version-1 event/result lines. The image build must disable `serial-getty@ttyS0.service` (and any kernel serial console) to prevent login prompts or echoed bytes from corrupting the protocol. The host transport defaults to a 1 MiB maximum frame and does not add network access or credentials.

The serial channel is transport isolation, not the complete worker sandbox. The reviewed image, restricted worker runtime, deadline/cancellation adapter, and guaranteed VM cleanup remain required before untrusted work is enabled.
