# Native kernel-log capture and single-worker sequence — source candidate only

## Diskless validation milestone and status

This implements the /dev/kmsg acquisition/collection component and wires a
**single fixed worker** to the [exact-child owner](night_shift_native_child_owner.md),
held RAM fixtures and existing denial correlator. It is not the complete paired
nine-worker validator, a boot entry, protected runner or Gate A operation.
**Applied offline runtime checks pass; native behavior remains unverified.**
The collector-only selection passes **107 tests**, and the wider related
selection passes **1,305 with two skips**, warnings treated as errors. A narrow
Windows-hosted typing declaration follow-up is recorded below. Source
application is not native execution approval.

Before drafting, the committed sixteen-file related baseline passed **1,196
with two skips**, warnings treated as errors. Repository Ruff and Mypy across
**96 night-shift source files** passed; the working tree was clean. The skips
remain Linux-only disposable-fd behavior and unavailable unelevated symlink
creation, not native successes.

`bootstrap_native_capture.py` remains outside public/production inventories.
Import alone does not acquire resources. **NativeKernelCapture construction
would open/read native /dev/kmsg; observe_fixed_worker would spawn a native
worker.** Neither may be invoked on the workstation or in an existing guest as
a validation shortcut. There is no CLI, caller-selected log path, command,
backend, profile, policy load, media write or new protected operation.

## Fixed device and cursor acquisition

The collector requires the pinned Linux x86-64/kernel/Python prerequisites,
isolated/no-site/no-bytecode Python, root without supplementary groups, exact
minimal environment, one kernel task and unconfined supervisor label. Established
private guest layout and complete externally reviewed immutable-media/tool
identity remain prerequisites; a guest device node is not host provenance.

It opens only `/dev/kmsg`, read-only with NONBLOCK, CLOEXEC and NOFOLLOW. It
requires a root-owned single-link mode-0600 character device, major/minor 1:11,
checks path/fd identities, nonblocking and non-inheritable flags, and rechecks
them around collection. Unexpected permissions/device identity refuse; no
chmod/chown, remount, alternate path or logging service is started.

A single SEEK_SET to the oldest available record is followed by a bounded drain
until EAGAIN to establish the actual last sequence. **SEEK_END alone does not
provide a known baseline sequence.** No invented baseline, writable marker,
seek-after-overflow or retry with a larger read buffer is used.

Baseline acquisition is bounded to **4,096 records and 4 MiB read**, under the
original worker deadline. It retains only one record/header at a time. It
requires a nonempty real baseline, contiguous observed sequences, nondecreasing
nonfuture kernel timestamps and enough counter space for the capture. Old
records predating the oldest available baseline are not claimed to be captured.
Historical device metadata bodies and continuation flags may be discarded here:
only their whole-record header/sequence is used, never historical audit
attribution. This does not relax the actual capture grammar.

The start timestamp is sampled before the final empty baseline read. Thereafter
the cursor is never repositioned. Pending records after that cut remain in the
same reader for collection after the child's exit observation.

## Bounded collection and explicit uncertainty

Actual capture accepts only complete single-line printable-ASCII records with
the existing strict header/flag shape and final newline. It neither concatenates
reads nor salvages multiline device metadata, continuation fragments or unknown
native formats into an attribution. The existing correlator independently checks
kernel facility and exact AppArmor fields before any local denial correlation.

- At most **64 records, 8,192 bytes per record and 65,536 aggregate bytes**.
- Whole-record reads use an 8,193-byte buffer to detect over-bound input. Linux
  /dev/kmsg's whole-record-or-error behavior must still be validated natively;
  EINVAL, EPIPE/overflow, EOF, interruption or another read error is terminal.
- Sequence gaps/duplicates/stale records, backwards/out-of-window timestamps,
  malformed records and device/path/flag changes stop. No stream repair, cursor
  reset, journal/dmesg fallback or userspace-log substitution exists.
- Explicit suppression/rate-limit/audit-lost/backlog-limit markers stop, even
  when seen in baseline history. The conservative marker filter may refuse a
  benign message; it never authorizes a permissive live retry.
- Collection includes a fixed **100 ms quiet tail**, reset on each arriving
  record. It consumes the original deadline; it cannot extend it. The endpoint
  is sampled before the final empty read, not after a later operation might have
  allowed another record beyond that logical cursor cut.

One original at-most-five-second guest-monotonic deadline covers fixture checks,
launch rendering/startup, readiness, baseline, gate, reports, exit, collection,
correlation and exact reap. The collector uses integer monotonic nanoseconds,
converted to kernel-header microseconds, while the owner retains its existing
same-kernel monotonic deadline. No host-clock timestamp is copied to the guest.
Poll waits are sliced to at most 20 ms by the reviewed owner helper. Checks and
trusted callbacks cannot bound a hung kernel call or process startup; the
independent host watchdog is still mandatory.

**Quiet is not a kernel audit flush acknowledgment or proof that no future
async record can arrive.** This code detects observed gaps/errors/markers; it
cannot prove absence of silent kernel audit suppression or records delayed past
its finite interval. Missing/unattributable denial remains UNKNOWN. Actual
emission behavior, kernel clock compatibility, device ABI and audit visibility
must be established in the separately approved native route before claiming
lossless native attribution. No synthetic interval is accepted as evidence.

## Integrated fixed single-worker order

`NativeRamFixtures.launch_context()` supplies only the held acquisition binding
and seed digest, refusing failed/closed fixtures. It is not fresh verification
or a receipt. The integration derives child context from those pins rather than
accepting a second caller-selected binding/digest. It enforces:

```text
held fixture context -> verify fixtures -> fixed child spawn -> await ready
  -> verify fixtures -> acquire fresh kernel cursor -> release gate once
  -> observe normal exit WNOWAIT (do not reap)
  -> finish bounded collection/quiet tail -> verify fixtures
  -> confined denial case: existing exact local EACCES/audit correlation
  -> allowed_pools positive case: exact positive report, no manufactured denial
  -> close log successfully -> explicit exact reap
```

The exact exited child stays unreaped through collection, fixture verification
and correlation. All calls receive the same deadline/cancellation callback.
Controls use the same collector but do not manufacture a denial; an empty
control interval is allowed. Confined denial observations require the actual
strict correlator. The fixed confined allowed_pools positive tag instead requires
its exact all-five-files report, errno zero and normal exit zero; it cannot turn
an EACCES into positive success. This function does not replace the
before/confined/after evaluator or claim native-validation success.

Every failure discards the result and attempts both log close and the owner's
one-shot exact-child abort. A constructor handles its own partial acquisition.
An uncertain close/wait/reap is never retried by those components; cleanup
uncertainty overrides another failure. Caller-owned fixture handles/artifacts
are retained for their existing owner, not deleted or re-acquired here.

LocalKernelInterval contains bounded raw records for trusted in-memory use by
the existing paired evaluator. Raw records are excluded from repr and all
exceptions; they must never be serialized (including dataclass asdict), printed,
logged or forwarded in the guest summary/chat/host receipt. LocalCapturedWorker
contains only the worker observation, hidden interval and optional local denial
correlation. Ordinary Python callers can fabricate these objects: there is no
native-pass, cleanup-pass, boot-authentication or receipt-acceptance field.

## Offline verification

The new tests replace all native log/OS/clock/poll/runtime-reader adapters and
worker/fixture owners. They exercise actual collection and the actual strict
correlator on synthetic records, including integrated order and held-child
checks. Existing owner/fixture models remain separately exercised. No native
log is opened, worker spawned, ELF run, policy transitioned or signal sent.

Coverage includes baseline/capture distinctions, device/flag changes, sequence
and clock boundaries, exact record/count/total-byte limits, explicit loss and
read faults, finite quiet tails, shared deadlines/cancellation, all six fixed
case/mode combinations, missing/misattributed denials and cleanup failures. Two
additional RAM tests cover held context without new I/O and failed/closed
context refusal. Inventory regression builds only the in-memory inspection ZIP.

Reproduce the applied checks and verify the declaration follow-up before committing:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_capture.py tests/night_shifts/test_bootstrap_native_owner.py tests/night_shifts/test_bootstrap_native_child.py tests/night_shifts/test_bootstrap_native_ram.py tests/night_shifts/test_bootstrap_native_supervision.py tests/night_shifts/test_bootstrap_native_worker.py tests/night_shifts/test_bootstrap_native_denials.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/bootstrap_native_capture.py night_shifts/bootstrap_native_ram.py --follow-imports=silent --platform linux
git diff --check
```

### Applied verification and declaration follow-up

- Collector-only selection: **107 passed in 0.25 seconds**, warnings as errors,
  no skips or exclusions. OS/log/clock/poll/worker/fixture adapters are replaced;
  collection and the real correlator process synthetic records only.
- Seven-file capture/owner/child/RAM/core/worker/audit selection: **757 passed in
  1.27 seconds**, warnings as errors, no skips or exclusions. This includes all
  107 collector tests, the two new held-context RAM tests and prior 648 passes.
- Wider seventeen-file related selection: **1,305 passed, two skipped in
  5.18 seconds**, warnings as errors, no exclusions. Counts overlap and must not
  be added. The skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation; neither counts as native success. This is not a
  full-repository runtime run.
- Repository Ruff and Linux-targeted Mypy of capture/RAM pass. Initial Windows-
  hosted Mypy across **97 source files** reported two errors because its
  stat_result type lacks Linux's st_rdev field. The narrow follow-up declares
  that field through a read-only Linux Protocol after the existing Linux guard;
  it neither removes nor weakens the character-device/major/minor checks.
- The repaired collector candidate passes **in-memory Windows/Linux Mypy and
  Ruff**, warning-as-error compilation and Python 3.12 grammar parsing. No
  candidate source is executed or written by those checks. Applied-file Mypy
  and regression checks remain the required final confirmation before commit;
  use the commands above. No runtime or test correction was needed.
- Four checkpoint Python files pass warning-as-error in-memory compilation and
  Python 3.12 grammar parsing; all six checkpoint files pass final-newline and
  trailing-whitespace checks; **three local document links** resolve; tracked
  `git diff --check` passes.
- Passing inventory regressions build the actual inspection ZIP in memory and
  confirm capture remains excluded there and from the public support source
  list. No other night-shift source imports it. Existing tracked changes are
  limited to the RAM acquisition context accessor, its model tests and owner
  documentation, alongside the three new capture/test/document files.

At the capture-only checkpoint, the installed worker, reviewed worker/bootstrap
source pins, AppArmor policy, public seed/production inspection inventory and
protected helper were unchanged. The paired-sequence follow-up below explicitly
updates the validation worker source pin; it does not modify the installed
protocol worker, production policy/launcher, inventories or protected helper.
Passing models, cross-target typing and grammar checks are not native kmsg,
clock, pidfd, AppArmor, lossless-attribution or VM-cleanup observations.

## Remaining runnable milestone

The [paired sequence and confined pool-control candidate](night_shift_native_paired_sequence.md)
now implements the complete nine-worker order, bracketed by two confined all-
five-pool read/write/record-lock workers, with a bounded local summary. All
**106 new tests** and **1,412 combined related tests with two skips** pass after
one legacy test-only matrix update. Ruff, Mypy across **98 source files**,
Linux-targeted typing, the worker pin and inventory exclusions pass. This remains
an unwired source candidate, not native execution or authenticated evidence.
Resolve network/capability audit visibility before claiming complete denial
coverage. Then
review immutable complete media and the protected single diskless VM operation,
independent watchdog/evidence and independently verified exact-VM absence.

These are still prerequisites of the selected autonomous route. Image
acceptance, trusted real credential bootstrap and authenticated Hyper-V UART
communication remain open. No elevation, native log access/worker execution,
media writing, VM operation, deployment or commit is part of this checkpoint.
**Gate A remains unrun.**
