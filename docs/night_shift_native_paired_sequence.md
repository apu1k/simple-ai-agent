# Paired native sequence and confined pool controls — source candidate only

## Milestone and status

This wires the complete **nine denial/control workers** through the existing
single-worker owner/capture path and adds **two confined allowed-pool positive
workers**, before and after those triples: **eleven fixed workers total**.
**Applied and verified offline; not deployed or executed natively.** All
**106 new pool/sequence tests** pass. After updating one legacy rejection matrix,
the nineteen-file related selection passes **1,412 with two skips**, warnings
as errors. No runtime correction was needed. Application is not native execution
approval, media acceptance, a protected-runner installation or Gate A.

Before drafting, the committed seventeen-file related baseline passed **1,305
with two skips**, warnings treated as errors. Repository Ruff and Mypy across
**97 night-shift source files** passed; the working tree was clean. The skips
remain Linux-only disposable-fd behavior and unavailable unelevated symlink
creation, not native successes.

The new `bootstrap_native_sequence.py` is deliberately unwired and excluded
from public/production inventories. Import/constructor alone does not execute a
worker. **NativeValidationSequence.run() would spawn native children and read
native logs** through [the single-worker candidate](night_shift_native_kernel_capture.md).
It must not be called on the workstation, retained guest/image or outside the
separately reviewed isolated validation-VM route. There is no CLI, arbitrary
worker catalog, path/command/source choice, policy load, media/VM operation,
credential handling, host-receipt acceptance or deployment activation here.

## Exact sequence and ownership

```text
confined allowed_pools (all five fixed files)
runtime_write:       control -> confined -> control
pool_sibling_write:  control -> confined -> control
outside_exec:        control -> confined -> control
confined allowed_pools (all five fixed files)
```

There is no overlap, worker retry, alternate control or continuation after a
failure. The one-shot object consumes its run before the first fallible action;
a completed or failed object cannot resume. All eleven PIDs must be distinct,
all contexts must match the held fixture acquisition and all observed local
intervals must be ordered and bounded. A new object is not permission to repeat
an attempt; the future protected host operation must enforce one-attempt policy.

The sequence derives attempt/VM/seed context only from the existing held
NativeRamFixtures. It does not accept another binding/digest, close caller-owned
fixture handles, reuse artifacts or repair permissions/mounts. Each existing
single-worker call verifies those same pins before launch, after readiness and
after bounded collection. A changed/failed fixture context stops the sequence.

Each child still uses the fixed setpriv/fresh-Python plan, zero capabilities/NNP,
exact fd mapping/extra-fd closure and enforced-label read-back **before** worker
source evaluation. There is no new profile, earlier transition or retained
capability to make the positive path work. The existing three denial operations
and exact positive exit-37 executable remain unchanged.

For each negative child, actual collection and initial denial correlation occur
while its PID is still WNOWAIT-held. The helper then reaps it before another
worker starts. After control-after, the pure paired evaluator joins all three
observations and rechecks the captured negative interval. That second local
calculation does **not** claim the already-reaped negative PID is still held.
It must agree with the initial correlation; kernel sequence and audit serial
must strictly advance across the three cases. No raw worker/kernel output is
printed or accepted from an untrusted provider as authority.

## Fixed confined allowed-pool operation

One new case tag, `allowed_pools`, is accepted **only in confined mode** throughout
worker context, child entry, plan renderer, report core, native owner and capture
sequence. The denial catalog remains exactly the original three cases; this
positive tag cannot be treated as an EACCES denial or used with an unconfined
fallback. Its only successful report is `pools_checked`, errno zero, report EOF
and exact normal exit zero. Missing/partial/error reports cannot be positive.

The standalone worker uses only:

```text
/var/lib/hyperv/.kvp_pool_0
/var/lib/hyperv/.kvp_pool_1
/var/lib/hyperv/.kvp_pool_2
/var/lib/hyperv/.kvp_pool_3
/var/lib/hyperv/.kvp_pool_4
```

For each it checks root-owned mode-0600, single-link, one-byte regular-file
metadata and distinct held identities, then opens RDWR|NOFOLLOW|CLOEXEC|NONBLOCK
with **no create or truncate**. It obtains one nonblocking whole-file POSIX
record lock with lockf(LOCK_EX|LOCK_NB, length=0, start=0, SEEK_SET), not flock.
There is no lock wait/retry. All five locks remain held together while it:

1. Rechecks descriptor/path identity and reads exactly the fixed sentinel V.
2. Writes exactly V once at offset zero, without append/truncate or other data.
3. Reads back V and rechecks descriptor/path metadata.

The operation attempts explicit unlock and one close for every acquired file,
even after partial acquisition/write, deadline failure or uncertain cleanup.
Any lock/read/write/identity/flag/unlock/close error refuses positive success.
A possibly consumed fd is never re-closed. Rewriting V can legitimately change
mtime/ctime between supervisor checks; the held RAM verifier already permits
that while requiring unchanged bytes/inode/mode/owner/backing. No rollback of
possible writes or cleanup/absence receipt is claimed.

This tests the confined process's fixed record-lock/read/write syscall path.
It does **not** prove interprocess contention, daemon compatibility, public KVP
publication or AppArmor enforcement merely from a returned errno. Those native
integration obligations remain separate. The AppArmor policy is not broadened.

## Reviewed worker snapshot change

The standalone worker source changes to include that positive operation. The
child entry's independent hard pin is updated to canonical-LF SHA-256:

`2b6fc9a513525eb2d39a6a4c50ef050620228fc4ff596925c9a279fd86a9d3d2`

The applied canonical-LF source is **17,061 bytes**; independent rehashing and
the source-pin regression both match the child entry's hard pin. Applied-file
Ruff, Windows-hosted typing, Linux-targeted typing, in-memory compilation and
Python 3.12 grammar pass. These are offline/static/model checks, not native
execution. Full immutable-media review is still mandatory; a matching
local/source digest cannot authenticate a caller's guest or media.
The inert ELF, production launcher/policy and installed protocol worker do not
change. No candidate is added to the existing public or inspection payload.

## Time and summary boundaries

The sequence receives one original guest-monotonic outer deadline, at most
**60 seconds**, and one cancellation callback. Each **new** child gets
min(outer deadline, current guest time + 5 seconds), covering its full existing
launch/report/capture/reap sequence. This does not renew any existing child's
budget. The constructor and time between stages also consume the outer budget.
Clock regression, cancellation/callback failure, late helper return or any
incoherent observation is terminal. Failure cleanup may use the existing
separate one-second exact-child cleanup bound after expiration, but cannot
restore result acceptance or start another worker.

The local result contains the binding, two pool PIDs, three existing paired
observations and local start/finish times. Its **at-most-512-byte ASCII JSON
summary** has a fixed schema and explicitly says `local_consistency_only`.
It does not serialize raw captures, exception text, source, seed digest or a
native-pass/cleanup/Gate-A/host-receipt field. Ordinary callers can fabricate
these Python objects; no acceptance API authenticates them. The method returns
bytes only: no stdout, evidence-file writing or host publication occurs here.

Cooperative checks cannot force a hung native call/callback to return. The
independent host watchdog/evidence and exact-VM final-absence observation remain
mandatory. The collector's finite quiet tail is still **not** an audit flush
acknowledgment or proof of absence of silent/delayed kernel records.

## Applied offline tests and verification

`test_bootstrap_native_pools.py` replaces all native pool/lock/clock adapters and
uses the existing offline preflight/entry/owner/capture models to check the new
tag through the actual encoder/report evaluator/renderer/collector. No real
setpriv, lock, file write, child, profile transition or log access occurs.
`test_bootstrap_native_sequence.py` replaces native single-worker/fixture owners
but uses the real paired/audit evaluators on synthetic records. It checks the
exact eleven-step order, one-shot behavior, stopped/late/mixed observations,
missing or wrong attribution, context changes, bounded local summaries and real
in-memory payload exclusions. These are not Linux/kernel emulators or receipts.

Reproduce the applied checks:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_pools.py tests/night_shifts/test_bootstrap_native_sequence.py tests/night_shifts/test_bootstrap_native_capture.py tests/night_shifts/test_bootstrap_native_owner.py tests/night_shifts/test_bootstrap_native_child.py tests/night_shifts/test_bootstrap_native_ram.py tests/night_shifts/test_bootstrap_native_supervision.py tests/night_shifts/test_bootstrap_native_worker.py tests/night_shifts/test_bootstrap_native_denials.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/bootstrap_native_sequence.py night_shifts/guest/bootstrap_native_worker.py night_shifts/guest/bootstrap_native_child.py night_shifts/bootstrap_native_child_plan.py night_shifts/bootstrap_native_supervision.py night_shifts/bootstrap_native_owner.py night_shifts/bootstrap_native_capture.py --follow-imports=silent --platform linux
git diff --check
```

### Applied verification record

- New pool/sequence selection: **106 passed in 0.28 seconds**, warnings as
  errors, no skips or exclusions. Existing offline fixtures are reused; no
  native child, pool file, record lock or kernel-log device is used.
- Initial nine-file related check: **862 passed, one failed**. The failure was
  the old rejection matrix still rejecting the now-valid confined allowed_pools
  tag. The test-only follow-up rejects an unsupported lookalike and explicitly
  rejects allowed_pools in control mode. It preserves preflight-before-adapter
  refusal assertions and adds one net guard case; no runtime correction occurred.
- Post-repair nine-file pool/sequence/capture/owner/child/RAM/core/worker/audit
  selection: **864 passed in 1.26 seconds**, warnings as errors, no skips or
  exclusions. This includes the 106 new-file tests and the extra legacy guard.
- Wider nineteen-file related selection: **1,412 passed, two skipped in
  5.26 seconds**, warnings as errors, no exclusions. Counts overlap and must not
  be added. The skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation; neither is native success. This is not a
  full-repository runtime run.
- Repository Ruff and Windows-hosted Mypy across **98 night-shift source files**
  pass. Linux-targeted Mypy of all **seven changed source components** passes.
- All **ten checkpoint Python files** pass warning-as-error in-memory
  compilation and Python 3.12 grammar parsing. All **thirteen checkpoint files**
  pass final-newline/trailing-whitespace checks; **nine local document links**
  resolve; tracked `git diff --check` passes. Git reports normal CRLF-to-LF
  normalization notices for the two guest files; the canonical-LF worker pin
  and 17,061-byte size are independently checked.
- All seven changed source components remain excluded from the public support
  inventory and actual **31-entry inspection ZIP**, built only in memory. The
  installed protocol worker, production launcher/policy and protected deployment
  assets remain unchanged. No native or host-receipt acceptance path is added.

These are model/static/source consistency results, not kernel/AppArmor
validation, interprocess lock contention, authentic lossless audit capture,
trusted boot provenance or child/tree/VM absence. The remaining native and
protected-runner prerequisites below are not waived by these passing checks.

## Remaining diskless operation and Gate A boundaries

The next runnable milestone still needs a reviewed validation-only guest boot/
acquisition entry for the intended isolation/layout and add-only fixed policy,
complete immutable validation media, protected one-operation diskless host
runner, independent watchdog/evidence and independently verified exact-VM
absence. Resolve network/capability audit visibility and actual kernel
capture/transition feasibility before claiming complete native denial coverage.
No temporary permissive test policy or live repair is an acceptable substitute.

Only then can the separately approved native attempt provide native evidence.
Accepted image preparation, trusted real credential provisioning, authenticated
Hyper-V UART communication and Gate A lifecycle/cleanup integration remain
open. No elevation, native worker/lock/log operation, policy loading, media
writing, VM operation, deployment or commit is part of this checkpoint.
**Gate A remains unrun.**
