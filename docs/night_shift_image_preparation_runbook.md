# Candidate one-time Ubuntu preparation runbook (NOT launch authorization)

This is a review procedure for a separate preparation VM, not Gate A itself.
**Current handoff (2026-10-09): three earlier failed installer candidates are retained;
a fourth candidate passed both native target audits and review release, and its
separate diagnostic disk copy completed cloud-init and the recorded account/SSH-server
checks. No cleaned/frozen base image exists; Gate A remains unrun.** The operator
reports the diagnostic VM OFF after orderly shutdown. Original candidates, media,
backups, manifests, permanent claims and the original `018` lock remain retained.
See the [diagnostic record](night_shift_image_diagnostic_record.md) for identities,
receipt hashes, observed failures/fixes, evidence limitations and next boundaries.

A candidate [copy-only, no-console image finalization workflow](night_shift_image_finalization.md)
now provides separate inspection, reviewed cleanup and publication entry points.
Its offline tests are not live recovery/NoCloud/serial evidence. First authorize an
inspection-only run; neither this implementation nor code approval authorizes any
VM launch, original-candidate change or Gate A run.

## Historical failed installer attempts

### First attempt: likely CRLF shell failure

The fixed-memory correction and host-only version-2 control migration were
verified before a separately approved exact-GUID launch. The operator checked
the live instance ID, sole 20 GiB disk, loaded autoinstall configuration and both
DVD hashes before approving disk modification. Subiquity then failed in the
first late-command with exit status 2, before the target-review checkpoint.
Host extraction confirms all 59 target-installer lines were CRLF, including
`set -eu\r\n`; this is the likely shell failure, not a guest-log-confirmed cause.
The existing seed and bundle faithfully hashed those unsuitable Linux bytes.

On 2026-10-03 the operator's read-only inspection reports the exact VM
`1691b381-a69b-4c6c-95bf-c3000d169191` OFF throughout, fixed 2 GiB RAM, 2 CPUs,
one Dynamic/parentless/not-host-mounted 20 GiB VHDX, disconnected networking,
Guest Service Interface disabled and zero GPU/DDA/Fibre Channel devices.
The installer DVD slot is now empty; the old CIDATA seed remains attached.
The operator recalls shutting it off without manually ejecting the installer;
the cause of the empty slot remains unresolved. Do not silently repair it,
restart the VM to retrieve logs, or bypass its retained permanent launch claim.
The manifest remains `installer_vm_started_not_reviewed`, not success.
Keep this failed candidate and its evidence intact; never hot-patch/retry its
payload or promote its disk to a trusted image. Gate A remains unrun.

### Second attempt: confirmed busy seed mount (2026-10-04)

A fresh LF-only candidate used sandbox `8e3e0fce76414f0495b70bccbbef559c`,
VM GUID `a1f7ef97-692d-4755-b780-5c70c425fa7a`, the same pinned Ubuntu ISO,
bundle SHA-256 `fc8ac8a92e9d3eb787180583ae38f47bbd4c4532d0ab612aef4a3b994ee01b5d`
and identity-bound CIDATA SHA-256
`f18f5665c40643ed5e202b6ce9b376a1f3422d6587f5d248afb7ce9b0d4d39d2`.
The operator's launch receipt observed the exact VM running, fixed 2 GiB RAM,
2 CPUs, one new 20 GiB disk, both DVDs and disconnected networking. The operator
verified root inspection, the live instance ID (using an exact shell comparison
after a transcription omission), disk inventory, loaded YAML and both guest DVD
hashes before answering the installer confirmation.

Subiquity's first late-command then failed with exit status 32. Read-only guest
journal inspection shows both of these messages at guest-displayed 06:15:16:

- `Candidate target service installed; inspect guest before freezing image.`
- `umount: /run/night-shift-protocol-seed: target is busy.`

The wrapper had changed its parent cwd into the mounted seed and attempted to
unmount without leaving it. This is a confirmed wrapper cleanup defect, not a
second CRLF diagnosis. The target script reached its final message, but the
manual target-review command did not run; this is NOT a reviewed installation.
The correction scopes checksum verification and payload execution to a subshell,
which must exit successfully before the parent performs an ordinary unmount.
Keep `set -eu`, read-only mount flags and failure propagation; do not introduce
lazy/forced unmount, ignored errors, an approval marker or an in-place retry.

The operator approved orderly live-installer power-off and reports the VM OFF.
This is an operator observation, not a new agent-side Hyper-V inspection. Keep
the candidate, its host media and permanent launch claim intact. Its saved status
remains `installer_vm_started_not_reviewed`, not prepared/accepted/retired.
Neither candidate is a trusted image. Subsequent preparation must use fresh
identity/disk and newly reviewed seed; unchanged fixed bundle bytes may be reused
after verification. No shutdown/cleanup action or new launch is implied by code
approval. Gate A remains unrun.

Keyboard troubleshooting note: tty1 exhibited Meta-style input and numeric
argument prompts. Windows Alt-release injection did not recover it; Hyper-V
reported all modifiers up, and `Msvm_Keyboard.Reset` returned 1 (unsupported).
Switching to the already-open tty2 restored usable typing. These observations do
not establish a hardware/modifier cause; try the existing alternative live shell
before further input-injection scripts. No guest commands were sent by those
keyboard scripts. Console configuration was reset manually by the operator.

### Third attempt: review checkpoint expired (2026-10-05)

Sandbox `6584fc35942046dcbeae7953647aca13`, VM GUID
`18e00e9e-e5f0-41e7-b00b-33ace333c83b`, used repository commit
`319c473909c0ed04f7acec61a90ba65c6426c908`, the same reviewed installer and LF bundle,
and corrected seed SHA-256
`9e51f3fe184911beeac613381a7079b682e01ff64780e29e17e65b3e11132b62`.
The operator's start-once receipt observed the exact VM running, fixed 2 GiB RAM,
2 CPUs, one new 20 GiB disk, both DVDs and disconnected networking. Both previous
failed candidates were observed OFF and unchanged. The live instance ID, sole
disk, loaded corrected YAML and both guest DVD hashes were checked before the
operator confirmed disk modification.

`command_0` completed and `command_1` began. The operator's read-only review
found `/target` on `/dev/sda2` (ext4), exact reviewed bootstrap/service hashes,
root-owned mode-0644 files and mode-0755 trusted directories, an enabled service
and serial-getty mask pointing to `/dev/null`. `night-shift` was UID 999/GID 988,
with only its primary group and dialout, a `/nonexistent` home and nologin shell.
All reported local password statuses, including root and the worker, were locked.
No serial-console conflicts were found in live/generated/default GRUB inputs;
Python reported 3.12.3 and openssh-server was not installed. Root's `.ssh` was
empty and no `.ssh` directory was found in target homes. The actual target
cloud-init input was `/target/etc/cloud/cloud.cfg.d/99-installer.cfg`, not the
assumed `/target/var/lib/cloud/seed` directory. It contained a separate target
instance UUID, `users: []`, root/password-SSH restrictions, no package updates,
and the installer's deferred `/etc/cloud/cloud-init.disabled` write.
These observations do NOT establish effective accounts or service behavior
following a first boot.

The guest journal records review start at **13:09:25** and explicit expiry at
**13:39:27**, after 30 minutes 2 seconds. The operator discovered failure upon
returning to tty1 and did not create the approval marker; `ls` confirmed it absent.
This was the intended fail-closed expiry path, NOT a new CRLF/mount failure or an
intended successful test. The manually typed/chat-driven audit was too lengthy
for the configured window. Do not retroactively release it, reset the timer,
rerun the payload, or call the disk a completed image.

The operator reports orderly live-installer power-off. This is an operator
observation, NOT a fresh agent-side Hyper-V OFF inspection. Local protected
control inspection still finds only `manifest.json` and `launch.claim`, status
`installer_vm_started_not_reviewed`, and manifest SHA-256
`d7feac6b60415557de8e59ec2006d6dfa2aa5d64bb2c42161c86b7e63578435c`.
Retain this candidate and both previous failures, media and permanent claims.
The crash-report path was transcribed from the guest; its contents were not
exported or independently inspected. No candidate is accepted or frozen.

The new review procedure below replaces this timed manual exchange with a fixed
read-only audit and a longer finite wait. Repository approval is NOT permission
to build/attach a new seed, create/start another VM, reuse a failed disk, change
retained manifests, retire resources, or boot an installed guest. Each real-host
step remains separately reviewed/authorized. Gate A remains unrun.

### Linux payload bytes and recovery boundary

All fixed guest text must be UTF-8/LF before packaging, lengths and hashes.
Both ZIP assets and the target-installer script use the same CRLF-to-LF
canonicalization, without rewriting checkout files. Invalid UTF-8, a leading
UTF-8 BOM, NUL or remaining lone CR refuses authoring. Git LF attributes help
checkout hygiene, but packaging does not rely on Git or the host platform.
Archive/media inspection compares exact canonical bytes: a legacy CRLF bundle
or seed is stale even if its own hash/checksums are internally consistent.
Do not normalize an untrusted archive during verification or weaken its pinned
hash check. Previously approved live assets are evidence, not overwritten outputs.

Offline newline tests do not prove shell syntax, Subiquity compatibility,
service behavior or a trusted installed image. After code/test review, authorize
new write-once assets and a fresh preparation identity/workspace/disk in separate
bounded steps. Do not reuse the failed disk. Any disposal/retirement remains a
separate approval, and must inspect actual state without repairing media drift.
The operator must separately approve actual paths, independently reviewed
digests, resources, permissions, a time window and exact real-host actions.
The never-started migration procedure below is historical; it is NOT applicable
to this already-launched failed attempt.

## 1. Approval packet and host checkpoints

Record and review:

- Exact Ubuntu installer path, version, SHA-256 and authenticated publisher
  provenance; matching a downloaded checksum without authenticating it is not
  the complete provenance review.
- Current repository commit and fixed guest-bundle path/hash; a fresh combined
  CIDATA seed must match the current renderer/payload and preparation identity.
  Older combined seeds are intentionally stale after a renderer change.
- Dedicated initially empty external workspace, media directory, free space,
  directory ACLs, generation-2 settings, Linux Secure Boot template, CPU/memory
  and virtual disk size. Virtual disk size is not a physical storage quota.
- Exact generated preparation name/owner marker, workspace, configuration path
  and new disk path. Record the actual Hyper-V VM GUID when observing the host.
  Do not reuse a personal VM or attach any host/personal disk.
- No connected switch, no host shares and no concurrent operator/runner changing
  this VM or its files. Creation and combined-seed attachment are separately
  authorized operations; neither existing function starts the VM.
- The exact-owned discard operation and its separate consent, described below.
  It retains storage/evidence, so it does NOT restore an empty workspace.

After creation/attachment, inspect actual host state: notes/name/GUID/config
path, one recorded writable disk, exactly the installer and combined seed DVDs,
no switch attachment, off-state and resources. Compare media digests again.
An uncertain create/attach status needs inspection, never automatic retry.

### Host-only control versus VM-worker storage (version 2)

For workspace `<root>/<32-hex-id>`, authoritative state is now in the exact
sibling `<root>/<32-hex-id>.control`, never beneath worker-writable VM storage.
`record.control` and `record.manifest` expose these derived paths. Version-2
manifests bind both `workspace` and `control`, in addition to exact VM paths,
name/marker, media, resources, status and any observed GUID. Creation records
its unknown state there before the host call. The data/configuration paths and
necessary Hyper-V permissions are unchanged; no control path is passed to a
Hyper-V script. The workspace root must initially be empty and receives two
identity-bound directories during a new approved creation.

The control directory contains only the manifest, pending update, launch and
retirement claims, and operation lock. Native Windows owner/DACL checks require
only the current operator account, SYSTEM and Administrators with simple
FullControl allow entries on control state and its private parent. Ancestors
are checked for untrusted ownership, replacement/deletion-child or ACL-changing
grants. A volume root's ordinary Modify permission is not treated as permission
to rename that root; untrusted delete-child/ACL-changing grants still refuse.
Paths must be link/reparse-free; control files must be regular and single-link.
Unknown entries, unsupported ACEs, broad/worker grants, missing control or drift
stop progress. The checks never modify ACLs. New control directories/files
inherit the reviewed private parent and are checked again; pending replacement
files stay there as well. Real Windows permission evidence is required; choosing
a fake runner never bypasses production permission checks. Fake-host tests
explicitly substitute an ACL model in four named test modules; separate policy
models and a read-only native test do not prove guest isolation.

Attach, launch and retirement use the same host-only operation lock. Permanent
claims and unknown-state rules retain their start/discard protections. Local
launch packets bind the control and manifest paths and refuse a busy lock.
Metadata/claims in the VM-worker workspace are untrusted legacy files/decoys:
new code neither adopts, updates nor deletes them, and never falls back to them.
Restricting only the old manifest would not protect later replacement files or
claims from its worker-writable parent. Keep necessary worker access to the
VHDX/configuration; do not blindly remove the `vmWorkerProcess` capability.

**Migration of the current VM is NOT authorized by repository-file approval.**
There is no automatic migrator. After this complete batch passes offline review:

1. Reobserve exact GUID `1691b381-a69b-4c6c-95bf-c3000d169191`, name/notes/config,
   generation 2 and OFF state; recheck sole disk, two DVDs, resources, network,
   reviewed digests and exclusive operator use. Never migrate a launched or
   uncertain attempt using this never-started procedure.
2. Require the existing version-1 `created_seed_attached_not_started` manifest,
   SHA-256 `c1f066ba8a669de6563494bb66b462ce30be25030df4692b86749fb3ca3b1c71`,
   exact GUID/config/media bindings and no legacy pending writes, claims or lock.
   Preserve its exact bytes/hash as new write-once private before-evidence.
3. Present a separate approval for the initially absent exact sibling
   `D:\NightShift\build-sandboxes\20ce30aa97c345b58b4a61155a26d72d.control`.
   Validate its private parent and ancestors, create it without reuse or overwrite,
   and independently check the resulting owner/DACL. No permission changes to
   VM data/configuration, D: or other directories are included.
4. Write a new control manifest with only version changed to 2 and exact
   `workspace`/`control` fields added. Preserve all existing status, identity,
   GUID, path, media-hash and resource fields. Retain the legacy workspace copy
   as non-authoritative evidence; it is no longer read by operations. Migration
   is not permission to attach, launch, retire or delete resources.
5. Recheck actual bytes, fields and native control permissions, retain private
   after-evidence and construct a fresh local packet. A changed input, interrupted
   write, collision or uncertain result stops for inspection, never blind retry.

Historical manually authored primary-group evidence disagrees with later native
observations; retain that discrepancy, not a silently rewritten history. The
control policy validates actual owner/DACL, not the historical group string.
A protected control plane does not eliminate Hyper-V escapes or protect against
a compromised administrator/operator/SYSTEM process. Basic-session-only console
use, no redirection, reviewed host integration and separately authorized attended
boot remain required. Gate A remains unrun.

### Explicit fixed-memory configuration and read-back

The approved preparation policy is fixed RAM, not Dynamic Memory. The original
creation script used `Set-VM -DynamicMemory:$false` without reading back memory
state. Operator inspection after attachment reported `DynamicMemoryEnabled=true`
with 2 GiB startup memory. Do not infer fixed allocation from the startup size.
Installed cmdlet metadata identifies `Set-VM`'s `DynamicMemory`/`StaticMemory` as
switches, whereas `Set-VMMemory.DynamicMemoryEnabled` is a Boolean. This metadata
and observation do not establish all parameter-set behavior.

Creation now uses explicit `Set-VMMemory -DynamicMemoryEnabled $false
-StartupBytes $MemoryBytes` and `Get-VMMemory` read-back. Missing state, a different
startup size or anything other than Dynamic Memory disabled throws before create
success. The existing attempt-local rollback/unknown-state rules still apply;
static regression tests are not proof this configuration works on the real host.
The launch script independently rejects Dynamic Memory and never repairs it.

Applying repository edits does not change an existing VM. A separate, exact-GUID
operator settings approval must precede correcting the current OFF VM. Recheck
ownership, name/notes/configuration, disk, media, disconnected adapters and OFF
state first; retain before/after memory observations and verify fixed 2 GiB RAM
without changing the manifest to pretend the host already matches. Do not recreate
the VM, bypass the launch guard or retry an uncertain host operation blindly.

The current integration-service report shows Guest Service Interface disabled;
other enabled integrations are still host/guest communication channels, not
ordinary Windows drive shares. Keep integration/sharing review open before boot.
A subsequent read-only firmware report identifies the first entry as the actual
reviewed installer `DvdDrive` path; generic `EFI SCSI Device` descriptions alone
would not have been sufficient. Host enhanced-session support remains enabled;
no host-global setting changed. Use basic session only, without drive/clipboard
or device redirection, under the separately reviewed attended launch scope.

### Exact configuration root versus Hyper-V VM.Path

`New-VM -Path` takes a configuration **root**, but the observed preparation VM's
`.Path` includes an additional exact VM-name subdirectory. New manifests bind
both `vm_config_root = <workspace>/vm-config` and
`vm_config = <workspace>/vm-config/<exact-preparation-name>`. Creation passes the
root separately and checks the returned VM.Path before accepting success.
Attachment, launch and retirement require the exact derived path, not just a
prefix, an existing root directory or an arbitrary observed path. Unknown layouts
remain a refusal; never discover a directory and silently adopt it.

Old manifests that record the root as `vm_config` are deliberately rejected.
There is no automatic migration/fallback. The following is the historical
configuration-only reconciliation procedure used before control isolation;
it does not make a version-1 workspace manifest usable by new operations.
Current recovery must also satisfy the separately approved version-2 host-only
migration above. For an existing never-started attempt, prepare a separate
exact-file reconciliation proposal **after offline validation**:

1. Independently observe the exact Hyper-V GUID and inspect by that GUID: exact
   name/notes, generation 2, OFF state, single recorded disk, sole installer DVD,
   disconnected adapters, and the unwrapped configuration path. The observed
   path must equal the derived root/name path; do not change host settings.
2. Require `created_not_started`, the old exact root binding, the reviewed media
   hashes/resources and absence of seed/launch/retirement claims, operation lock
   and pending manifest writes. Confirm no operator has started or changed it.
   Unknown/attached/launched attempts need a separately reviewed recovery plan.
3. Retain the manifest's exact original bytes and SHA-256 as write-once private
   evidence. Present a separately approved exact-match change adding
   `vm_config_root`, replacing only `vm_config` with the derived exact path and
   pinning `vm_id` to the independently observed GUID. Preserve all other fields,
   including status; reconciliation does not certify creation or installation.
4. Re-read the approved file and check both bindings, preserved inputs and GUID.
   A changed manifest, missing evidence, claim or uncertain write stops progress;
   no blind retry or host cleanup. Do not apply migration merely by approving
   these repository edits. When present, the recorded GUID is checked/forwarded
   by attachment, packet construction and retirement to reject replacement VMs.

File-edit approval is not seed building/attachment or VM-launch approval. Keep
this existing VM OFF throughout code review and manifest reconciliation.

For operator Python snippets in Windows PowerShell 5.1, feed the reviewed source
through stdin (`$code | & $python -B -`), not a multiline `python -c $code` argument;
native argument quoting can strip embedded double quotes. This is invocation
syntax, never permission to execute a creation or launch snippet. On any error,
retain the original traceback and inspect the manifest/host instead of rerunning.

### Start-once launch packet and function (offline-tested only)

Use the [approval-packet template](night_shift_preparation_launch_approval.md)
for actual operator observations and a separately approved attended time window.
After create/attach, `build_preparation_launch_plan(record, observed_vm_id)` reads
local files and native control permissions and returns an immutable packet. Its `to_review_dict()` contains
paths, pinned media digests, manifest/script hashes, resources and expected host
policy. It does not query Hyper-V, authenticate the publisher, inspect VM-storage
or console/sharing ACLs, or write a packet file. Host-only control owner/DACL and
ancestor permissions are inspected natively. The VM GUID must come from independent trusted host
inspection; it is never derived from the generated preparation name. A packet
fingerprint binds review fields but is not a signature or permission grant.

`launch_image_preparation_vm` has no CLI/agent tool and requires separate launch,
ISO-provenance and host-state review consent. It rechecks the entire packet under
an exclusive launch/retirement guard, then creates a permanent `launch.claim`
and persists the pinned VM GUID/plan fingerprint with `launch_unknown` before
the host command. Changed inputs or a stale packet require new approval.

The fixed script looks up the pinned GUID, verifies exact name/notes/configuration,
off-state, generation, the single dynamic parentless unattached VHDX and its
virtual size, CPU/fixed memory, disabled/absent checkpoints, automatic power
policy, disconnected adapters, two exact DVDs, Linux Secure Boot/installer-first
boot order and both media digests. It does not repair host settings. After its
single start action it observes that same GUID running with its owned disk and
no switch attachment. Unknown host-property representations must stop for manual
inspection, not trigger a weakened guard or automatic configuration repair.

A matching receipt yields `installer_vm_started_not_reviewed`: this observes
only a VM start, not ISO boot, installer acceptance, target review or a good
image. Timeout, crash, mismatched receipt or persistence error leaves claim/
unknown evidence; never auto-retry or automatically discard. The command timeout
bounds the PowerShell call, NOT the running VM lifetime or complete installation.
An operator must attend the graphical console. No supervisor, install-success
poller, media removal, automatic installed-guest first boot or freeze is included.

Attach, launch and retirement share host-only `vm-operation.lock`. Normal returns/handled errors
release only the exact guard created by that wrapper; permanent claims survive.
A process crash, changed guard or failed release leaves it for manual inspection.
Never infer a stale lock from elapsed time. Confirm no active operation and
independently inspect the exact VM/workspace before separately authorizing
resolution. This coordinates these wrappers, not arbitrary Hyper-V actors;
creation and all other operators/runners still require exclusive host use.

## 2. Candidate installer entry (one-time manual confirmation)

After separate launch approval, use the VM's graphical Hyper-V console and the
reviewed installer DVD. The candidate **does not add the `autoinstall` kernel
flag**: retain the installer's disk-modification confirmation for this one-time
build. Canonical documents a separate NoCloud volume as a delivery method, but
that does not prove this exact ISO consumes our seed from a second virtual DVD.

Before confirming disk modification, verify that the live installer selected
the reviewed ID-bound configuration and only the new VM disk. Use the live
installer shell to inspect `/autoinstall.yaml` and the visible block-device
inventory if necessary. If the ISO presents an ordinary interactive install,
an account/password setup, an unexpected disk, networking, or cannot show that
the intended seed is in use, stop and investigate. Do not improvise a manual
install, supply a default login, add a switch, or bypass the disk guard.

Do not add `console=ttyS0`: that conflicts with the final protocol service.
The current seed/installer input tests do not prove disk selection or ISO boot.

## 3. Candidate live-installer inspection checkpoint

The combined seed first runs the fixed `/target` service installer. Inside the
same verified, read-only CIDATA subshell it stages the checksum-covered
`review_protocol_test_target.py` as root-owned mode-0600
`/run/night-shift-target-review.py` in the ephemeral installer, NOT in `/target`.
The parent then unmounts CIDATA normally; no cwd is left inside the mount.
The combined ISO now has seven fixed files and its payload checksums include
the auditor. The existing three-file LF bundle is unchanged; old combined seeds
are intentionally stale and must remain retained evidence, not overwritten.

The separate review late-command rejects any preexisting marker, runs the fixed
read-only auditor before starting the human review clock, then prints a UTC
start, estimated deadline and **3600 one-second polling attempts**. It reports
remaining attempts every 300 polls. This is approximately a **60-minute
cooperative review window**, NOT a host-enforced lifetime deadline; sleep and
command overhead can extend it and the displayed wall-clock estimate is not a
trusted monotonic deadline. Attend installation plus the complete window and
shutdown reserve; do not rely on it to stop a VM when the operator leaves.

The auditor is bound to the live seed identity and current canonical bootstrap
and unit hashes. It checks the mounted sole-disk target, files/trusted parents,
locked system accounts and groups, service enable/mask links, serial-console
configuration, prerequisites, SSH/credential absence and actual installer-written
cloud-init policy. It reads fixed files and only invokes live `findmnt`/`lsblk`;
it runs no target executable, starts no service, accesses no network and writes
no marker or report file. Python is invoked with `-B` to prevent bytecode writes.
Live-installer PyYAML is required for safe cloud-config parsing; missing support,
unknown account/config shapes or inspection errors refuse, without installation
of dependencies or weakening policy. Output contains only fixed check names and
PASS/FAIL summaries, never password hashes, key material, raw YAML or tracebacks.
Offline fixture metadata/commands are models, not real Unix/Hyper-V evidence.

A fresh root-owned regular non-symlink mode-0600 acknowledgment is STILL required.
After observing it, the late-command reruns the read-only audit and releases only
on success. Neither a passing report nor a timeout approves the image. Exhaustion,
audit failure or drift fails installation and must not be bypassed in place.
`shutdown: poweroff` is still requested only after successful completion; no
automatic installed-guest first boot is introduced.

**Prepare this procedure and review its exact source before launching.** At the
checkpoint, use tty2 and one read-only report command (no pipes/quotation marks):

```sh
sudo -n journalctl -b --no-pager --grep=^NS-REVIEW -n 40
```

Review all eight PASS checks, the final RESULT and the current WINDOW/WAIT records.
The same report prefix includes BLOCKED/EXPIRED status, so an initial PASS is not
the last word if the gate subsequently refuses or times out. Do not assume an
old PASS report means the wait is still active: check tty1 for
current state/expiry before any release, and never acknowledge a failed run.
Retain failures and only collect narrow sanitized diagnostics, not another long
unplanned audit. The manual commands below are fallback inspection examples,
not the default multi-round timed procedure. Host/ISO/disk/seed pre-install checks
remain necessary and are NOT replaced by this target audit.

Canonical documents **Help -> Enter shell**, Control+Z or F2 for the live
installer. Validate that console access actually works on our ISO. Confirm
`id -u` is `0` and `/target` is the mounted newly installed guest. This is a
shell in the ephemeral installer, **not a login account added to the target**.
If the shell/checkpoint is unavailable, do not release or freeze the image.

Before releasing the wait, inspect the new target without starting its unit:

- Installed bootstrap and service bytes match the independently reviewed fixed
  sources. Their files and containing trusted directories must be root-owned
  and non-writable by the service identity; files are expected mode `0644`.
- `night-shift` is a system identity with locked password, `/nonexistent` home,
  `/usr/sbin/nologin` shell and only the reviewed primary/dialout groups. Root
  remains locked, and there are no unexpected interactive preparation users,
  SSH credentials, remote-login service or host integration/shares.
- The fixed service is enabled, serial-getty@ttyS0 is masked, and installed GRUB
  settings/generated configuration and the live command line do not contain
  `console=ttyS0`. Python/systemd prerequisites are present.
- Installer logs show that the one-disk guard and fixed late-command completed.
  Inspect actual cloud-init inputs/user configuration; target inspection alone
  does NOT establish the final account state after cloud-init first boot.

Examples of **read-only inspection commands, only inside that approved live
installer shell**, include:

```sh
sha256sum /target/usr/local/lib/night-shift/protocol_test_bootstrap.py \
  /target/etc/systemd/system/night-shift-protocol-test.service
stat -c '%u:%g %a %n' /target/usr/local/lib/night-shift \
  /target/usr/local/lib/night-shift/protocol_test_bootstrap.py \
  /target/etc/systemd/system/night-shift-protocol-test.service
awk -F: '$1 == "night-shift" { print $1, $3, $4, $6, $7 }' /target/etc/passwd
systemctl --root=/target is-enabled night-shift-protocol-test.service
readlink /target/etc/systemd/system/serial-getty@ttyS0.service
```

Expected unit state is `enabled`, and the serial-getty link is `/dev/null`.
These are examples, not an automated audit. Do not print/copy shadow password
fields or raw potentially sensitive logs into chat. Record sanitized findings,
missing evidence and any errors, not just the installer's success message.

Only after the operator has performed the target review, while the wait is
active, the following **live-installer-only** action releases the wait:

```sh
test "$(id -u)" -eq 0 &&
  test ! -e /run/night-shift-image-review-approved &&
  test ! -L /run/night-shift-image-review-approved &&
  (umask 077; : > /run/night-shift-image-review-approved)
```

The marker ONLY permits installer completion/power-off. It is not a signed
review receipt, image certification, first-boot approval or a passed gate.
Observe the actual VM off-state; do not assume that rendering `poweroff` proves
it happened. No automatic first boot, seed/DVD detach or boot-order change is
implemented by this procedure. Those need separately reviewed exact-VM actions.

## 4. Failure/discard: exact-owned VM retirement, disk retained

`night_shifts.ubuntu_preparation_retirement.retire_image_preparation_vm` is an
opt-in trusted Python function, not a CLI/agent tool. It requires both explicit
retirement authorization and acknowledgment that the attempt is being
**discarded**. `provisioning_unknown`/`seed_attach_unknown`/`launch_unknown`
additionally require operator inspection (`unknown_state_reviewed=True`) and an
updated record matching the persisted status. A started or launch-unknown
attempt requires the original GUID/plan-bound `launch.claim`; retirement passes
that GUID to the host script and refuses a same-name replacement. An orphaned
claim or incomplete launch persistence must be manually reconciled first. Missing VM/disk/configuration, ownership
mismatches or incomplete manifests require manual investigation, not a sweep.

Before calling the fixed script, it creates a permanent exclusive
`retirement.claim` and persists `retirement_unknown`. The script validates the
exact preparation name/notes/configuration/single-disk binding, uses the recorded
launch GUID where available (or pins the observed GUID for an older never-launched
attempt), force-powers off if needed, rechecks ownership/off-state by that GUID,
and unregisters only that VM. The receipt must match the recorded launch GUID. It requires a successful inventory query
showing absence of both its GUID and name and verifies disk retention. It does
not require intact installer/bundle media just to discard a failed attempt.

**Force-off can interrupt installation and corrupt the disk. Never use this
operation to freeze a good image.** `retired_vm_disk_retained` means only that
the script reported VM absence and the wrapper still observed its disk; it is
not full filesystem cleanup or image acceptance. The manifest records the
retired VM GUID. The retirement path does not delete the VHDX, seed/installer
media, workspace or Python evidence. Only its transient operation guard is
removed on a normal return/handled exception. Hyper-V may remove its own VM
configuration metadata during unregistration; do not promise those files survive.

Timeout, crash, malformed receipt, incomplete manifest persistence or uncertain
retention leaves the claim/unknown evidence and blocks automatic retry. Inspect
the exact name/GUID/workspace manually. Do not delete the claim to retry blindly,
reuse the retained disk as a trusted base, or call runtime prefix reconciliation
for preparation VMs. Filesystem deletion requires a later separately reviewed
exact-path action; start a new attempt only in a fresh reviewed workspace.

## 5. Still required before a trusted base or Gate A

The [2026-10-09 diagnostic record](night_shift_image_diagnostic_record.md) now
contains real native `/target` audit/re-audit/release evidence, successful curtin
and post-install messages, and completed cloud-init plus bounded account/SSH-server
checks on a separately prepared diagnostic copy. The original unmasked installed
boot failed in the serial bootstrap before cloud-init finalization; it did not
prove protocol success or a kernel crash. Recovery/copy initialization is not
acceptance of the original candidate or a cleaned base.

### Initialization before worker activation

The generic protocol unit is enabled for the finished base and can power off on
both success and failure. Its serial-device ordering is not a guarantee that
cloud-init has completed. Do not simply start an uninitialized installed disk
without a controller or rely on catching GRUB to apply a mask in time.

Before an explicitly approved initialization/diagnostic boot, preserve original
state/evidence and prepare a separate working copy using an approved live recovery
environment. Mask the worker offline, preserve its exact original bytes/permissions,
and separately review any temporary console-only root access. Recovery should boot
its verified live ISO diskless before the copy is attached; verify guest block
read-only flags and disable filesystem journal replay for forensic inspection.
A writable transition/journal replay is a separate approved copy-only operation,
not a silent continuation of read-only inspection. Never mount the guest filesystem
on Windows or use the protected agent WSL distribution as a recovery sandbox.

Verify the installed root, running service mask/inactive state, all cloud-init
stage start/finish/error fields, the result and intended disable marker, and
actual account/remote-access state. A bare `cloud-init status: disabled` or an
Off console does not prove finalization. Do not disable the unit's power-off
safety or add distribution-specific dependencies without reviewing the actual
systemd ordering graph. Temporary debug/root access and the worker mask are
preparation-only changes, not acceptable final-image configuration.

Remaining work is separately reviewed offline hygiene and diagnostic removal,
restoration/audit of the exact worker and serial-console policy, graceful completion,
new external read-only/private base export, final digest/provenance and independent
image review. Generated SSH host keys, logs/cache/history, installer/cloud/machine
state and temporary root access remain pending on the current copy. Preserve the
completed diagnostic evidence before destructive hygiene. Keep the intended
cloud-init-disable policy; do not reset/re-run initialization as a cleanup shortcut.
Retirement is not a substitute for any of these. No unattended end-to-end builder
or reusable automated first-boot/hygiene pipeline is supplied by this runbook.

Only a reviewed frozen bootable VHDX permits a separately authorized **Gate A**
lifecycle/protocol run. Gate A still needs observed network-off boot, protocol,
cancellation/disconnect and VM/differencing-disk cleanup evidence. No repository
transfer or model work belongs in this preparation run or Gate A.

## Sources (documentation, not evidence for our ISO)

- [Canonical autoinstall quick start](https://canonical-subiquity.readthedocs-hosted.com/en/latest/howto/autoinstall-quickstart.html): separate seed volume and disk confirmation without the kernel flag.
- [Autoinstall reference](https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html): late-command inspection pauses, `/target`, and `shutdown: poweroff`.
- [Operating the server installer](https://canonical-subiquity.readthedocs-hosted.com/en/latest/tutorial/operate-server-installer.html): graphical terminal and live shell controls.

These current documentation pages were consulted while drafting the candidate;
they do not certify the packaged Subiquity version in our selected ISO.
