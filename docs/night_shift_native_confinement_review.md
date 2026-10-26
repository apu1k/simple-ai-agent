# Native confinement review scope — offline preparation, NOT execution approval

## Current local checkpoint and historical remote scope

This continues the [recovery handoff candidate](night_shift_recovery_handoff.md),
not the real-host Gate A suite. The operator has returned to the local desktop
and committed the Flex work as `a7c717c` and recovery/confinement work as
`fad3832`. Local elevation is available for separately approved later work, not
an execution grant for this scope. Source review and synthetic tests continue;
no policy loading, daemon, media authoring, VM operation, service/network change
or automatic restart is requested by this checkpoint. No protected helper,
deployed bundle, retained VM/image, permanent claim, frozen script or prior
receipt is changed.

The [fixed native-validator design](night_shift_native_validator_design.md)
now specifies validation-only RAM controls, exact-worker audit attribution and
failure semantics. Its first applied component is a pure bounded local audit
correlator with **93 passing synthetic format tests**. The combined eleven-file
selection passes **641 with 2 skips in 4.58 seconds**, INCLUDING those 93,
warnings as errors; repository Ruff and Mypy across **85 source files** pass.
Strict in-memory compilation/3.12 grammar, actual bundle exclusion, unchanged
launcher/policy pins, existing tracked source preservation, links and whitespace
checks also pass; see the linked design for limits. No source repair is needed.
This remains neither a runnable validator nor a native result.
The explicit network/capability denies may suppress audit and require a separate
observability decision; an errno alone must not be accepted as LSM evidence.
Earlier remote-session and uncommitted statements below are historical reports.

Before this batch, the normal nine-file targeted selection was rerun with
warnings as errors: **509 passed, 2 skipped in 3.99 seconds**, including all 50
handoff regressions. The skips remain Linux-only disposable-fd behavior and
unavailable unelevated symlink creation, not native successes. Repository Ruff,
Mypy across **84 night-shift source files**, and `git diff --check` pass. Those
results validate the applied baseline, NOT the new test module below. Native
AppArmor parsing/enforcement, NNP transition, boot/runtime compatibility,
independent host receipt and VM cleanup remain unverified. Gate A remains unrun.

## Applied offline harness — verified, not native evidence

`tests/night_shifts/test_bootstrap_confinement_contract.py` is test-only. It
executes the launcher's Python control flow with substituted OS, subprocess,
policy-parser and import adapters; no native command or guest code is executed.
The seed/policy fixtures are deliberately NOT archives or loadable policy.
Existing handoff tests, not these substituted parsers, cover the full-seed pin.

The harness:

- Records the actual namespace-phase command argv, translates only the explicit
  mount/remount requests into an assumed mount view, and feeds that view into
  the real probe's `check_mounts`. It also checks the fixed bind sources, fresh
  sysfs request, executable runtime versus noexec pool, and write destinations.
- Mutates the recorded plan to check refusal of writable root/proc/sys,
  persistent or executable pools, noexec runtime and added/nested writable views.
- Injects terminal failure at each of the 14 current namespace commands and
  four boot commands; checks there is no repeated command or later phase.
- Checks every missing NNP/capability property, denied/short profile-transition
  writes and wrong read-back stop before support-code imports.
- Builds the existing inspection ZIP in memory and verifies the recovery,
  public-probe and validation candidates remain excluded.

This is a consistency/ordering model, NOT a Linux mount simulator, AppArmor
parser or security-policy analyzer. In particular it assumes chroot-visible
mount enumeration and synthetic bind backing; it cannot establish actual
submount visibility, inherited mount/superblock flags, device behavior, utility
semantics, LSM permissions, ABI compatibility or process-tree absence. A passing
model must never be recorded as a native denial or authentic boot receipt.

The applied harness passed **39 tests in 0.17 seconds**, warnings as errors.
The combined ten-file command then ran without temporary hooks or source
substitution:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_confinement_contract.py tests/night_shifts/test_bootstrap_recovery_handoff.py tests/night_shifts/test_bootstrap_recovery_native_policy.py tests/night_shifts/test_bootstrap_public_probe.py tests/night_shifts/test_bootstrap_daemon_asset.py tests/night_shifts/test_public_bootstrap_kvp.py tests/night_shifts/test_maintenance_credentials_prototype.py tests/night_shifts/test_maintenance_tls_prototype.py tests/night_shifts/test_maintenance_failure_diagnostics.py tests/night_shifts/test_maintenance_store_native_prototype.py -rs
```

Result: **548 passed, 2 skipped in 4.00 seconds**, INCLUDING the 39 new contract
checks, 50 handoff regressions and 459 earlier related tests. The skips remain
Linux-only disposable-fd behavior and unavailable unelevated symlink creation;
neither is a native success. This is a targeted selection, not the full suite.
Repository Ruff and Mypy across **84 night-shift source files** pass.

Strict warning-as-error in-memory compilation and Python 3.12 grammar parsing
pass for all **five handoff/test files** and **11 packaged Python snapshots**.
This does not execute Python 3.12, Linux imports, utilities or ABI checks. The
combined tests include actual in-memory inspection-bundle exclusion checks.
Launcher and policy canonical-LF hashes still match the recorded handoff
snapshots. `git diff --exit-code HEAD -- night_shifts scripts tests/night_shifts`
passes for existing tracked files; untracked handoff/test sources are checked
separately. All **10 checked Python/document files** pass trailing-whitespace/
final-newline checks, **26 local document links** resolve, and `git diff --check`
passes. No new runtime source repair was needed.

Actual-input seed/handoff rebuilding and the full external staging-catalog
read-back were not repeated for this test/document-only checkpoint; their
historical results in the linked handoff record are not new checks here.
No new production entry point, runtime evidence acceptance API or executable
validation payload is introduced. No elevation, native guest command, policy
load, daemon, media authoring, VM operation, service/network change, restart or
commit occurred. The existing uncommitted work and Flex changes are retained.

## Native questions that the model deliberately cannot close

| Area | Required later observation | Stop condition / current gap |
| --- | --- | --- |
| Trusted inputs | Externally reviewed complete recovery/support media and code/policy pins, held read-locked through use; independently recorded exact new VM identity | Media-internal manifest, profile name and guest DMI string alone are not provenance. Deterministic media/host runner are not yet supplied. |
| Runtime and utilities | Actual Linux x86-64, kernel 6.8.0-139-generic, isolated/no-site Python 3.12, required stdlib/shared objects, and exact parser/mount/unshare/setpriv behavior | Grammar parsing and static ELF inventory do not establish executable imports/ABI or utility options. No install/upgrade/fallback during validation. |
| Add-only policy | Parse the exact reviewed bytes without kernel load first; then add only into an isolated approved guest with no colliding profile | Parser failure or existing name stops. Never replace/remove a profile, consult an unreviewed cache, add abstractions or retry. |
| Capability/NNP transition | All five capability sets zero, NNP=1, then the fixed `changeprofile` write and exact enforced-label read-back before any support import | The transition may be unavailable under NNP/zero caps. Stop for source review; do not move it earlier or retain capabilities merely to pass. |
| Mount/PID/net layout | Actual post-chroot mountinfo: readonly root/runtime views, fixed tmpfs execution/pool mounts, no writable persistent view/nested redirect, full PID visibility, distinct mount/net namespaces, fresh sysfs, sole DOWN loopback | The test-only argv model cannot show actual chroot mountinfo or recursive/submount effects. No PID namespace, broad rbind or permission/mount repair fallback. |
| Disk/device isolation | Only expected optical/read-only active-loop backing, no target block disk or swap; exact KVP character device; no existing daemon anywhere in the full PID view | Block names alone do not prove backing/provenance. Missing reads or uncertainty stop; do not enable a guest service or alter a device ACL. |
| Positive confined behavior | Pinned ZIP imports, exact RAM-only daemon creation/execution with fixed foreground argv and empty PATH, five fresh pools, locked public-only publication, exact-child stop | Model publication is not native behavior. The production candidate is not intrinsically read-only: its daemon still has host-mutation/IP/helper code paths. |
| Negative confinement | Native operations denied for the reasons below, with bounded independently reviewed evidence and no raw guest output | PermissionError alone may be DAC/noexec/missing-path failure, not AppArmor enforcement. Denial instrumentation/payload is still to be designed and separately pinned. |
| Host observation/lifetime | Independent exact-VM full public-record receipt, protected external watchdog and independently confirmed final absence of only the newly owned VM | Guest JSON and direct-child exit do not establish host receipt, tree absence or VM stop. Timeout/cancellation/transport loss is UNKNOWN until independently resolved. |

## Required denial matrix — design requirements, not runnable instructions

Use only newly owned disposable guest RAM objects and fixed harmless probe
operations. Do not run negative probes on the Windows host, current workstation,
retained inspection VM or real target disk. A future validator must distinguish
LSM denial from unrelated missing-path/DAC/noexec/syscall failure. Where a
positive control would itself be dangerous, design a harmless substitute; do not
execute a shell, send packets, mutate a real disk or mount a real filesystem
just to demonstrate that the unconfined control would work.

| Boundary | Later harmless negative probe | Required interpretation |
| --- | --- | --- |
| Execution allowlist | Attempt exec of a fixed inert, non-shell RAM fixture outside the two allowed executable paths, on a deliberately executable disposable mount | The fixture must exist and otherwise be executable. Never use arbitrary commands or rely solely on an ENOENT/noexec result. Shell/helper absence is also checked statically. |
| Filesystem writes | Attempt to write/create a disposable sentinel outside the exact daemon/pool write allowlist, on a dedicated otherwise-writable RAM location | Readonly-root failure is defense in depth, not evidence that AppArmor denied the write. No broad write grant may be added for the test. |
| Pool operations | Check permitted fixed pool reads/writes/locks, and refusal of an unrelated sibling RAM file | A passing negative alongside broken legitimate pool operations does not establish usable policy. Never substitute a native marker-store fixture for host receipt. |
| Network | Attempt creation of fixed socket families/types without transmitting data, with syscall/errno evidence sufficient to identify the cause | A namespace with no NIC/route does not prove the LSM network rule. The host VM must independently remain NIC-free. |
| Capability boundary | Observe zero sets/NNP and attempt one fixed harmless privileged operation whose effects cannot alter host/guest resources | Zero capabilities can deny independently of AppArmor. Do not claim this proves the policy's capability rule or perform real mount/ACL/service changes as a control. |
| Signals/process isolation | Confirm exact-child signaling works, and that unauthorized interactions cannot be inferred from self-peer signaling alone | The policy explicitly permits receiving signals from unconfined supervisors. Do not claim all cross-profile signaling or ptrace is already tested. No broad process-name cleanup. |

No runnable denial validator or native result is supplied here. The separate
[validator design and audit-correlation source checkpoint](night_shift_native_validator_design.md)
is still offline, unwired and not host evidence. The candidate policy's `deny`
text and Python exception mocks are not substitutes.
Any required change to source/policy/layout must be reviewed offline and repinned
before a new separately authorized attempt, not repaired inside a privileged run.

## Ordered path toward Gate A

1. The applied offline harness is verified as above; native behavior remains open.
2. Next, design/review a fixed guest-only native validator and its harmless controls,
   bounded evidence transport and failure semantics. Keep it separate from the
   public probe; do not expand the production command/payload API for testing.
3. Review deterministic complete support media, fresh exact-owned diskless host
   runner and protected watchdog/receipt path. The current renderer is NOT an
   ISO author and the foreground guest report is NOT a wired evidence channel.
4. Only after local access and fresh explicit execution approval, validate the
   native policy/layout in an isolated new diskless VM: no target disk, NIC,
   shared folder or serial pipe; exact identity, intended Secure Boot and
   checkpoints/GSI controls read back; exclusive host activity; immutable inputs;
   independently bounded lifecycle and final VM absence. Do not improvise a
   different guest platform or weaken constraints to obtain a pass.
5. Separately review the public-only KVP feasibility attempt and its Data Exchange
   scope. Even successful native confinement and public exchange are NOT Gate A.
   Real credentials, authenticated serial transport, accepted image preparation
   and Gate A's independent bounded lifecycle/transport/cleanup remain open.

Nothing in this document authorizes a live test, protected deployment, claim
reset, retained-object cleanup, image finalization/publication or Gate A run.
