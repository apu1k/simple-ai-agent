# Held-target / provisioning-process guardian composition — unwired candidate

## Status and purpose

**Applied and verified offline; not installed or exercised natively.** All
**76 new tests** pass, including compilation of all five actual C# sources
in one model assembly. The fresh thirty-one-file related selection passes
**2,102 with two skips**, warnings as errors. This slice joins the
[held executable-target boundary](night_shift_native_launch_boundary.md) to the
[provisioning-process guardian](night_shift_native_process_guardian.md). They were
previously separate bodies. Keeping them separate at runtime would leave the
caller responsible for plan equality, deadline conservation and lock lifetime.
This composition makes those obligations explicit in one fixed source path.

- `scripts/native_validator_held_guardian.cs`: derives the process plan from the
  launch plan, shares one attempt window, holds the target lease and gates both
  creation and primary-thread resume.
- Narrow additions to the two existing **core** bodies: internal absolute-window
  caps, internal fixed launch gates and a terminal local lease-release fact.
  Their public standalone constructors remain library bodies, not authorization
  APIs; both native adapter sources and their Windows API calls are unchanged.
- `tests/night_shifts/test_native_validator_held_guardian.py`: CLR composition
  models compiling all five actual C# sources, plus source/dependency guards.

This remains C# for the Windows pre-Python trust/process layer, with Python for
provisioning and validation. No Rust, new runtime dependency, application DLL or
language migration is introduced. It is **not** the protected starter,
authenticated approval channel, worker entry point or Python handoff.
**Never compile or load checkout code elevated.**

## A single plan, not two partially matching grants

The public constructor takes exactly one `LaunchPlan`. Its fixed four-file
inventory, root/scratch identities and byte pins retain the earlier boundary's
contract. It derives the guardian's root, SID, installation ID, approval digest,
UTC expiry and budget directly from that plan. There is no second independently
supplied `GuardianPlan`, arbitrary command, callback, executable name or argument
list in this public composition API.

The original immutable copies and validation rules still apply. The plan is
**forgeable consistency data**, not authentication. A new object/process, a fresh
ID or a successful hash does not grant another attempt or consume a permanent
whole-attempt authorization. The earlier worker-side install claim does not
supply that outer approval boundary.

The future guardian executable must compile this composition and both prior
bodies/adapters into its **one independently protected application assembly**.
It must not load an incoming bridge DLL or dynamically compile the checkout.
Its own OS/CLR/assembly/config/DLL load provenance has to be established before
its first instruction/assembly load; checking its on-disk bytes afterward cannot
establish that provenance retroactively. System trust and search/load policy are
still prerequisites outside the four carried-file hashes.

## One original window, including target closure

Construction starts one monotonic clock and computes one absolute deadline from
6–900 seconds and the original approval expiry (initially 6 seconds to 24 hours
away). There are no filesystem, token or process operations in the constructor.
The same clock/window is used by target acquisition, both full reverifications,
process creation, execution, termination/absence observation and handle closure.
Waiting between construction and `Run()` consumes that original budget too.

Five seconds are reserved **inside** the original attempt window for process
stop/observation and final resource closure. The target boundary is capped at the
run-window end, not the later cleanup deadline, so acquisition/hashing cannot
consume that reserve then give the worker a renewed full budget. Internal caps
can only shorten the existing bodies' calculated deadlines, never extend them.
A shortened window with no run time left refuses before creation. Monotonic
rollback/nonfinite observations refuse; wall-clock rollback cannot renew the
monotonic limit. Approval expiry continues to cap the operation.

Target-file closure consumes the same original window. Even after successful
process observation and closure, a late/uncertain target close or final clock
observation cannot return a successful local result. This is a cooperative
budget, **not** a mathematical hard bound on blocked Windows/CLR/kernel calls,
system suspension or a compromised privileged host. Protection of the starter
and guardian before/during their own load and acquisition still needs independent
reviewed supervision/evidence.

## Fixed acquisition-to-resume ordering

1. Disarm this object's one-shot `Run()` before target or process operations.
2. Acquire/hash the exact launch closure and retain all of its handles before
   entering the process guardian. No worker has been created at this point.
3. Require the existing guardian host/token role and create/read back the private
   kill-on-close job. Immediately before entering atomic suspended creation,
   repeat complete inventory/metadata/byte verification through the **same held
   handles**. Check the remaining run window again after that gate.
4. Mark creation attempted **before** entering `CreateSuspended`, including calls
   that later throw or return malformed data. The unchanged adapter uses atomic
   `JOB_LIST` assignment, no create-then-assign fallback and no handle inheritance.
5. After suspended membership/count checks, reverify the same complete closure
   again and recheck time before the exact primary-thread resume. Scratch must
   still be empty: the suspended worker has executed no instructions yet.
6. Retain the closure through run/stop/empty-root-and-job observation and checked
   process/job closure. No path reopen, lease transfer to the worker or parent
   lock-lifetime assumption is introduced.
7. Only then close targets once, in the prior boundary's reverse ownership order,
   and check the original window before returning local process observations.

The process adapter's fixed sibling command, sanitized complete environment,
two-process job limit and exact-handle-only control are unchanged. No arbitrary
launcher, PID/name reconciliation, claim reset, ACL repair, broad deletion or
automatic retry is added.

## Failure, retained locks and local observations

The core guardian exports an **internal terminal local fact**, not a public
cleanup certificate. The composition may release its lease only after:

- refusal/failure **before entering creation**, with checked resource closure
  and no final window uncertainty; or
- a returned process observation after checked root/job absence, process/job
  closure and the original deadline check.

Any guardian failure **after entering creation** deliberately retains the target
lease, even if a stop/empty observation may have succeeded while handling that
failure. This is conservative: exceptions are not used as proof of absence, and
uncertain native creation is not treated as "no child". Failed reverification
poisons the existing lease without unlocking it. The composition does not put it
in `using`/`finally`, expose it publicly or offer `Dispose`, unlock, reset, retry
or finalizer paths. The one-shot remains terminal on all failures.

`LaunchLeaseRetained` is only a terminal local ownership observation. `false`
does **not** certify that every native close succeeded; close failures remain
unknown and are never retried. `true` means the object deliberately still owns
the lease. Dropping the object does not authorize process exit/unlocking,
reconciliation or another attempt. The future protected host must retain
independent exact-owned evidence/reconciliation and handle guardian death;
process death releases Windows file handles, and this managed object cannot
preserve locks after its host dies. There is no installed uncertain-outcome
recovery operation in this checkpoint.

A normal return is still the prior
`local_process_observations_only_not_install_acceptance` result. Zero/nonzero
worker exit, a bounded deadline stop or residual-tree stop never establishes
installation acceptance, provenance, authenticated authorization or Gate A.
All externally returned failure labels are fixed and do not expose backend
exception text or input contents.

## Verification scope

The pre-application **committed baseline** passed **696 tests with one skip**, warnings as
errors, across eight files: installation-boundary, process-guardian,
held-target-boundary, deployment, provisioning, media-store, native-primitive and
native-metadata tests. Repository Ruff and Windows-hosted Mypy across **104
night-shift source files** pass. The skip is unavailable unelevated symlink
creation. Existing primitive regressions use disposable non-secret markers, not
a protected launch anchor, this composition or an installed guardian/worker.
Those are historical baseline results; the applied results are recorded below.

The applied models read the literal existing fake-backend harnesses without
importing/executing their Python modules, replace only their synthetic clocks
with a shared model time, then compile both native adapters, both core bodies
and the composition in one ordinary CLR model assembly. Existing fake file,
token, job/process and time operations remain substituted; the original harness
scenario runners are not called. Source checks inspect gate order, absolute caps,
no public unlock/second-plan path and absence of tool/deployment wiring.

Models cover plan validation/derivation, complete hashing before host/process
operations, same-handle pre-create/pre-resume verification, shared time consumed
at each stage, fixed cleanup reserve, constructor delay, UTC/monotonic behavior,
shorter/non-renewable caps, normal/nonzero/259 exits, stop/absence/close faults,
pre-create safe release, post-create poisoned-lease retention, final target-close
uncertainty and concurrent terminal one-shot behavior. Non-Windows CLR models
skip explicitly. No model invokes native file/job/process P/Invoke, installs
executables or runs carried Python. Synthetic executable bytes remain inert.
Temporary compiler/model artifacts are ordinary non-secret harness data, not a
protected build or native launch experiment.

### Applied verification record

No source or test repair was needed after application.

- New applied selection: **76 passed in 0.91 seconds**, warnings as errors,
  no skips or exclusions: **72 CLR composition models and four source checks**.
  All five actual C# sources compile together with the fake backends. The
  genuine observations are ordinary CLR compilation/reflection and execution
  of model logic, not native acquisition, sharing, atomic assignment, suspended
  execution, kill-on-close behavior or process-tree absence.
- Fresh thirty-one-file related selection: **2,102 passed, two skipped in 13.15
  seconds**, warnings as errors, no exclusions. Counts overlap and must not be
  added. This is not a full-repository runtime test run. The selection is every
  `test_bootstrap*.py` module plus `test_public_bootstrap_kvp.py`,
  `test_maintenance_credentials_prototype.py`, `test_protocol_bootstrap_main.py`,
  `test_protocol_test_bootstrap.py`, `test_linux_payload_newlines.py`,
  `test_maintenance_store_native_prototype.py`, `test_native_metadata_comparison.py`,
  `test_native_validator_install_boundary.py`,
  `test_native_validator_process_guardian.py`,
  `test_native_validator_launch_boundary.py` and
  `test_native_validator_held_guardian.py`.
- Skips are not native successes. Existing primitive regressions use ordinary
  non-secret disposable markers, not this composition or a protected launch
  anchor. All new file/job/process/token/time observations are substituted;
  no native adapter P/Invoke is invoked by the new models.
- Repository Ruff and Windows-hosted Mypy across **104 night-shift source files**
  pass. Scoped Linux-targeted Mypy of the unchanged deployment/provisioning
  modules passes with `--follow-imports silent`. This does not establish a clean
  complete Linux import graph: the earlier held-target checkpoint records the
  existing Windows-specific dependency limitations. No Python application or
  native adapter repair/suppression was introduced.
- The new Python test passes warning-as-error in-memory compilation and Python
  **3.12** grammar parsing. All **eight checkpoint files** pass UTF-8 and
  trailing-whitespace checks; non-ignore files have final newlines. All **seven
  local document links** resolve. Tracked `git diff --check` passes.
- One exact `.gitignore` exception exposes the new C# source without widening
  `/scripts/*`; all eight checkpoint files are visible in `git status --short`.
  Both Windows adapters, earlier import-boundary sources, Python application,
  runtime/tool/PowerShell wiring and protected policies remain unchanged.
- Catalog, dependency, pin and payload regressions pass. The **91-entry deployment
  bundle** and **87-file import inventory** are unchanged. None of the C# sources
  is added to the Python deployment bundle or guest payloads.

The validation-record follow-up is documentation-only. These results verify
compiled library composition and fault models, not a protected executable,
load provenance, durable approval, native locking/containment, guardian-death
cleanup, installation acceptance or a native provisioning attempt.

## Remaining protected integration

Still required, before native use:

1. A separately reviewed protected build/install/starter route establishing its
   own and the guardian's complete pre-load provenance and trusted search policy.
2. The authenticated, permanently consumed whole-attempt approval channel,
   original-deadline handoff and independent protected evidence/reconciliation.
3. Guardian/worker executable entry points, fixed reviewed request delivery and
   worker import-closure acquisition/claim plus the fixed verified Python
   provisioning handoff, all inside the contained tree. None is supplied here.
4. Separately approved native provisioning/containment/guardian-death experiments
   with independent outcome and exact-tree absence evidence.

Then follow the fixed diskless VM runner, permanent execution claim, **independent
VM-lifetime watchdog** and protected VM/evidence integration. Process jobs do not
contain VMs operated by a host service and do not prove exact-VM absence.

This source composition is not called by a tool, launcher, installer or Python.
The 91-entry deployment bundle, 87-file import inventory, guest catalogs,
existing protected policies/claims and carried runtimes are unchanged. No private
anchor, protected claim, deployment bundle, guardian/worker executable or ISO was
created, installed or copied. No elevation, native guardian/worker execution,
provisioning, guest execution, VM operation or commit occurred.
**Gate A remains unrun.**
