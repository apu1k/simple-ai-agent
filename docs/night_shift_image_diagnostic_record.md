# Ubuntu image diagnostic record — 2026-10-09 (NOT Gate A)

This records operator-console evidence and saved host receipts from the ongoing
attended preparation. It is not permission to start/retry a VM, clean a disk,
release a lock, accept an image or run Gate A. The three earlier failed installer
candidates remain retained; see the [preparation runbook](night_shift_image_preparation_runbook.md).

## Current handoff

- A fourth candidate reached the fixed target audit, passed both audits and
  released the installer review wait. Automatic installer power-off was observed.
  Saved logs confirm curtin/post-install success and review release; do not equate
  those messages alone with complete image acceptance.
- Its first unmasked installed boot failed in the protocol bootstrap and powered
  off before cloud-init's final stage. This was not a successful protocol test.
- An isolated recovery VM inspected a separate post-boot disk copy, then booted
  that copy after offline protocol masking and temporary root tty9 preparation.
  **Cloud-init initialization and the listed account/SSH-server checks now pass
  on this diagnostic copy**, not on a newly booted original candidate.
- The operator reports the diagnostic VM OFF after orderly installed-system
  power-off; no installation-media prompt appeared. This is an operator report,
  not a fresh agent-side Hyper-V inventory. The latest launch receipt recorded
  all four original candidates OFF and unchanged.
- The diagnostic copy still contains temporary root-console configuration, the
  worker mask, generated host keys and machine-specific/log/cache state.
  **No cleaned/frozen base image or final accepted digest exists. Gate A is unrun.**
- Preserve original candidates, disks, media, manifests, permanent claims and
  the original candidate's `018` operation lock. Earlier numbered scripts are
  completed/one-shot evidence, not scripts to rerun at this new state.

## Resource and provenance binding

The fourth preparation used commit `48343aa4e55e77037ed5a574b9a54b81fd8b58b2`:

| Item | Recorded binding |
| --- | --- |
| Original candidate | `night-shift-image-prep-2486645f4317486aae7034ae66845305` |
| Original VM GUID | `7d0b7f9e-772b-4c29-9356-326493ca8d11` |
| Original control manifest after launch | SHA-256 `c6de022038f9d20654f98c618fe71150ae5d57df447f4c255906105db8372052` |
| Installer | `D:\NightShift\sources\ubuntu-24.04.5-live-server-amd64.iso`; SHA-256 `97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8` |
| LF bundle | SHA-256 `fc8ac8a92e9d3eb787180583ae38f47bbd4c4532d0ab612aef4a3b994ee01b5d` |
| Fourth seed | SHA-256 `05935f6672bf00a02123837dbd47d089d5921295f7938233afa86baae58a3fd0` |
| Preserved pre-first-boot disk | SHA-256 `f8fbef0e446881361f16e5db01128c81fef101da03658f2156687525e3689e70` |
| Original post-boot disk / inspection copy before diagnostics | SHA-256 `f9f71dfa3e32a1d4c4a2ba621c567b0cd01a511d9d393709726ec659f0495ec4` |
| Recovery/diagnostic VM | `night-shift-recovery-8c4c51e2f47a44ccaca6ef09de7492f5`; GUID `24651418-5ca1-4e35-8cb9-2a498b44f33f` |
| Diagnostic working copy | `D:\NightShift\build-sandboxes-review-48343aa\recovery-inspection-020\assets\unvalidated-post-boot-inspection.vhdx` |
| Copy before `028` boot, after offline masking | SHA-256 `085b638f29c9a00f01c24b9e5af13741ba2120edf750c02499bae6780741c32f` |

The last digest is **before** the successful diagnostic boot. Initialization and
normal guest writes changed the copy afterward; it is not a current/final base
digest. The original candidate had 2 CPUs, fixed 2 GiB RAM, a sole 20 GiB dynamic
parentless disk and disconnected networking. Recovery used the same resource
limits but **no network adapter**, Guest Service Interface disabled, Linux Secure
Boot, no checkpoints and no personal/host disk or share. `028` cleared both DVD
media paths and selected only the prepared copy before starting once.

Representative saved receipt hashes (not guest/image certification):

| Receipt | SHA-256 |
| --- | --- |
| `installer-launch-receipt.json` | `45ca9ced3f74bffdce65e7f7ce5af02c63c43f72e948a75f192fe7946c8c1bf9` |
| `017-completion-receipt.json` | `cf11fe5311cdc7156674a6831bbb4d8be84a0ae8db553ec87b2aaf7812e0c89f` |
| `020-reconciliation-receipt.json` | `2afc985580b500751d4ab7f645a2e8d0809d7d02ab9130bb7931bc8c7444f401` |
| `recovery-resume-024-receipt.json` | `46c6c09c8293c61f1ca684d8cdead1f9fe6b1d5eb68a2792f9b39c17a985a85c` |
| `inspection-attach-026-receipt.json` | `73017058e4012ea2acd2e582d89784d2684318796222d5d2519fc06006ad777f` |
| `027` media-attachment receipt | `497529413d017d8a725e6dbdebd005c801452bbbd955991616c92fcb3dc4f2c5` |
| `028` diagnostic-copy launch receipt | `cfb689ed87edf2d7e9210f04d57146d53a3681850adb9e07cfef2e92ab01b505` |

Private host receipts remain outside the checkout. Linux console findings below
are operator-reported observations; the host receipts did not independently
mount/read guest filesystems or attest cloud-init/security completion.

## What actually happened

### Fourth installer review and shutdown

The native target audit reported all eight policy groups PASS on 2026-10-05.
Saved `installer-journal.txt` records RESULT PASS at **16:32:51**, another PASS
at **16:42:57**, and **`NS-REVIEW RELEASE accepted; installer completion only`**
at 16:42:57. `subiquity-server-info.log.1630` records successful curtin installation
and post-install configuration. The marker released completion; the configured
`shutdown: poweroff` did not wait until the review window expired. A console
turning off is not itself an installation error or a trusted-image receipt.

### Unmasked installed boot and forensic inspection

`018` started the original installed candidate, but the attempted GRUB interception
was missed. Its printed 15-second notice preceded a silent pause, not a visible
countdown or enforced GRUB hold. No one-boot service mask was applied.

Saved guest journal entries from 2026-10-07 04:16:41–42 show the protocol service
starting, reporting `night-shift protocol bootstrap failed: (5, 'Input/output error')`,
then exiting with status `1/FAILURE`. The unit has `FailureAction=poweroff` and
`SuccessAction=poweroff`; that sequence is consistent with its failure power-off
path, not evidence of a kernel crash. No Gate A controller/task/result exchange
was captured. The exact failing operation (open/configure/read/write) and
hardware serial cause remain unconfirmed; lack of the reviewed COM1/controller
setup is a leading explanation, not a hardware diagnosis proved by that message.
The bounded host-event report contained no matching events, which proved neither
success nor crash.

Recovery booted the pinned live ISO **diskless** before hot-attaching only the
inspection copy. Guest disk/partition read-only flags were verified, and ext4 was
mounted `ro,noload` (shown as `ro,norecovery`). This avoided journal replay during
initial inspection. Results/status showed completed init/config stages but no
final-stage start/finish, no `result.json` and no intended disable marker.

### Offline diagnostic preparation and successful initialization

`027` delivered only a fixed diagnostic Python procedure, a checksum-verifying
shell runner and checksums on nonbootable read-only `NSDIAG027` data media. It
installed no dependencies and transferred no checkout, account credentials or
model keys. Its approved Linux invocation deliberately allowed **copy-only**
writes and ext4 journal replay, backed up the original worker unit, masked its
normal path with `/dev/null`, and enabled the vendor root tty9 debug shell.
It used no chroot and started no service. It finished by unmounting the copy and
restoring guest block read-only flags. The final-stage absence persisted after
journal replay, so it was not merely an initial no-replay view of pending data.

The original unit backup hash was `71d0c64109efa5f96c906812a403fe7820b5455305b32ac420e90381cf903657`.
The unchanged bootstrap hash is `6d8fd573e51fb5f573cdf7392dbd051574021b9a2c38be72e723316794e9d58b`.
The reviewed procedure's LF hash was `7adc5403e989d46a074888e8c96679b036a564b0d4e79aec6d7609766d4eaf1c`.
These are public code hashes, not SSH private-key contents/digests.

`028` booted only the prepared copy with DVDs empty. In the actual tty9 shell,
`findmnt` reported **ext4 `/dev/sda2`** and the worker reported
**`LoadState=masked`, `ActiveState=inactive`**. Networking startup displayed a
wait-online progress line on the console; it could overwrite the prompt and
look like a reset. No reset was established, and networking was not enabled as
a workaround. Cloud-init subsequently completed naturally.

At **2026-10-09 07:21:21 UTC**, cloud-init `26.1-0ubuntu1~24.04.1` reported final
completion with `DataSourceNone`, uptime **125.08 seconds**, and systemd reported
`cloud-final.service` finished. `result.json` had no errors; all four status stages
had start/finish values, no errors and no recoverable errors. `modules-final`
started at 124.99 and finished at 125.08. `/etc/cloud/cloud-init.disabled` existed,
root-owned, mode 0644, 132 bytes. The result/status JSON, not a bare `disabled`
CLI status, established completed initialization.

Account/SSH-server observations after completion:

- Root and `night-shift` passwords were locked (`L`).
- `night-shift`: UID 999, GID 988, `/nonexistent`, `/usr/sbin/nologin`; groups only
  its primary group and dialout (20).
- The UID 1000–65533 account query returned no entries.
- `openssh-server`: `unknown ok not-installed`.
- Root's `authorized_keys` was empty. Six RSA/ECDSA/Ed25519 SSH host-key/public-key
  files existed, dated October 7; filenames/sizes/permissions, **not contents**, were
  reported. These are guest-generated identity artifacts still requiring hygiene,
  not proof of a personal key or running SSH daemon. Client SSH configuration and
  a small cloud-init-written `sshd_config` also existed.

These are bounded initialization/account checks, not a complete image-hygiene
or confinement attestation. Temporary debug access remains disqualifying for a
frozen base. No normal protocol service/task behavior was validated by a masked
boot. The operator subsequently powered the installed copy off without a media
prompt. Earlier candidates and original evidence remain retained.

## Defects, expected behavior and code-review disposition

| Finding | Disposition |
| --- | --- |
| Original CRLF payload / parent-cwd unmount / 30-minute manual-review workflow | Earlier repo corrections are recorded in commits `f0e9098`, `319c473`, `48343aa` and the runbook. Those failed candidates are not resumed. |
| `014` Python `\6` filter escape | External operator-script bug: interpreted as a control character, rejecting Guest Service Interface before any start. Corrected literal comparison allowed the first actual launch. |
| Exact pre-install firmware/media equality in `015`; property-order/recursive object output in `016` | External helper assumptions/serialization defects. Reviewed Ubuntu EFI insertion and ISO ejection were not evidence of unrelated VM changes; typed semantic observations replaced misleading raw comparisons. |
| `015`/`020`/`023` ACL assumptions | External helper defects: Hyper-V can remove a VM DVD read grant or add its exact VM/worker grants; VHD attachment changed the asset directory and inherited copied-ISO profile. Inspect and bind known native profiles/transitions, never silently restore/remove grants or equate ACL drift with byte drift. |
| `023` Running/Off normalization mismatch | External helper bug stopped before its attachment call. Corrected without discarding/reinstalling the candidate. |
| `024` assumed live ISO remained inserted | External helper omitted the observed shutdown/eject transition. `025` identified the empty DVD; corrected `024` explicitly reattached the same verified ISO only after detaching the inspection disk. |
| Relying on catching GRUB in time | Preparation-workflow defect. Mask the worker **offline before any initialization/diagnostic boot**; do not depend on console timing. |
| Bootstrap I/O error and shutdown | Nonzero exit plus unit failure power-off is intentional fail-closed behavior. It is not a successful task or a demonstrated core protocol implementation bug. Exact serial cause remains open until reviewed channel testing. |
| Worker can start before first-boot finalization | Preparation sequencing must prevent that startup. Keep the initialized-base requirement and offline mask/restore boundary explicit; do not disable shutdown safety or blindly add distribution-specific cloud-init dependencies to the generic unit. Review the actual systemd graph before any ordering change. |
| Missing `main()` regression coverage | Add offline tests for serial-open/read I/O errors, early controller EOF, channel closure, success/EOF and both unit power-off actions. These do not emulate Linux UART/termios or real Hyper-V. |

No guest runtime source or fixed bundle needs changing solely to record these
findings. Better phase-specific serial diagnostics and reusable tested preparation
helpers are follow-ups, not demonstrated prerequisites requiring another install.
Do not claim that external helper fixture tests establish real ACL transitions or
that mocked EIO tests identify the observed guest failure's exact cause.

## Required next boundary

1. Separately review preservation of completed diagnostic evidence before destructive
   hygiene, keeping the three failed candidates, original fourth candidate, backups,
   media, permanent claims and `018` lock unchanged.
2. Perform approved **offline, copy-only** hygiene: guest-generated keys, logs/caches,
   history, installer/cloud/machine-specific state; restore the exact worker unit;
   remove root tty9 enablement and diagnostic overrides/artifacts. Do not unmask it
   in the current unconnected running preparation guest or use key contents in chat.
3. Audit the resulting filesystem/security/serial-console policy, gracefully finish,
   export a fresh independently hash-verified base outside worker-writable storage,
   enforce the reviewed read-only/private host policy and record provenance.
4. Review actual COM1/named-pipe binding and permissions; separately authorize the
   existing real-host Gate A suite using disposable differencing disks. Capture task,
   rejection, timeout/cancellation/disconnect and exact cleanup results. No model
   calls or arbitrary repository transfer belong in this gate.

Numbered operator scripts remain outside this checkout in
`notes_temp\ai_agent\scripts`, executed by complete-copy/paste into Administrator
PowerShell under the usual account, without new switches/confirmation phrases.
Use basic console only; no redirection. WSL is protected agent infrastructure and
must not be used as a test/recovery sandbox. No original/failed candidate restart,
blind retry, lock removal, ACL repair or broad cleanup is implied by documentation.

Documentation/tests change the repository commit/clean-state input but **not** the
fixed guest payload. Commit/review this batch before generating the next host
procedure; pin that procedure to the new reviewed commit while preserving old
receipts' original commit and hashes. Do not rerun old one-shot scripts or weaken
their checks to work around the new repository state. The existing verified LF
bundle is unchanged; a documentation/test update alone does not require a rebuild.
