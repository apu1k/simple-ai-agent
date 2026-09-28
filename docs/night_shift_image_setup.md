# One-time Hyper-V protocol-test image setup (not yet automated)

**Current state: no reviewed bootable Linux VHDX and no unattended image builder.**
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
