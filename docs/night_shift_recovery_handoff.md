# Recovery handoff and confinement launcher — verified offline, not deployed

## Current remote-session boundary

The operator is connected remotely through Tailscale. Continue ordinary-user
source review and synthetic tests only. Do not request elevation, load policy,
change services/networking/remote access, install dependencies, author deployment
media or launch a VM. Commits can wait until local access is available; retain
the existing uncommitted work and use exact, non-overlapping pending edits.

Committed baseline: `50b61ee` (public-only RAM support seed). The applied working
tree adds the handoff/launcher and two regression modules. Rejected superseded
pendings initially left newer tests paired with older launcher behavior. The
focused repairs are now applied and pass the standard offline rerun below.
The source remains uncommitted by operator choice, not blocked on a commit.
Historical support-seed validation is separate from this batch's new checks.

## Applied candidate, not execution authority

- `night_shifts/bootstrap_recovery_handoff.py` renders deterministic in-memory
  NoCloud `user-data`, `meta-data`, `network-config` and the support ZIP. It is not
  an ISO writer or a boot/deployment command. Only the existing fixed public
  parser fixture is accepted; no real credentials, generated keys or arbitrary
  script/file API is added.
- The complete seed pin is checked before snapshotting the standalone launcher.
  Launcher source is embedded in a fixed isolated Python command; the larger ZIP
  stays a data file on the same future CIDATA optical media. Command/user-data
  bounds are explicit. No package updates, installation or shell command API is
  provided by the renderer.
- `night_shifts/guest/bootstrap_recovery_launcher.py` is opt-in guest code with no
  import-time mutation. Its root boot function has no ordinary workstation CLI.
  It checks the exact runtime, guest GUID, root identity, block/network/swap
  isolation, RAM staging and absence of the fixed AppArmor profile before writes.
- A future approved invocation would create new guest RAM staging, mount only
  CIDATA read-only, verify the complete ZIP and policy pin, parse/add (never
  replace) the candidate policy, then create private mount/network namespaces.
  The child constructs a RAM root with read-only runtime views, fixed tmpfs seed
  and pool directories, chroots and drops all capabilities with NNP. Only after
  the full pin and enforced policy transition does it import the support code.
- Native commands have fixed argv, a minimal environment, no raw tool output and
  cooperative remaining-deadline timeouts. Failures after possible mutation stay
  UNKNOWN; no retry, repair, broad cleanup or VM operation is implemented.
  A subprocess timeout is NOT whole-tree absence or VM cleanup evidence.
- The foreground guest report remains local public output, not independent host
  receipt. The existing exact-VM reader, trusted media provenance and protected
  host watchdog/lifecycle controller are not wired into this candidate.

## Historical reconciliation failures — now corrected

Standard applied command, without source substitution or a temporary hook:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_recovery_handoff.py tests/night_shifts/test_bootstrap_recovery_native_policy.py -rs
```

Result: **37 passed, 8 failed**. These are synthetic failures, not a live Linux
attempt. One failure is a truncated short read; one is rejection of an unused
loop device; five downstream isolation cases stop at that same loop check; one
shows `/sys` being bound from the old network namespace instead of freshly
mounted in the new one. Repository Ruff reports **two unused imports**. Mypy
passes across **84 source files**. `git diff --check` passes for applied tracked
changes (that alone does not validate untracked files).

The unchanged seven-file seed/asset/KVP/credential/TLS/failure/native-store
selection passes **459 with 2 skips in 4.11 seconds**, warnings as errors. It
EXCLUDES both new handoff suites. Skips are Linux-only disposable-fd behavior and
unavailable unelevated symlink creation, not successful native checks. These are
targeted tests, not a full-repository run.

## Applied repairs — standard rerun passed

1. Continue bounded reads through short chunks to EOF, enforcing the aggregate
   limit and always closing the descriptor. Partial writes remain UNKNOWN and
   are never retried.
2. Distinguish an unconfigured loop device from actual writable backing. Only
   FileNotFoundError on the backing attribute permits the unused case. An active
   loop and every optical device still require the observed read-only flag;
   empty backing attributes and other access errors do not establish absence.
3. Mount fresh read-only sysfs after entering the new network namespace; do not
   bind the old `/sys` view. Keep the complete PID view; no private PID namespace.
4. Remove the two unused imports. Adapt only the synthetic backing-attribute
   fixture and add aggregate-overflow, descriptor-error and backing-state cases.

All four repairs above are applied. The new tests also cover read-only active
backing, empty backing and permission errors that must not establish absence.

The standard nine-file targeted selection ran without a temporary hook or source
substitution, with warnings as errors:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_recovery_handoff.py tests/night_shifts/test_bootstrap_recovery_native_policy.py tests/night_shifts/test_bootstrap_public_probe.py tests/night_shifts/test_bootstrap_daemon_asset.py tests/night_shifts/test_public_bootstrap_kvp.py tests/night_shifts/test_maintenance_credentials_prototype.py tests/night_shifts/test_maintenance_tls_prototype.py tests/night_shifts/test_maintenance_failure_diagnostics.py tests/night_shifts/test_maintenance_store_native_prototype.py -rs
```

Result: **509 passed, 2 skipped in 4.02 seconds**, INCLUDING all **50 handoff
regressions** and the earlier 459 related tests, not 509 plus those earlier
counts. Skips remain Linux-only disposable fds and unavailable unelevated symlink
creation. Repository Ruff passes; Mypy passes across **84 source files**. This
is a targeted offline result, not the full repository or live/Linux validation.

Actual pinned package/license inputs produced identical support ZIPs and
four-file handoffs twice, entirely in memory. The ZIP has **18 total entries**
(17 validated payload entries plus the manifest), **155769 bytes**, and retains
the committed support-seed snapshot SHA-256:
`d357624a8a4709da838ce229b5223f27126dbd37ffb547c31e12fb3eaf30df12`.
Handoff sizes: user-data **23793**, meta-data **114**, network-config **29**,
support.zip **155769** bytes. The embedded Python command is **23569 bytes**,
below the explicit 100000-byte bound. Source decoding and the independently
computed embedded-launcher hash agree. Current ordinary snapshot hashes:

- Launcher: `d50695feb596f578718179c91de133ef659fd90cf4832e7b9c525b4c2291e3c2`.
- AppArmor policy: `05e702c364a532679456826e22d6d28e108222ea387df6a690141e60194a166a`.

These are checked source snapshots, NOT protected deployment pins, authentic
boot evidence or permission to execute. No seed, standalone ELF or media was
written. In-memory warning-as-error compilation and Python 3.12 grammar parsing
pass for all four new Python files, all 11 packaged Python entries, the embedded
command and decoded launcher. This does not execute Python 3.12 on Linux or
establish utility, import, ABI or kernel compatibility.

Independent streaming read-back confirms all **48 staging artifacts /
244031259 bytes** still match the pinned catalog, whose own hash also matches.
The actual **31-entry inspection bundle** excludes the candidate handoff, seed,
daemon and probe assets. `git diff --exit-code HEAD -- night_shifts scripts tests`
passes for existing tracked sources/tests; it does not include untracked files.
The four new Python files and four current status/review documents separately
pass final-newline/trailing-whitespace checks. All **23 checked local document
links** resolve and `git diff --check` passes. Protected claims, frozen scripts
and prior failed-run classifications are not changed by this work.

The eight-file uncommitted source/test/documentation checkpoint is verified
for offline development after recording these results. It is not deployment,
media-authoring, policy-loading or live-test approval. No dependency installation,
elevation, native guest command, daemon, policy load, service/network/remote-access
change, WMI/KVP operation, VM operation or restart occurred.

## Remaining path, with no remote-session elevation

Offline source/model validation can continue without a commit. Do not convert
mocked parser/mount/transition traces into Linux evidence. Actual AppArmor parser
compatibility, NNP/zero-capability transition, confinement denials, utility/ABI
availability and RAM/mount layout remain unverified and may require source
review changes. No weaker mode or runtime permission repair is allowed.

The [native-confinement review scope](night_shift_native_confinement_review.md)
and test-only `test_bootstrap_confinement_contract.py` harness are now applied
and verified offline: **39 new checks pass**; the combined ten-file selection
passes **548 with 2 skips in 4.00 seconds**, including the earlier 509 checks,
with warnings as errors. The harness models the launcher's recorded mount argv
against the probe's real checker and injects phase failures; it does NOT execute
native tools or establish Linux enforcement. Repository Ruff, Mypy across 84
night-shift files, strict compilation/Python 3.12 grammar, bundle exclusion,
ordinary launcher/policy snapshot pins, links and whitespace checks pass. This
separate test/document checkpoint required no runtime source repair or reload.
It does not repeat the historical full staging rehash or actual-input handoff
build, and it does not turn those results into native validation.

After that offline checkpoint, design the fixed native denial validator and
controls, then deterministic media and the exact-owned diskless host runner/
watchdog. Preparation does not authorize a native run. Any future live attempt
requires fresh explicit approval, complete externally pinned and read-locked
recovery/support media, exact fresh VM ownership, no disk/NIC/shared folder/serial
pipe, independent public-record receipt and confirmed final VM absence. A
media-internal hash or guest-provided identity is not provenance.

Public-only feasibility would still leave real credentials, authenticated serial
integration, accepted image finalization/publication and Gate A's independent
bounded transport/cleanup requirements. No additional marker-store fixture is
needed for this handoff checkpoint. **Gate A remains unrun.**
