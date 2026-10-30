# Native validator supervision protocol core — source candidate only

## State and immediate blocker

**Applied and verified offline; not deployed or executed natively.** The
transport validation harnesses are committed through `811a454`. Windows portable
transport checks do not substitute for Linux execution. This batch implements
the pure report/state and paired-control evaluation component of the
[fixed native-validator requirements](night_shift_native_validator_design.md).
Native guest supervisor acquisition, process ownership and integration remain
unimplemented; this is not a runnable validator.

Before application, the committed worker/audit two-file baseline passed **190**,
warnings as errors. After application, the three-file worker/audit/core selection
passes **297**, including **107 new tests**. The wider thirteen-file related
selection passes **845 with two skips**. Those applied results are recorded
below; they are not native enforcement or a full-repository test run.

`night_shifts/bootstrap_native_supervision.py` supplies a pure bounded protocol
core and paired local evaluator. It does **not** create a process, write a gate,
wait/reap/signal a child, capture a log, create a fixture, load policy, author
media, provision a credential or perform a VM operation. There is no CLI, boot
activation, host-receipt acceptance API or production deployment integration.

## Fixed report/state contract

`WorkerReportSession` takes an externally trusted AttemptBinding, one of the
three existing case IDs, control/confined mode, expected exact owned child PID
and its original absolute deadline. It cannot discover PID ownership or trust
an identity learned from a worker frame. PIDs are bounded to the existing
worker/correlator range, and one deadline allows at most five seconds.

The incremental report parser accepts ASCII newline-delimited JSON from the
existing worker encoder, with **256 bytes per frame including newline, two
frames and 512 aggregate bytes**. Duplicated fields, unsupported fields/phases,
wrong identity/types, oversized or incomplete frames, extra frames and invalid
observation/errno combinations stop. Input chunks are bounded before buffering.
No raw worker/audit bytes appear in errors or local result objects.

The required order is:

```text
ready → caller-observed gate release → result → report EOF → exact normal exit
```

- A ready frame cannot release a gate by itself. `mark_gate_released()` records
  a trusted caller observation; it does not write G, close a descriptor or prove
  a fresh audit cursor was acquired. Pending pre-release bytes, duplicate gate
  marks and results arriving before release refuse.
- EOF alone is not exec success. Only the fixed **positive outside_exec control**
  may omit the result frame, and only with independently observed normal exit
  **37**. A confined worker taking that route is an unexpected allowed execution.
- Write controls require `control_written`, errno zero, report EOF and normal
  exit zero. Confined results require syscall EACCES, report EOF and normal exit
  zero. An unexpected allowed open fails; other errno or incomplete/abnormal
  exit cannot become AppArmor attribution.
- `finish_exit()` must be called using an actual exact-child normal-exit
  observation. It does not perform that observation or reap. A signal, timeout,
  raw wait status, another PID or worker-supplied exit field is not a substitute.
- Clock regression, callback failure, cancellation and deadline expiry are
  terminal UNKNOWN states. The deadline is not renewed at ready, release or a
  result. A terminal session cannot be reused; a new object is not permission
  to repeat a live attempt. Clock/cancellation callbacks are trusted local code,
  not enforcement against a hung provider or proof of monotonic provenance.

## Paired controls and local audit consistency

A completed session returns frozen `LocalWorkerObservation` data: binding,
case/mode/PID, normalized observation/errno/exit and local start/finish times.
These values are consistency observations, **not authenticated native receipts**.
They can be fabricated by an ordinary Python caller, as synthetic tests do.

`correlate_paired_case` requires control-before, confined and control-after with
the same binding and fixed case, three distinct PIDs, valid control/result
semantics and nonoverlapping ordered local intervals. Broken or mixed controls
refuse before looking at audit records. It then invokes the existing strict
`correlate_local_denial` on the supplied bounded capture and exact confined PID.
Missing/unattributable logs remain UNKNOWN; raw records are never returned.

The frozen `LocalPairedObservation` contains only binding, fixed case, the three
PIDs, kernel sequence and audit serial. It has **no validator-pass, host-receipt,
fixture-authenticity or cleanup field**. Matching IDs/times/errno and synthetic
kernel strings cannot establish a real boot, isolation, unchanged RAM fixtures,
authentic lossless capture or unreaped native PID ownership. Capture boundaries
and their actual ordering relative to the gate remain native-runner obligations.

## Executable source tests and inventory boundary

`tests/night_shifts/test_bootstrap_native_supervision.py` covers fragmented and
boundary-size reports, actual worker message encoding with substituted write/
clock/getpid adapters, identity/phase/gate violations, malformed/bounded JSON,
missing/abnormal exits, fixed positive-exec handling, wrong errno, terminal
budget failures, mixed/broken controls and exact local audit matching/refusal.
It uses the actual correlator with **synthetic** kernel-format records. No
worker preflight/operation, executable fixture or native log is run/read.

The passing inventory regression builds the actual inspection ZIP in memory
and checks that the new module remains excluded there and from the public seed
source list. Neither inventory, the existing worker/launcher/policy nor any
protected helper is edited. No other night-shift source references the new
module; it remains unwired.

Reproduce the applied checks:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_supervision.py tests/night_shifts/test_bootstrap_native_worker.py tests/night_shifts/test_bootstrap_native_denials.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/bootstrap_native_supervision.py --follow-imports=silent --platform linux
git diff --check
```

### Applied verification record

- Three-file worker/audit/core selection: **297 passed in 0.50 seconds**, warnings
  treated as errors, with no skips. This includes **107 new supervision-core
  tests** plus the existing 190 worker/audit tests.
- Wider thirteen-file related selection: **845 passed, two skipped in
  5.19 seconds**, warnings treated as errors, with no exclusions. This includes
  the 107 new tests and the prior 738 related passes; the counts are not additive
  to the three-file selection.
- The two skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation. Neither is a native success. The new session,
  gate, exit and paired-control checks use modeled clocks/reports/exit inputs.
  Actual worker encoder compatibility is tested with substituted write/getpid/
  clock adapters, not a native child, executable control or policy transition.
- Repository Ruff and Mypy across **92 night-shift source files** pass.
  Linux-targeted Mypy of the new source also passes. The typing result is not
  Linux execution or native ABI validation.
- Both new Python files pass strict warning-as-error in-memory compilation and
  Python 3.12 grammar parsing. This is not execution on Python 3.12.
- All four checkpoint source/document files pass trailing-whitespace and final
  newline checks; **six local links** resolve; tracked `git diff --check` passes.
- The actual **31-entry inspection ZIP**, built in memory only, and the public
  seed source inventory exclude the core. Canonical-LF launcher and AppArmor
  policy hashes match the existing reviewed snapshots. No policy is loaded.
- Existing tracked `night_shifts`, `runtime`, `scripts` and night-shift test
  assets match HEAD; the new untracked core/test sources are checked separately.
  No existing production importer, runtime or protected helper is changed.

No test/runtime source repair was needed after application. The verification-
record changes are documentation-only. Source application, passing models,
typing and grammar checks cannot be recorded as native enforcement.

## What still prevents a runnable validator

This verifies only the offline protocol/evaluation component. The real guest
supervisor still needs:

1. Apply and verify the [native RAM fixture acquisition candidate](night_shift_native_ram_fixtures.md),
   then integrate its held before/after pins with each worker. That candidate
   creates the fixed RAM sentinels but does not run the confined allowed-pool
   read/write/record-lock controls; those still need their trusted child entry.
2. Apply, verify and integrate the [fixed child bootstrap and launch-plan candidate](night_shift_native_child_bootstrap.md):
   exact fd mapping and capabilities/NNP/profile ordering before worker evaluation.
   Native spawn enforcement, exact child ownership and actual transition behavior
   remain unverified; no privileged fd may reach the worker.
3. Bounded native pipe I/O and exact-child pidfd/WNOWAIT lifetime handling,
   retaining the unreaped negative PID through capture before exact reaping.
4. Fresh authentic lossless `/dev/kmsg` capture after ready and before release,
   bounded through collection; no journal/dmesg/userspace-text fallback.
5. Full supervisor sequencing for the fixed nine workers and a bounded summary.
   Network/capability audit observability remains unresolved; this component
   neither changes policy nor claims complete denial coverage.

Then immutable reviewed media and a protected exact-owned diskless host runner,
independent watchdog and evidence path still need completion and separate
execution approval. Native confinement/KVP feasibility, accepted image, real
credential bootstrap and authenticated VM communication remain prerequisites of
the selected autonomous Gate A route, not results of this source component.

No elevation, policy load, fixture/worker execution, media write, VM/service/
network operation, deployment, reload or commit is part of this batch.
**Gate A remains unrun.**

Related: [fixed worker protocol](night_shift_native_worker_review.md),
[confinement scope](night_shift_native_confinement_review.md),
[Linux transport harness](night_shift_linux_guest_tls_validation.md),
[Gate A preflight](night_shift_hyperv_preflight.md).
