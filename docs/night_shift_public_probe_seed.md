# Deterministic public support seed and fixed guest probe — verified offline

**Support-seed checkpoint committed as `50b61ee`; verified offline only, NOT
deployment, bootable media or execution approval.** The subsequent uncommitted
[recovery handoff/launcher](night_shift_recovery_handoff.md) now passes its applied
offline rerun: **509 with 2 skips**, including all 50 handoff regressions and the
459 related tests. Repository Ruff and Mypy across 84 source files pass. Actual
inputs reproduce this unchanged seed and the new handoff twice in memory; no
media is written or guest code/policy run. The handoff remains uncommitted for
remote-session offline development, NOT native or deployment approval. Its
linked validation record is separate from the historical seed checks below.
This advances the
[reviewed daemon asset](night_shift_kvp_runtime_review.md)
toward the [fresh diskless feasibility test](night_shift_bootstrap_feasibility.md).
It does not start that test or enable Gate A. The original recovery ISO, V1/V2,
consumed claims, frozen scripts and prior receipts are not inputs or edit targets.

## This batch

- `night_shifts/bootstrap_probe_seed.py`: explicit in-memory builder of a <=512 KiB,
  fixed-inventory, uncompressed **data ZIP**, with sorted entries, fixed timestamps/
  permissions, LF source snapshots, empty package initializers and canonical
  manifest. No output path, extraction, CLI, NoCloud/autoinstall config, installer,
  service activation, kernel/ISO modification or host operation exists.
- The builder accepts only the attempt/VM binding and exact reviewed package and
  license bytes. It reuses the whole-package-pinned extractor, includes only the
  KVP ELF, and checks the authenticated COPYING/GPL hashes. Source URLs and all
  exact source archive hashes accompany the binary. Authenticated full source is
  retained externally; this is not legal approval for redistributing binary media.
- The public record has a fixed 284-byte manually encoded parser-test CA with a
  deliberately INVALID dummy signature and a fixed all-zero leaf-pin sentinel.
  Only attempt/VM fields vary. It contains no generated/stored private key and
  must NEVER authorize a TLS peer. This tests the existing public codec and KVP
  plumbing, not certificate issuance, key possession or production authentication.
- `night_shifts/guest/bootstrap_public_probe.py`: an opt-in function, NOT a CLI or
  deployed boot hook. It requires independently trusted complete-seed digest and
  binding; the future launcher must verify bytes BEFORE importing them. Internal
  ZIP manifest/hash agreement is only consistency, not provenance.
- The guest checks Linux x86-64/kernel 6.8.0-139-generic, isolated/no-bytecode Python,
  root UID/GID, NNP and zero effective/permitted/inheritable/bounding/ambient
  capabilities, distinct mount/net namespaces, the fixed enforced AppArmor label,
  a readonly root view, fixed tmpfs execution/pool mountpoints and no writable
  persistent view, nested redirects or overmounted duplicate mountpoints. It
  requires no swap, loop/optical block-device names only, a sole DOWN loopback,
  the expected DMI VM GUID, fresh RAM directories, KVP char-device shape and no
  observed existing daemon. It never mounts, repairs permissions or fixes a check.
- Only after those checks does it create-new the pinned daemon in guest RAM,
  execute its fixed absolute path with `-n`, DEVNULL streams, empty PATH/fixed
  locale, closed inherited descriptors and a new session. It waits <=5 seconds
  for the five new empty pools, calls the **existing locked publisher once**, and
  holds the foreground daemon for 15 seconds for the later host read-back.
  Cooperative budget is 25 seconds plus bounded direct-child termination waits;
  blocking native calls still need the future external native watchdog.
- It attempts termination of only its new exact process session (TERM, then KILL
  after a bounded wait); uncertain direct-child exit dominates any local success
  with UNKNOWN. It never retries publication, rolls back, deletes retained files,
  powers off the guest or operates the host VM. A compact <=3000-byte JSON return
  records only fixed labels, public hashes, identities, time and local result.
  It does NOT claim host receipt, whole-process-tree absence or VM cleanup.
- `guest/bootstrap-public-probe.apparmor`: explicit candidate policy with no shell,
  KVP helpers, network, capability or general filesystem-write grant. It is **not
  loaded and has not passed a Linux parser/native test**. Its name alone cannot
  prove the loaded policy's contents. The future trusted launcher must pin/load
  the reviewed bytes and independently establish the mount/network confinement.

The guest daemon itself still supports host mutation/IP/helper operations. The
probe is valid only with an exclusive trusted host doing the reviewed read-only
KVP acquisition; no concurrent host pool writes. Confinement is defense in depth,
not a claim that the daemon becomes an intrinsically read-only implementation.
The complete PID view is required; a hidden existing daemon cannot be ruled out
by a private PID namespace. Guest-root adversaries and a malicious host are not
made safe by directory checks. Missing/mismatched prerequisites refuse, with no
weaker-mode, package-manager, shell, networking or service-enable fallback.

## Historical initial verification — corrected by the standard rerun below

The new synthetic tests cover deterministic inventory/metadata, external digest,
wrong binding, manifest rehash attempts against pinned assets, ZIP links/extra/
duplicate/trailing/prepended/compressed content, license pre-parse checks, invalid
fixture signature, unsafe mount/status/device models, mocked exact supervision,
preflight refusal before mutation, publication uncertainty, child exit/unknown
stop and exact-session escalation. They do not invoke the native preflight,
execute the daemon, query WMI, publish to a real guest or load AppArmor.

The first standard command, `python -m pytest -q tests/night_shifts/test_bootstrap_public_probe.py -rs`,
passed **47 and failed 2** in 0.85 seconds, with one deliberate duplicate-ZIP
construction warning. Both failures expose Windows `Path` semantics in Linux
path-model constants: the valid mount view and exact foreground command used
backslashes on Windows. This is a source portability defect, not a failed live
Linux execution. Repository Ruff passed. Mypy checked **82 files** and found
**8 errors** for unguarded Linux-only OS flags/process-group/signal attributes.
Strict warning-as-error compilation of all three new Python files passed.

The applied correction uses lexical POSIX constants on every host and a
Linux-guarded typed stdlib ABI for native helpers; there is no Windows execution
fallback or weakened path/mount policy. Reporting separates no-spawn-attempt
from confirmed direct-child exit and reports **UNKNOWN** if a spawn was attempted
but no process handle returned. `direct_child_started` reflects acquisition of
that child handle, not proof of process absence when false: `spawn_attempted=true`
with no handle remains UNKNOWN, with `direct_child_stopped=null`. New regressions
cover those cases, unready-daemon timeout, post-publication exit and exhausted
stop waits. The intentional duplicate-member warning is explicitly asserted.
These corrections passed the standard applied rerun recorded below.

The unchanged six-file extractor/bootstrap/credential/TLS/failure/native-store
selection passed **405 with 2 skips** in 4.55 seconds. It EXCLUDES the new probe
suite. Skips remain Linux disposable fds and unavailable unelevated symlink
creation, not successful native deployment. These are targeted, not full-repository
results. At this historical checkpoint the new probe suite and Mypy were not
green; the successful corrected rerun follows below.

The actual staged package and pinned license texts built and validated a
**154681-byte, 18-entry ZIP twice identically, entirely in memory**, with a
44712-byte pinned ELF and 632-byte fixed public record. Pre-correction seed
SHA-256 was `bc45f88b03fa9f17a9d5fa8c57b36eb200f48d4edfafdb1374b224e4dc17c088`;
this is a historical check, NOT a deployment pin, and must change/recheck after
the source correction. No seed or standalone ELF was written or executed.

The actual in-memory inspection ZIP had 31 entries and excludes all new probe
assets. All **48 staging artifacts / 244031259 bytes** still match the pinned
catalog. All **112 tracked night-shift/script files** match HEAD after canonical
LF comparison; no old runtime, adapter, fixture or bundle policy changed. All 20
checked local links resolve and `git diff --check` passed. No protected marker
or VM operation participated in these tests.

## Corrected applied verification — standard rerun passed

The standard seven-file targeted command ran with **warnings treated as errors**:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_public_probe.py tests/night_shifts/test_bootstrap_daemon_asset.py tests/night_shifts/test_public_bootstrap_kvp.py tests/night_shifts/test_maintenance_credentials_prototype.py tests/night_shifts/test_maintenance_tls_prototype.py tests/night_shifts/test_maintenance_failure_diagnostics.py tests/night_shifts/test_maintenance_store_native_prototype.py -rs
```

Result: **459 passed, 2 skipped in 3.72 seconds**, INCLUDING all **54 new probe
tests** and the 405 related tests above, not additional coverage on top of them.
There was no transient hook or runtime source substitution. The same two skips
remain Linux disposable fds and unavailable unelevated symlink creation. This is
a targeted offline result, not the full repository or native/Linux feasibility.
Repository Ruff passed and Mypy passed across **82 night-shift source files**.
Strict compilation passed for the three new Python files and all 11 packaged
Python entries. Those 11 entries also parsed under Python 3.12's syntax grammar;
this is NOT an executed Python 3.12/Linux import or ABI compatibility test.

The corrected snapshot built/validated twice identically using the actual pinned
package/license inputs, in memory only: **155769 bytes, 18 entries**, with the
same 44712-byte ELF and 632-byte public record. Corrected snapshot SHA-256:
`d357624a8a4709da838ce229b5223f27126dbd37ffb547c31e12fb3eaf30df12`.
This ordinary source-snapshot check is not protected deployment authority; any
future author/launcher must independently pin/recheck its reviewed complete code
and media inventory before import/use. No seed or standalone ELF was written.

Independent read-back again verified all **48 staged artifacts / 244031259 bytes**
against the pinned catalog. All **112 tracked night-shift/script files** still
match HEAD after canonical LF comparison. The actual 31-entry inspection ZIP
excludes the candidates; all 20 checked local document links resolve and
`git diff --check` passed. No existing runtime, adapter, frozen fixture, receipt
or bundle policy was modified, and no prior failed run was reclassified.

The seven-file source/test/documentation checkpoint was subsequently committed
as `50b61ee`. Keep its historical validation separate from the uncommitted
handoff/launcher work. Do not build media or run the probe manually. No dependency installation, elevation or restart is
needed. AppArmor parsing/native enforcement, Linux runtime behavior, boot handoff,
host receipt and VM cleanup remain unverified, not model-only successes.

## Next integration boundary, not covered here

This ZIP is intentionally not an ISO/NoCloud boot mechanism. Next review must
supply the fixed trusted recovery boot handoff and confinement launcher, verify
AppArmor parser/native behavior and the actual RAM/mount/runtime layout, then
implement/pin offline support media and the exact-owned diskless host runner.
Any need to change a prerequisite stops for source/policy review; never adapt it
inside a privileged run to make a test pass.

Before live use, require a fresh permanent claim, exact new GUID/name/sole Notes,
no disk/network/share/serial pipe, GSI/checkpoints disabled with read-back, pinned
read-locked recovery/support media, intended Secure Boot and separately reviewed
Data Exchange use. A protected code-pinned launcher/native watchdog must bound
both worker and VM lifetime. The host must independently observe the **complete
expected public record** via the existing exact-VM reader and capture a bounded
report, then independently confirm only that new VM's final absence. The guest
function's returned report is not yet connected to a trusted evidence transport
and is not that independent host receipt. Timeout does not prove VM stop.

A later successful public-only exchange still leaves real credential factories,
authenticated serial integration, image inspection/finalization/publication and
Gate A's separate transport/cleanup boundary. No extra native-store fixture is
needed here. No daemon execution, package installation, AppArmor load, service
change, elevation, WMI/KVP access, media write, VM operation, permission repair,
credential generation, retained-object change or restart occurred in this source
preparation. **Gate A remains unrun.**
