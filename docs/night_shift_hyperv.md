# Night-shift Hyper-V backend

Phase 3 uses **Hyper-V on Windows** as the first local VM backend. The process backend remains available only for fast protocol tests and is not a security boundary. The current host-managed worker MVP decision and verified gates are in [`night_shift_plan.md`](night_shift_plan.md) and [`night_shift_status.md`](night_shift_status.md); [`night_shift_worker_runtime.md`](night_shift_worker_runtime.md) documents the existing guest/workspace prototype.

## Implementation status

The trusted-host controller now implements Hyper-V prerequisite checks, pinned-image verification, generation-2 VM creation, disposable differencing disks, resource configuration, status, start, pause, stop, and idempotent destruction. Every operation derives names and paths from a trusted sandbox ID and the PowerShell scripts verify the persisted VM ownership marker before acting.

Task, event, and result handling uses the existing versioned JSONL protocol through a narrow `HyperVTransport` interface. A Linux-compatible host transport is available through an explicitly configured VM COM1 ↔ Windows named-pipe channel. The default transport still fails closed. A reviewed guest image configured to consume `/dev/ttyS0` is required before real tasks can run.

## Host prerequisites

- Windows 11 Pro, Enterprise, or Education with hardware virtualization enabled in firmware.
- Hyper-V and its PowerShell management module enabled.
- An administrator-managed, generation-2 Linux base image stored outside the repository.
- No switch attachment for the protocol-test VM (`switch_name=None`, `network_enabled=False`); any future network profile requires a separately reviewed switch and explicit policy exception.
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

`SandboxSpec` currently defaults to 2 virtual CPUs, 4096 MiB startup memory, a 20 GiB virtual disk size, and networking disabled. `create.ps1` sets CPU count, disables dynamic memory, resizes the differencing disk when applicable, and omits a switch when networking is off. Virtual disk size is **not** a verified host-storage quota; cgroup/process/lifetime and disk growth enforcement must be reviewed on a real host before treating resource limits as comprehensive.

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
6. Make stop and destroy idempotent. Scope reconciliation to precisely owned IDs; an unscoped startup sweep is unsafe while another runner may be active.
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
)
channel = HyperVSerialTransport()  # separate whole-task WorkerChannel, not a controller argument
controller.check_prerequisites()
```

`SandboxWorkerBackend(controller, channel)` composes the old whole-task execution path; the planned host-managed tool session is not yet implemented. The example does not create a VM or enable real jobs.

Run the host process with only the permissions needed for its owned VMs and workspace. Do not accept these paths, the image digest, switch name, PowerShell executable, or pipe name from an agent task.

## Serial guest channel

Each VM's COM1 port is attached to `\\.\pipe\night-shift-<sandbox-id>-com1`. The name is derived from the orchestrator-generated sandbox ID and passed to a fixed `Set-VMComPort` invocation during creation. Task text cannot influence it. `HyperVSerialTransport` opens that pipe directly without a shell, sends exactly one bounded UTF-8 task frame, streams bounded event frames, and retains exactly one terminal result frame.

Inside the reviewed Linux image, the worker bootstrap must open `/dev/ttyS0` in raw mode, read one protocol-version-1 task line, and write protocol-version-1 event/result lines. The image build must disable `serial-getty@ttyS0.service` (and any kernel serial console) to prevent login prompts or echoed bytes from corrupting the protocol. The host transport defaults to a 1 MiB maximum frame and does not add network access or credentials.

The serial channel is transport isolation, not the complete worker sandbox. The reviewed image and restricted worker runtime remain required before untrusted work is enabled.

## VM-backed execution adapter

`SandboxWorkerBackend` connects the backend-independent worker interface to a `SandboxProvider` such as Hyper-V. It polls a monotonic deadline during startup and guest-event streaming, but synchronous provisioning, task send, result retrieval, callbacks and cleanup are **not** fully covered by that deadline. It reads guest events on a daemon thread, persists guest/orchestrator events when an `EventStore` is supplied, and attempts destruction on success, cancellation, timeout and most failures. This prototype does not yet guarantee interruptible I/O or failure-proof cleanup.

A caught cleanup failure becomes a failed worker result; an event logging/callback exception can still interrupt later cleanup and must be fixed before live work. Individual fixed PowerShell commands have their own timeout, not a global cleanup deadline.

## Restart reconciliation

The legacy controller's `reconcile()` inventories Hyper-V through a fixed script and recognizes a VM only when both its strict `night-shift-<32 lowercase hex characters>` name and its exact `night-shift-owner:<sandbox-id>` marker agree. It validates the complete inventory before changing anything. Do **not** run unscoped startup reconciliation alongside another runner; the controller does not prove which runner owns a live VM.

Because guest transport sessions cannot be resumed safely after the orchestrator process is lost, reconciliation destroys every non-final persisted Hyper-V sandbox, cleans its trusted workspace, and marks its durable record destroyed. It also removes strictly owned host VMs that have no database record. VMs with unrelated names, missing or mismatched markers, or conflicting persisted backend identities are never touched.

Cleanup continues after an individual failure and returns a `HyperVReconciliationReport`. The caller must check `report.succeeded` (and log/alert on `report.errors`) before enabling job execution. Reconciliation deliberately does not require the base-image digest to pass: a missing or changed creation image must not prevent removal of already-running disposable VMs. Hyper-V prerequisites and ownership checks still fail closed.

For targeted recovery/tests, `reconcile(sandbox_ids=frozenset({...}))`
restricts cleanup to exact sandbox IDs. The legacy startup guidance to use unscoped `reconcile()` must **not** be applied while another runner may own live VMs: the current controller cannot distinguish a different live runner's owned sandboxes. Implement durable runner ownership before production startup reconciliation.

## Phase 3 protocol-test image

Guest assets:

- `night_shifts/guest/protocol_test_bootstrap.py`
- `night_shifts/guest/night-shift-protocol-test.service`

The bootstrap locks `/dev/ttyS0` in raw mode and accepts only
`phase3-protocol-success` or `phase3-protocol-sleep:<seconds>`. It never executes
task text or repository code.

Image checklist:

1. Use a minimal generation-2 Linux VM with Python 3, networking off, and no
   personal files, credentials, host mounts, remote login, or default password.
2. Create locked user `night-shift`; grant only serial-device access.
3. Install the bootstrap as root-owned/non-writable and enable the supplied unit.
4. Disable `serial-getty@ttyS0`; remove `console=ttyS0` from kernel arguments.
5. Verify raw exclusive serial access, fail-closed objectives, disconnect
   shutdown, and the six-hour service limit.
6. Clear logs, caches, history, machine identity, DHCP state, SSH host keys, and
   installer artifacts. Review the filesystem, shut down, and store VHDX read-only.
7. Record provenance and pin the digest:

```powershell
(Get-FileHash 'C:\ProgramData\NightShift\images\worker.vhdx' -Algorithm SHA256).Hash
```

## Opt-in real-host tests

Follow the [Gate A preflight, enforcement matrix and observation record](night_shift_hyperv_preflight.md) first. Normal runs skip `test_hyperv_real_host.py`. On an operator-approved dedicated host:

```powershell
$env:NIGHT_SHIFT_HYPERV_INTEGRATION = '1'
$env:NIGHT_SHIFT_HYPERV_BASE_IMAGE = 'C:\ProgramData\NightShift\images\worker.vhdx'
$env:NIGHT_SHIFT_HYPERV_BASE_IMAGE_SHA256 = '<reviewed digest>'
$env:NIGHT_SHIFT_HYPERV_WORKSPACE = 'C:\ProgramData\NightShift\integration-sandboxes'
python -m pytest -q tests/night_shifts/test_hyperv_real_host.py
```

The suite configures networking off and covers prerequisites, successful and rejected-objective serial exchanges, timeout/cancellation, forced-stop disconnect cleanup, host-observed VM absence, disk removal, and exact-ID orphan reconciliation. Actual adapter state and pipe ACLs require separate host inspection.
It never enables Hyper-V, elevates, restarts, creates switches, or downloads an
image. Optional timeout/resource variables are listed in the test file.

Real-host results remain pending until a reviewed VHDX, approved host configuration, and operator authorization are supplied. Mocked tests and the fail-closed default transport remain active. The named-pipe ACL and session/VM binding have not yet been validated as a secure per-tool channel.
