# Deterministic public support seed and fixed guest probe — applied correction pending

**Applied; offline checks found portability/reporting corrections still pending.
NOT deployed, bootable media or execution approval.** This advances the [reviewed daemon asset](night_shift_kvp_runtime_review.md)
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

## Initial applied verification — corrections required

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

Pending source correction uses lexical POSIX constants on every host and a
Linux-guarded typed stdlib ABI for native helpers; there is no Windows execution
fallback or weakened path/mount policy. A related reporting correction separates
no-child-started from confirmed direct-child exit and reports **UNKNOWN** if a
spawn was attempted but no process handle returned. New regressions cover those
cases, unready-daemon timeout, post-publication exit and exhausted stop waits;
the known duplicate-member warning is explicitly asserted rather than leaked.
**These corrections and new regressions have not yet passed an applied rerun.**

The unchanged six-file extractor/bootstrap/credential/TLS/failure/native-store
selection passed **405 with 2 skips** in 4.55 seconds. It EXCLUDES the new probe
suite. Skips remain Linux disposable fds and unavailable unelevated symlink
creation, not successful native deployment. These are targeted, not full-repository
results; the new probe suite and Mypy are not green yet.

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

After applying the correction: rerun the normal new-plus-related suite without
a transient test hook, repository Ruff/Mypy, strict compilation and the real-input
in-memory determinism/inventory checks against the corrected source snapshot.
Recheck preservation/links/whitespace before any commit recommendation.
Do not commit, build media or run the probe manually yet. No new dependency or
elevation is needed for verification; Linux policy/parser/native behavior remains
unverified and must not be replaced with a model-only claim.

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
