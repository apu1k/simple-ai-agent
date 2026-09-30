# Candidate one-time Ubuntu preparation runbook (NOT launch authorization)

This is a review procedure for a separate preparation VM, not Gate A itself.
**No preparation VM has been launched and no installed VHDX is reviewed.**
The host functions and scripts have only fake-runner evidence. The shell/YAML
candidates have not been executed in Ubuntu. The operator must separately
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
**discarded**. `provisioning_unknown`/`seed_attach_unknown` additionally require
operator inspection (`unknown_state_reviewed=True`) and an updated record
matching the persisted status. Missing VM/disk/configuration, ownership
mismatches or incomplete manifests require manual investigation, not a sweep.

Before calling the fixed script, it creates a permanent exclusive
`retirement.claim` and persists `retirement_unknown`. The script validates the
exact preparation name/notes/configuration/single-disk binding, pins the actual
Hyper-V GUID, force-powers off if needed, rechecks ownership/off-state by that
GUID, and unregisters only that VM. It requires a successful inventory query
showing absence of both its GUID and name and verifies disk retention. It does
not require intact installer/bundle media just to discard a failed attempt.

**Force-off can interrupt installation and corrupt the disk. Never use this
operation to freeze a good image.** `retired_vm_disk_retained` means only that
the script reported VM absence and the wrapper still observed its disk; it is
not full filesystem cleanup or image acceptance. The manifest records the
retired VM GUID. The retirement path does not delete the VHDX, seed/installer
media, workspace or Python evidence. Hyper-V may remove its own VM configuration metadata during
unregistration; do not promise those files survive.

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
