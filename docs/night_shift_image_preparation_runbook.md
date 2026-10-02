# Candidate one-time Ubuntu preparation runbook (NOT launch authorization)

This is a review procedure for a separate preparation VM, not Gate A itself.
**No preparation VM has been launched and no installed VHDX is reviewed.**
One operator-reported preparation attempt has been observed OFF after creation
and separately approved combined-seed attachment. The persisted manifest records
`created_seed_attached_not_started` and the local seed verification passes.
Host observations exposed configuration-path and fixed-memory assumptions that
the fake runners missed: the VM still reports Dynamic Memory enabled, contrary
to the reviewed fixed-memory policy. It must remain OFF until separately reviewed
correction and isolation checks pass. Launch and retirement still have only
offline/fake-runner evidence; successful attachment does not certify readiness.
The shell/YAML candidates have not been executed in Ubuntu. The operator must separately
approve actual paths, independently reviewed digests, resources, permissions,
a time window and the exact actions before any real host operation.

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
ordinary Windows drive shares. Keep permissions/integration/sharing review open
before boot. Generic `EFI SCSI Device` boot descriptions do not identify the
installer; inspect the first firmware entry's actual device/path as well.

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
There is no automatic migration/fallback. For an existing never-started attempt,
prepare a separate exact-file reconciliation proposal **after offline validation**:

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
only local files and returns an immutable packet. Its `to_review_dict()` contains
paths, pinned media digests, manifest/script hashes, resources and expected host
policy. It does not query Hyper-V, authenticate the publisher, inspect ACLs, or
write a packet file. The VM GUID must come from independent trusted host
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

Launch and retirement share `vm-operation.lock`. Normal returns/handled errors
release only the exact guard created by that wrapper; permanent claims survive.
A process crash, changed guard or failed release leaves it for manual inspection.
Never infer a stale lock from elapsed time. Confirm no active operation and
independently inspect the exact VM/workspace before separately authorizing
resolution. This coordinates these wrappers, not arbitrary Hyper-V actors;
create/attach and all other operators/runners still require exclusive host use.

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

The combined seed first runs the fixed `/target` service installer, then a
separate fixed late-command review wait. It refuses a stale acknowledgment,
checks for a root-owned regular non-symlink acknowledgment with mode `0600`,
and makes at most 1800 one-second polling attempts. This is roughly a 30-minute
review window, **not a host-enforced deadline**. Exhaustion fails installation;
it must not be treated as a completed image. It requests `shutdown: poweroff`
after successful review, instead of the installer's default reboot.

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

The first real launch packet and the actual ISO's seed/confirmation/checkpoint
behavior remain unvalidated. After an observed successful install/power-off,
review exact-VM DVD removal/boot order, serial configuration/pipe ACLs and a
separately approved first boot; verify cloud-init's resulting accounts and the
running service. Image hygiene, machine-specific state cleanup, graceful final
shutdown, external base-image preservation/digest and independent image review
are not automated here. Retirement is not a substitute for any of these.

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
