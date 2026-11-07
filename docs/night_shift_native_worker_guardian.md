# Provisioning worker lifetime composition — unwired candidate

## Status and boundary

**Applied and verified offline; not installed or exercised natively.** All
**83 new tests** pass, including **78 CLR scenarios** and compilation of all
eight actual C# sources together. The fresh thirty-six-module related selection
passes **2,661 with two skips**, warnings as errors. This is the first composition
slice of the worker-integration milestone, not completion of that milestone or
a runnable protected operation.
It connects the actual canonical request codec, pre-import acquisition/claim
body and process-guardian lifecycle in one same-assembly C# worker owner:
`scripts/native_validator_worker_guardian.cs`.

The current native process adapter launches the C# worker from the separate
guardian; it is NOT a Python launcher. This candidate deliberately cannot use
that adapter as a fallback. Its distinct internal `IWorkerPythonKernel` has
**no installed implementation or live default**. The subsequent
[fixed Python adapter and private entry candidate](night_shift_native_worker_windows.md)
is now applied and verified OFFLINE, NOT installed or exercised natively. Its
**76 new tests** pass, including **26 CLR scenarios** and compilation of all nine
actual C# sources together; the fresh thirty-seven-module related selection
passes **2,737 with two skips**, warnings as errors. It adds a separate native
adapter, a bounded non-secret argument frame and conservative QPC-to-Python
deadline translation. This owner's immutable context now carries the SAME
internal clock used by its lifetime checks. The **83-test** and **2,661-test**
records below concern the preceding committed lifetime checkpoint, not the new
adapter/context/entry validation. That component's document records its applied
verification and narrow fixture/typing repairs; no C# source repair was needed.
There is still no public constructor, `Main`, installer, tool wiring or installed
executable route. The C#/Python split and original outer guardian adapter remain
unchanged.

**Never compile or load checkout code elevated.** Trusted OS/CLR/executable/load
provenance, authenticated permanent whole-attempt approval, protected request
and original-deadline delivery, and an independent protected process watchdog
must precede this assembly. The owner cannot establish those prerequisites by
checking its subsequent imports. Hashes and immutable local objects are
consistency data, not authority or protected transport.

Related bodies:

- [Canonical installation request](night_shift_native_install_request.md).
- [Pre-import acquisition, claim and held request](night_shift_native_install_boundary.md).
- [Process guardian](night_shift_native_process_guardian.md).
- [Python-side provisioning handoff](night_shift_native_worker_handoff.md).

## Fixed composition

Construction requires independent outer-request length/hash, budget/expiry,
internal fixed file/process dependencies, one clock and a MANDATORY already
earlier absolute deadline in that clock's origin. It performs no file/token/
claim/process operation. The owner wraps the clock once, refusing nonfinite
readings and observed rollback. Budget/UTC expiry can shorten, never extend,
the supplied cap. Five seconds for process stop/observation remain INSIDE the
window. A cap with no remaining execution window refuses before native work.

`Run(raw)` is serialized and disarmed before decoding or I/O:

1. Require the original execution window. Independently hash the bounded outer
   request before the actual strict CLR codec parses/canonicalizes it.
2. Require exact equality to the independent budget/expiry. Derive BOTH plans
   from these bound inputs; there is no separately supplied import/process plan.
3. Construct the real import boundary and process core using the SAME clock and
   earlier cap. Acquisition may not consume the stop reserve.
4. Require the future adapter's fixed WORKER host role before import-claim
   creation. The process core requires that role again before job setup. The
   candidate does not provide a native implementation of that role check.
5. Acquire and retain the complete fixed import closure and permanent import
   claim with the existing boundary. A malformed request does not consume this
   claim; the prerequisite protected whole-attempt approval must independently
   handle malformed input and failures/cancellation before this point.
6. At the process core's pre-create gate, call ONLY the lease's fixed
   `CopyWorkerRequest()`. That method completely checks the held closure before
   and after copying. Construct a bounded immutable launch context from those
   ACTUAL held bytes and the independently derived worker pin, outer hash,
   identities/paths, budget/expiry and earlier execution deadline. Never use the
   codec's in-memory projected bytes instead of reading the held request.
7. Stage that context through the internal Python-kernel seam. Staging MUST NOT
   start/resume a process. Check the window again before the core marks creation
   attempted and crosses `CreateSuspended`. The context returns fresh byte
   copies, so a recipient cannot mutate the retained request snapshot.
8. After creation but before primary-thread resume, reverify the complete held
   import closure using the same handles, then recheck the window.
9. Use the actual process core's exact-owned observation/stop/closure sequence.
   Return only its local process observation after permitted import closure and
   a final original-window check. Exit zero is NOT provisioning acceptance.

The process plan uses the bound launch root only as fixed context for the
internal adapter. This code does not acquire executable targets or scratch;
those locks and trusted load policy remain obligations of the separate outer
held-target guardian/starter. The worker owner must eventually be hosted in the
fixed, already contained worker, not co-located with the independent guardian.

## Import lifetime and failure

The import lease is NOT wrapped in an unconditional `using` or `finally`.
It is released only when the actual process core's terminal
`LaunchTargetsReleasable` fact permits it: no creation attempt with checked
closure/window, OR successful checked empty-job/root observations, closes and
the original cap. The fact's existing name is retained; it does not authenticate
anything and is not a protected absence receipt.

Any core exception after creation was attempted conservatively keeps the whole
import lease, including if the exact-job stop may have worked. Reverification
failure can poison the lease but cannot unlock it. There is no public disposal,
reset, retry, finalizer or reconciliation shortcut. A retained-owner flag means
ownership was deliberately kept, not proof of native handle validity. The
future protected route must retain this owner and establish exact child absence
before host exit/reconciliation; OS locks do not survive worker death.

Pre-create refusal with checked process-core closure may release a poisoned
lease because that core has not attempted creation. Acquisition failure retains
no returned lease and uses the boundary's existing checked closure. Import
close uncertainty is terminal; the single disposal attempt is never repeated.
Unknown exception text is reduced to fixed labels. A new owner cannot overwrite
or bypass the same fixed import claim. Claims never become acceptance or retry
permission. Protected cancellation/early-failure policy is still external.

## Verification scope

Fresh committed baseline before drafting: **529 passed in 4.48 seconds**, warnings
as errors, across the import boundary, installation request codec, process
guardian and Python worker handoff. Repository Ruff and Windows-hosted Mypy
across **105 night-shift source files** pass. These are baseline checks ONLY;
they do not include the new source/tests and are not native evidence.

The applied tests compile all eight actual codec/boundary/process/composition
sources together, reusing inert fake file/process backends under one synthetic
clock. An independent host Python codec supplies the canonical worker bytes in
the held fake file. Cases cover request/metadata refusal, claim ordering,
held-byte/context isolation, both launch gates, deadline consumption, poisoned
pre-create release, post-create retention, concurrent one-shot use, checked
process/import closes and fixed-claim refusal on a new owner.

Compilation, fake job counts and model closure cannot establish native locking,
atomic assignment, durability, guardian-death cleanup or actual process absence.
No test invokes the existing process adapter's P/Invoke methods or a carried
interpreter. The ordinary compiler/model host is not a protected worker.

### Applied verification record

The initial applied selection compiled successfully but had **64 passing tests
and 18 failures**. The reused fake file backend appended closes to its local
log without forwarding its hook. The composition's merged trace therefore
missed those closes, breaking close-order assertions and preventing late-close
fault injections from firing. A test-only repair forwards that SAME close event
through the extracted disposable fake's existing event method, after disarming
the fake handle. An added guard checks that forwarding and that the original
shared fixture remains unchanged. No production C# source or native adapter
repair was needed; no assertion or fault case was removed.

Fresh verification after application of the test-only repair:

- New applied module: **83 passed in 1.28 seconds**, warnings as errors, no skips
  or exclusions: **78 CLR scenarios and five source/instrumentation guards**.
  These execute the applied test file and unchanged applied C# sources, not an
  in-memory replacement. All eight actual sources compile in the same assembly
  with synthetic file/process/time observations and independent Python-derived
  held worker bytes.
- Complete **thirty-six-module** related selection: **2,661 passed, two skipped
  in 19.15 seconds**, warnings as errors, no exclusions. This includes every
  `test_bootstrap*.py` and `test_native_validator_*.py` module, plus
  `test_public_bootstrap_kvp.py`, `test_maintenance_credentials_prototype.py`,
  `test_protocol_bootstrap_main.py`, `test_protocol_test_bootstrap.py`,
  `test_linux_payload_newlines.py`, `test_maintenance_store_native_prototype.py`
  and `test_native_metadata_comparison.py`. Counts overlap and must not be added.
  This is not a full-repository runtime test run; the two existing fixture skips
  are not native success.
- Repository Ruff and Windows-hosted Mypy across **105 night-shift source files**
  pass. Scoped Linux-targeted Mypy passes for provisioning, deployment and the
  host request reviewer with `--follow-imports silent`; this is not a clean
  complete Linux import-graph claim.
- The changed Python test file passes warning-as-error in-memory compilation
  and Python **3.12** grammar parsing. All **six checkpoint files** pass UTF-8
  and trailing-whitespace checks; newline conventions are preserved, including
  the pre-existing missing final newline in `.gitignore`. All **13 local
  document links** resolve. Tracked `git diff --check` passes.
- Related catalog/dependency/codec/payload regressions pass. Catalog names/counts,
  carried Python source, native adapters, fixed outer worker command/environment,
  tool and PowerShell wiring, and existing protected installations/policies/
  claims remain unchanged. The six intended checkpoint files are the complete
  `git status --short` scope. No runtime/bundle/code pins were materialized.

This record update is documentation-only. The results verify compiled library
composition and modeled lifetime ownership, not a native Python adapter,
protected delivery, actual child absence, installed execution or provisioning.

## Remaining worker milestone and non-actions

The [fixed Python adapter/entry candidate](night_shift_native_worker_windows.md)
is applied and verified offline. It supplies the fixed interpreter/source/argument
path, restricted environment/CWD/import paths, single-process inner atomic job
and a conservative common-QPC bridge to Python's local monotonic domain. This is
compiled source plus modeled behavior, NOT native launch/clock/CRT/loader/job
characterization. It does NOT supply the protected starter or parent
authentication: fixed fields/hashes are consistency data, never authorization.
The worker lifetime body still has no live default or executable constructor.
Next are the protected build/install/starter, executable entry points, original
request/approval/deadline delivery INTO the worker, protected receipts and
independent reconciliation, followed by separately approved native experiments.
No numeric process-relative C# deadline is simply serialized as a Python
`monotonic()` timestamp.

The existing Python handoff/provisioner is not invoked by this candidate. No
end-to-end provisioning or installed-worker success is claimed. Trusted protected
build/install/starter, permanent approval including early cancellation,
watchdog/load coverage, protected receipts and independent reconciliation remain
required before any separately approved native attempt. A later VM runner still
requires its own VM-lifetime watchdog and exact VM/disk absence evidence.

No actual request/runtime/bundle/ISO or executable was materialized. No elevation,
protected claim, installation, native import acquisition, guardian/worker/Python
launch, provisioning, VM operation or commit occurred. **Gate A remains unrun.**
