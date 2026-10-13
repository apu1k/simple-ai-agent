# Copy-only image finalization (candidate; NOT Gate A)

This operator-only workflow removes Ubuntu-console typing. Python authors fixed
NoCloud data media and invokes fixed Hyper-V scripts; a Linux live recovery boot
inspects/finalizes **only a fresh disk copy**, then returns bounded JSON over COM1.
The operator CLI is not an unattended installer or permission to launch a VM.
A separate [protected inspect-only adapter](privileged_image_inspection.md) exposes
only inspection after distinct next-turn authorization, reviewed installation and
UAC. It never exposes finalization/publication or elevates checkout code.

**Validation boundary:** offline fixtures validate rendering, guards, deletion
policy and receipts. Live ISO/NoCloud `runcmd` compatibility, UART/pipe behavior,
actual ACL transitions and Linux mount/unmount behavior remain unverified.
The first authorized run must be **inspect**, not finalize or publication.
A timeout is not evidence that the VM or guest worked.

## Before a real run

Separately authorize the exact source, a **fresh current source SHA-256**, the
reviewed Ubuntu recovery ISO/path/digest/provenance, an initially empty external
workspace, appropriate Hyper-V permissions and the fixed code at its reviewed
commit. Do not reuse the pre-028 source digest from the diagnostic record.
Preserve completed diagnostic receipts and the diagnostic source itself first;
the `--evidence-preserved` flag records an operator decision, not an evidence audit.

Require private host-only workspace-parent ACLs (operator, SYSTEM,
Administrators), sufficient space for another copy and no concurrent operator or
runner. The wrapper checks native control ACLs without repairing them. Review
COM1 pipe access separately; code does not attest pipe ACLs. Do not elevate the
whole AI application or use WSL as recovery infrastructure.

All source-disk VM references must be OFF; the source must be an unattached,
parentless dynamic 20 GiB VHDX. The script holds a read-sharing lock that denies
source writes/deletion during copying and maintenance, checks the copy against
the source digest, and rechecks that the source is unchanged. Retained original
VMs, disks, media, claims, manifests and the `018` lock are never changed.

## 0. Collect fresh host evidence without launching anything

Use the operator-only collector before choosing the inspection command:

```powershell
python -B -m night_shifts.host_evidence `
  --source '<reviewed diagnostic VHDX>' `
  --recovery-iso '<reviewed Ubuntu live ISO>' --recovery-iso-sha256 '<reviewed SHA-256>' `
  --workspace '<proposed external workspace>'
```

This prints bounded JSON to stdout; it does not create report/workspace files,
control claims, media or VMs, mount disks, modify ACLs, or elevate. Keep the report
private: it includes local resource paths and source-VM names/GUIDs. Source
references must be OFF and the VHD unattached/suitable before hashing. Temporary
read-sharing handles deny content writes/deletion during hashes; current source
SHA-256 is discovered rather than supplied from an old receipt. The recovery ISO
hash must match the independently reviewed value. Workspace emptiness, native
private ACL policy and physical space are checked without repair.

A missing/unsafe workspace is reported as a blocker but does not prevent a safe
source snapshot; the directory is never created automatically. Hyper-V query
access may require a dedicated terminal with appropriate permissions. Do not
run the AI application elevated. `blocked`/exit code 2 is not permission to fix,
stop or start anything. `snapshot_ready_for_review`/exit code 0 is only an input
snapshot: create/start permission, guest contents, pipe ACLs and provenance are
not attested, and **launch is never authorized**. Actual inspection rechecks the
inputs/state and needs separate authorization. This collector is offline-tested;
native real-host observations still need recording.

## 1. Inspect automatically

Proposed operator invocation after the inputs and launch are separately approved:

```powershell
python -m night_shifts.image_finalization inspect `
  --source '<reviewed diagnostic VHDX>' --source-sha256 '<current SHA-256>' `
  --recovery-iso '<reviewed Ubuntu live ISO>' --recovery-iso-sha256 '<SHA-256>' `
  --workspace '<new empty private external directory>' `
  --authorize-maintenance --iso-provenance-reviewed --evidence-preserved
```

There are no Ubuntu login/console commands. The new generation-2 recovery VM has
2 CPUs, explicit fixed 2 GiB memory with read-back, no network adapter, GSI
removed from use, no checkpoints and Linux Secure Boot. Its boot order contains
**only** the pinned live DVD: it must not boot the installed target. CIDATA is
data-only, contains no credentials and uses ordinary `runcmd`, **not autoinstall**;
no target program, chroot, mkfs, package installation or download is executed.

The Linux guard requires a Hyper-V live overlay root, the exact NoCloud instance
ID, only loopback networking and exactly `/dev/sda` (20 GiB) with vfat `/dev/sda1`
and ext4 `/dev/sda2`. An existing source mount, different layout or identity
refuses. Inspection sets block devices read-only and mounts ext4 `ro,noload`.
It checks completed cloud-init and returns diagnostic names/code hashes, never
private-key, history or log contents. Only the copy is exposed to recovery.

An external `<id>.control/manifest.json` and permanent `launch.claim` bind the
attempt. A successful inspection is `inspected_not_accepted`; the copy/media are
retained. The recovery VM is removed only after its result/unmount and host stop
are observed. Hyper-V attachment may change copied VHDX metadata even during a
read-only filesystem inspection; do not assume its final hash equals the source.

## 2. Review the profile, then finalize a NEW copy

Build a JSON object mapping exact diagnostic **regular-file** paths to the code
hashes returned by inspection. The reviewed original `027` procedure used:

- `etc/night-shift-diagnostic-027/original-night-shift-protocol-test.service`
- `etc/night-shift-diagnostic-027/operation.json`
- `etc/night-shift-diagnostic-027/prepared.json`
- a vendor debug-shell enable link in `sysinit.target.wants` (verified/removed by
  fixed policy, not an arbitrary profile entry).

The original-unit backup must also match the pinned current service bytes. Any
additional override/artifact needs explicit review; unknown paths, directories,
symlink parents, different hashes or credentials block finalization. Profiles
cannot request arbitrary guest path deletion. No wildcard cleanup of systemd
configuration is permitted.

Run the same CLI with `finalize --profile '<reviewed profile.json>'` and a **new
empty workspace**. The source remains the preserved initialized diagnostic disk,
not a previously attempted maintenance copy. The complete preflight/deletion
plan is checked read-only before the copy's writable journal-replay transition,
and rechecked afterward before file mutations.

The fixed cleanup restores the exact protocol unit, removes reviewed diagnostic
files/debug enablement, masks debug-shell, removes generated SSH host keys
without reading their contents, and clears logs, apt cache, cloud instance state,
DHCP state, random seed and listed root histories. An empty authorized_keys is
removed; nonempty credentials refuse. `/etc/cloud/cloud-init.disabled` is
preserved so completed initialization is not rerun; installer instance config is
removed, machine-id is emptied and the D-Bus alias restored.

Post-cleanup checks reuse the root-ownership/payload, locked-account,
Python/systemd, enabled-unit/getty, serial-console and SSH policy auditor. They
also check diagnostic/state removal and marker preservation. The target is
flushed, ordinarily unmounted and all source block devices observed read-only
before success is emitted. This is a finite policy audit, not a proof that every
possible credential or malicious installed file is absent.

Successful state: `finalized_not_accepted`, **not an accepted runtime base**.

## 3. Separately accept and publish

Independently review the finalization receipt/audit and record the manifest's
SHA-256. Publication is a separate authorization:

```powershell
python -m night_shifts.image_publication `
  --manifest '<finalized host-only manifest>' --manifest-sha256 '<reviewed SHA-256>' `
  --destination-directory '<separate private external directory>' `
  --authorize-publication --accept-audit
```

An inspection, uncertain cleanup or failed audit cannot be published. The export
script requires the copied disk unattached and unreferenced by a VM, locks it,
checks its accepted hash, and creates a fresh `night-shift-protocol-<id>.vhdx`.
It applies a protected DACL to **only the new export** (operator read/execute;
SYSTEM/Administrators full control), sets/read-backs its read-only attribute and
DACL, and independently checks its digest again from Python. Trusted admins can
still change this policy: it is not cryptographic immutability.

A separate permanent `publication.claim` prevents retries. The sibling `.json`
contains accepted provenance and `gate_a: unrun`. A VHDX without completed
provenance is not accepted, even if copying succeeded. Never export into worker
storage or repair retained source ACLs. Publication does not start a VM or run
Gate A; a disposable Gate A workspace and pipe-policy review remain separate.

## Failure handling

Connect, serial write and bounded receipt read have deadlines. JSON must echo the
fresh identity/mode and successful unmount; malformed/oversized/mismatched data
never accepts an image. Host operation failures retain a sanitized phase label
when available: COPY, CREATE, BOOT, CHANNEL, GUEST, STOP, VERIFY or REMOVE.
A normally caught failure also attempts a bounded create-new `host.failure.json`
in the host-only control directory (or the protected adapter's request-specific
failure receipt). CHANNEL substages distinguish pipe creation/connection, security
compilation/query/parsing, VM SID resolution, ACL validation and handshake
preparation/write/wait. Only fixed reason codes and optional numeric Windows
errors are retained; arbitrary exception text and guest output are discarded.
Exact-owned failure-stop read-back may record `off_observed`, but never upgrades
UNKNOWN to successful unmount/inspection, VM removal or retry authorization.
Missing, oversized, malformed or identity/mode/phase-mismatched failure receipts
are not propagated. Failure receipts do not amend or replace the GUID receipt.

Normal host failure attempts an exact-ID/owner-bound recovery stop, retaining the
VM/config/copy/media for investigation. If the supervising PowerShell process is
killed or times out, that stop may not occur: status remains **UNKNOWN**. Likewise,
partial publication stays unknown with its permanent claim. Inspect exact owned
resources; never retry, release claims, remove old locks or perform broad cleanup
automatically. No root-console, networking or safety-policy relaxation is a
fallback. Live validation and actual cleanup evidence are still required.
