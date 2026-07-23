# Night-shift Hyper-V backend

Phase 3 uses **Hyper-V on Windows** as the first local VM backend. The process backend remains available only for fast protocol tests and is not a security boundary.

## Implementation status

Phase 3A defines the backend-independent sandbox lifecycle, durable sandbox records, resource policy, and the worker `plan` setting. It does **not** create or run a VM yet. The next Phase 3 slice will implement the Hyper-V controller and host–guest transport.

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
- automatic shutdown after the job deadline or loss of the host controller.

Pin and record the image SHA-256 digest. The controller must reject an unexpected image digest rather than silently using a changed image.

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
