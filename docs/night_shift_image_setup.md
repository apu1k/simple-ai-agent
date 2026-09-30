# One-time Hyper-V protocol-test image setup (not yet automated)

**Current state: no reviewed bootable Linux VHDX and no unattended image builder.**
An offline guest-asset bundle can now be generated, but it does not install an OS,
transfer files into a VM, or remove the need to review the resulting image.
The `hyperv_image_preflight` command added here is read-only. It checks an
*already prepared* image's filename, eight-byte VHDX signature and pinned
SHA-256, an initially empty test-only workspace outside this checkout, and
conservative free-space availability. It does **not** download, install,
provision, launch, or certify a VM. An eight-byte signature is not a complete
VHDX format check. The trusted Hyper-V controller independently checks the
image digest before creation; neither check proves guest contents are safe.

The operator confirmed on this machine that `Microsoft-Hyper-V-All` is enabled
and `Get-VM`, `New-VM`, `Start-VM`, and `Remove-VM` cmdlets are available. This
is a **software-prerequisite observation**, not authorization to build an image
or run the real-host suite; image, workspace, VM privileges and pipe ACLs have
not been validated. No particular image source, location or SHA-256 has been
approved.

## Candidate operator runbook and discard safeguard

See the [candidate preparation runbook](night_shift_image_preparation_runbook.md)
for the exact input/host review checkpoints, deliberate one-time installer
confirmation, live-installer target inspection and separate discard consent.
It is **not launch authorization**, and the actual ISO behavior is unvalidated.
The combined seed now requests a finite manual late-command review wait and
`shutdown: poweroff`; it does not automatically boot the installed guest.
The optional `retire_image_preparation_vm` path only force-stops/unregisters
one exact-owned preparation VM and retains its untrusted disk/evidence. A
permanent claim and unknown status block retry after uncertainty. Retirement
is for discarding a failed attempt, **not freezing an image or freeing storage**;
its PowerShell script and Python wrapper are tested only with a fake runner.
The [launch approval-packet template](night_shift_preparation_launch_approval.md)
and read-only `build_preparation_launch_plan` bind the media, manifest, launch
script and resources to an independently observed VM GUID. The separate opt-in
`launch_image_preparation_vm` rechecks that packet and exact host settings,
creates a permanent claim, records `launch_unknown` before one start command,
and accepts only a matching running/network-off receipt. Successful launch is
`installer_vm_started_not_reviewed`, never an installed or accepted image.
Retirement recognizes these launch states, requires their original GUID/plan
claim, and refuses a same-name replacement. Launch and retirement share an
exclusive transient operation guard; crashes/changed guards need manual review,
not stale-lock guessing. These are offline-tested candidates, not observed
Hyper-V behavior or a hard installation/VM-lifetime supervisor.
First-boot serial configuration, image hygiene and final preservation/review
remain separate prerequisites. No real VM operation is authorized here.

## What a one-time image build needs

1. Operator-selected and independently verified Linux installer/source, OS
   version, provenance and licensing; decide explicitly whether a **separate
   image-preparation** VM may access a network. The actual protocol-test VM
   must have no switch attachment. Do not implicitly download an image or use
   a personal VM, an agent-selected URL, or a repository checkout as a base.
2. A minimal Hyper-V generation-2 Linux base VHDX stored **outside** this
   checkout, with virtual size at most the reviewed test `disk_gb` (20 GiB by
   default). An ISO alone is not the bootable VHDX. Review Secure Boot template
   compatibility for the chosen distribution. A base image is frozen after
   review; each test receives a disposable differencing disk, not a separate
   manual installation. Reserve enough disk space for image preparation and
   temporary disks; virtual size is **not** a physical disk quota.
3. Install Python 3 and systemd, copy the repository's
   `night_shifts/guest/protocol_test_bootstrap.py` to
   `/usr/local/lib/night-shift/protocol_test_bootstrap.py` and the
   `night_shifts/guest/night-shift-protocol-test.service` unit to the systemd
   system directory as root-owned, worker-nonwritable files. Create the locked
   `night-shift` service identity with access only to its serial device, enable
   the unit, disable `serial-getty@ttyS0`, and remove any kernel `console=ttyS0`.
   Review raw COM1 communication on `/dev/ttyS0`, systemd shutdown/disconnect
   behavior, other running services, accounts and permissions inside the guest.
4. Remove image-preparation accounts/credentials, secrets, host shares, remote
   login, installer leftovers and machine-specific state according to the
   reviewed distribution procedure. Shut down the VM, retain a clean base
   VHDX outside the checkout, and record its independently obtained SHA-256
   and build provenance. Do not run the guest image mounted to the host as
   arbitrary code during inspection. The operator must review the image, not
   just accept an integrity hash.
5. Select a **separate**, initially empty, test-only workspace directory
   outside this checkout; never point tests at an existing VM/disk directory.
   Verify disk space, account privileges, no concurrent runner, serial-pipe
   permissions and network-off configuration with the [Gate A
   checklist](night_shift_hyperv_preflight.md).

## Optional offline guest-asset bundle

After reviewing the fixed sources, an operator may write a deterministic ZIP to
a **new path** in an existing directory outside the checkout:

```powershell
python -m night_shifts.protocol_image_bundle `
  --output 'C:\ProgramData\NightShift\staging\protocol-test-assets.zip'
```

The command neither downloads an OS nor invokes Hyper-V. It bundles exactly the
repository-owned protocol bootstrap, systemd unit and Linux guest installer,
plus a file-hash list and manifest; it prints the ZIP SHA-256 for independent
review. The staging parent must already exist. Existing output is never
overwritten. Compare the ZIP hash to the reviewed output before transferring
it by an explicitly approved medium to a *separate image-preparation VM*;
never mount host directories into the final runtime guest. Extract only the
verified fixed-file bundle into a fresh guest directory. After reviewing its
contents, an operator may choose to run `sudo sh install_protocol_test.sh`
**inside that Linux guest**, not on the Windows host. The installer refuses
non-root/non-Linux/non-Microsoft-virtual guests, checks asset hashes and
Python syntax, creates a locked service account and root-owned files, masks
the serial login service and enables the fixed protocol unit. It does not
install Linux, download dependencies, remove guest credentials, shut down the
VM, check pipe ACLs, inspect guest networking, or freeze/verify the VHDX.
The installer is not executed in offline tests. Even with a bundle, a bootable
Linux system and explicit transfer mechanism are still required.

## Ubuntu Server 24.04 ISO input gate (offline)

Ubuntu Server 24.04 LTS amd64 is the selected **candidate** for the protocol
image. The operator does not have to supply a finished VM; an official installer
ISO will be needed for an actual build. Obtain the exact point-release ISO from
an independently reviewed Canonical source and verify the publisher's checksum
(and its authenticity) independently. No ISO download is authorized by the
choice of distribution. The checker deliberately requires a local ISO **and**
a separately supplied expected digest; hashing an arbitrary file and accepting
its own digest is not a provenance check.

With a previously created and reviewed fixed guest bundle, run from the repo
root using your actual paths and independently obtained hashes:

```powershell
python -m night_shifts.ubuntu_iso_inputs `
  --iso 'C:\ProgramData\NightShift\sources\ubuntu-24.04.x-live-server-amd64.iso' `
  --iso-sha256 '<independently verified ISO SHA-256>' `
  --bundle 'C:\ProgramData\NightShift\staging\protocol-test-assets.zip' `
  --bundle-sha256 '<reviewed bundle SHA-256>'
```

This read-only check bounds the local files, checks the ISO9660 descriptor's
Ubuntu 24.04 amd64 label, matches both supplied digests, and requires the ZIP's
fixed contents to match current trusted guest sources. Neither the ISO label
nor the file's own hash attests source authenticity. It does not run an installer,
validate a bootable ISO, produce a VHDX, or inspect a guest. Its tests use a
synthetic ISO header and never launch a VM.

Canonical's [autoinstall quick start](https://canonical-subiquity.readthedocs-hosted.com/en/latest/howto/autoinstall-quickstart.html)
notes that presenting NoCloud data from an extra volume alone can leave an
interactive confirmation before disk modification. A truly unattended Hyper-V
builder must explicitly and safely arrange the boot parameter and seed medium,
keep a preparation VM separate from runtime VMs, prove exact-ID cleanup, and
be tested on the *actual reviewed ISO*; none of that is yet implemented. Do
not assume a passing ISO input check means unattended image creation works.

## Candidate NoCloud configuration (offline only)

`night_shifts.ubuntu_seed.render_ubuntu_seed` produces bounded in-memory
`user-data` and `meta-data` for a generated image-preparation VM ID. It asks
Subiquity for an offline fallback, disables installer refresh and SSH,
uses a direct single-disk layout, refuses disk setup when more than one disk
is visible, and requests no login accounts or passwords. Canonical's
[autoinstall reference](https://canonical-subiquity.readthedocs-hosted.com/en/latest/reference/autoinstall-reference.html)
permits omitting `identity` when `user-data` is provided. The first install
may **still require a human confirmation before erasing the new VM disk**;
this is acceptable for one-time base-image preparation, never for ordinary
background jobs. The kernel `autoinstall` flag is not added automatically.

`night_shifts.ubuntu_seed_staging.stage_ubuntu_seed(parent, instance_id)`
can now write these two bounded files plus a hash manifest into a **new**
identity-named directory under an existing, link-free directory outside the
checkout (for example, `D:\NightShift\staging`). Use the exact generated
`night-shift-image-prep-<32 lowercase hex>` identity of an approved preparation
VM; the staging function itself does not create one. It refuses reuse even
if an earlier write was incomplete; inspect leftovers rather than deleting
or retrying blindly. This is offline file staging only: it does **not** make a
NoCloud seed ISO, attach anything to a VM, add the `autoinstall` boot flag,
or transfer/install the protocol bundle. Review the files and recorded hashes
before planning any installer run.

An **offline-only candidate ISO builder** is now available:
`night_shifts.ubuntu_seed_iso.build_ubuntu_seed_iso(staged_directory)`.
It requires the pinned development dependency `pycdlib==1.21.0` (not installed
by this code). It rechecks the exact generated `user-data`, `meta-data` and
manifest, rejects extra files, and writes a fresh sibling `<instance-id>.iso`
with the NoCloud volume label `CIDATA` and Rock Ridge/Joliet `user-data` and
`meta-data` filenames. It returns its SHA-256; independently review that hash
and verify the ISO contents before attaching it. Existing outputs are never
overwritten. Building it does not execute PowerShell, create/start a VM, or
validate Ubuntu's use of the media. Tests exercising real ISO extraction only
run when the optional authoring dependency is installed. A separate opt-in `night_shifts.ubuntu_seed_attachment.attach_preparation_seed`
path can attach only the reviewed, SHA-256-pinned **combined install** `CIDATA`
ISO described below (not this older generic ISO) to the **exact owned
preparation VM while it is off**. It requires a persisted `created_not_started`
manifest, a matching generated seed filename and explicit attachment approval.
The fixed PowerShell script checks VM ownership, generation, off-state, disk,
installer DVD, disconnected network adapters, and both media hashes before
adding one seed DVD. Any uncertain result leaves `seed_attach_unknown` in the
manifest and requires operator inspection rather than automatic retry or a
broad cleanup. Its fake-runner tests do **not** establish that Hyper-V actually
attaches the DVD; no real VM operation is authorized by these tests.

A separate candidate `night_shifts/guest/install_protocol_test_target.sh`
handles **only an Ubuntu live installer's mounted `/target`**: it requires root
in a Microsoft Linux guest, a mounted target with Python, fixed-file hashes,
and an absent service identity. It creates a locked `night-shift` user, installs
root-owned fixed files into the new target, and masks the serial login and
enables the fixed service with `systemctl --root=/target` (not `--now`). It is
**not** the existing `install_protocol_test.sh`, which expects a running,
installed guest. Its checks are static on this Windows host; the target script
has **not** been invoked or reviewed against Ubuntu 24.04's live installer.
`render_ubuntu_install_seed(instance_id)` now defines **candidate** Subiquity
`late-commands` that would mount the fixed `CIDATA` volume read-only,
check `SHA256SUMS`, call this installer-target script, then pause for manual
inspection of `/target` from the live installer shell. A fresh root-owned
mode-0600 `/run/night-shift-image-review-approved` marker releases the wait;
a stale marker or exhaustion of 1800 polling attempts fails installation.
This is roughly a 30-minute cooperative review window, not a host-enforced
deadline or image certification. The seed requests `shutdown: poweroff` after
review; actual acceptance/off-state must be observed. The existing
`stage_ubuntu_seed` and `build_ubuntu_seed_iso` still use the **old generic
configuration** and include only `user-data`/`meta-data`: they do not include
or invoke this payload. The **separate offline**
`build_ubuntu_install_seed_iso(parent, instance_id, bundle, reviewed_bundle_sha256)`
now builds a candidate write-once `CIDATA` ISO containing the late-command
configuration, fixed trusted guest bootstrap/service/target installer, and a
`SHA256SUMS` for those files. It rechecks the reviewed bundle hash and contents
against the current trusted files; tests open the ISO through both Rock Ridge
and Joliet. Its returned SHA-256 must be independently reviewed before use.
The read-only `inspect_ubuntu_install_seed_iso` checks the pinned ISO hash and
bounded byte snapshot, exact ID-bound late-command configuration, and fixed
payload against the preparation manifest's reviewed guest bundle and current
trusted sources. It requires exactly the six expected regular files, with
matching bytes in the ISO9660, Rock Ridge and Joliet namespaces; extra files,
directories, symlinks, missing extensions and bootable/UDF media are refused.
The attach-only path now requires this check **before changing the manifest or
calling PowerShell**, records `seed_kind: ubuntu-protocol-install-v1`, and
rejects the older generic seed even if its SHA-256 and `CIDATA` label match.
The pinned `pycdlib` development dependency is therefore needed for attachment
inspection as well as ISO authoring; missing inspection support fails closed.
The existing PowerShell script independently rechecks the reviewed ISO hash
immediately before its attach-only operation. These checks assume reviewed,
operator-controlled input directories; they do not replace host ACL review or
establish guest safety. No Subiquity boot, installed VHDX inspection, or
guest-service operation has occurred. A failed late-command must
block freezing the image; manually inspect or discard the exact-owned prep VM,
never reuse a partially installed disk as a trusted base.

No seed ISO has been attached to a real VM, and no guest bundle is copied into Ubuntu.
There is **no actual unattended installer yet**. Offline YAML
parsing cannot prove Subiquity accepts this on the reviewed 24.04.5 ISO;
verify the disk guard and installed user state in the real guest. Since
there is no login, failure recovery should discard the exact-owned disposable
image instead of adding a generic password or enabling networking. Do not
power up the create-only VM with the expectation that this code has installed
Ubuntu or the protocol service.

## Opt-in create-only preparation VM (offline-tested, not authorized to run)

`night_shifts.ubuntu_image_preparation.create_image_preparation_vm` composes a
reviewed local Ubuntu ISO and fixed guest bundle with a **fresh** dedicated
workspace, for example `D:\NightShift\build-sandboxes`. It does not have a CLI
or agent tool; a trusted operator must separately authorize **VM creation** and
review ISO provenance before calling it. The directory must exist, be empty,
link-free and outside the checkout; ISO, guest bundle and workspace must be on
the same volume. The caller pins both independently reviewed hashes.

The fixed `prepare_image_vm.ps1` script creates an ID-bound generation-2 VM,
20-GiB dynamic disk by default and VM configuration below that fresh workspace,
attaches the reviewed installer ISO and sets the Linux Secure Boot template.
No switch is provided, dynamic memory and checkpoints are disabled, and the
script **does not start the VM**. The guest bundle is only bound in a durable
manifest, **not injected** into the VM. Its VM name uses the separate
`night-shift-image-prep-<id>` namespace, so runtime reconciliation must never
mistake an image-preparation VM for a job VM. If the host command fails or has
unexpected output, the manifest retains its exact ID with status
`provisioning_unknown`, and retry is blocked by the nonempty directory. The
operator must inspect owned leftovers; never blindly sweep other VMs.

The fake runner verifies identities, bounded choices, opt-in guards, and
manifest persistence. It has **not** executed the PowerShell script or verified
that host configuration, DVD attachment, VM cleanup, ISO boot or disk quotas
work on Hyper-V. Directory ACLs, named pipes and all host-generated paths still
require review. No preparation VM or directories on D: were created in the
offline tests. Ubuntu installation, offline guest-bundle transfer, first-boot
protocol service, image cleaning, final digest and real lifecycle Gate A remain
**BLOCKED**. This create-only foundation must not be called an unattended
image builder or a reviewed base image.

No unattended Hyper-V image creation is implemented in this repository.
A future opt-in builder should pin the OS input, keep image-preparation VM and
runtime VM separate, produce a reproducible manifest, perform exact-ID cleanup
on failures, and never change Hyper-V features, network settings, or host
permissions implicitly. That is **additional implementation**, not something
this input preflight pretends to provide. No live coding job may run after only
completing the image build: Gate A and the distinct real transfer Gate B still
need operator-approved evidence and the guest tool service/adapter.

## Read-only input check after image review

After a base image exists and an empty test-only workspace has been designated,
run this from the repository root, substituting **your reviewed** values:

```powershell
python -m night_shifts.hyperv_image_preflight `
  --image 'C:\ProgramData\NightShift\images\protocol-test.vhdx' `
  --sha256 '<independently reviewed 64-character SHA-256>' `
  --workspace 'C:\ProgramData\NightShift\integration-sandboxes' `
  --disk-gb 20
```

The command is read-only and has no Hyper-V dependency. A passing input check
is **not Gate A**: separately inspect the VHDX virtual size with `Get-VHD`,
confirm the installed guest program/unit and permissions, review the network
and COM1 named-pipe ACL, and obtain explicit authorization *before* setting
`NIGHT_SHIFT_HYPERV_INTEGRATION=1` and launching the opt-in test. The first
real-host suite creates and destroys its **own** VMs and differencing disks.
See [Hyper-V preflight](night_shift_hyperv_preflight.md) for the exact operator
checklist and evidence required; no image creation or VM run happened as part
of this offline work.
