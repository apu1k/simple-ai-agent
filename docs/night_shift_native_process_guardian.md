# Provisioning-process guardian body — unwired candidate

## Status and scope

**Applied and verified offline; not installed or exercised with native process
operations.** All **83 new tests** pass, including compilation of both actual
C# sources. The fresh twenty-nine-file related selection passes **1,906 with
two skips**, warnings as errors. This is the next Windows-specific source slice
after the
[pre-import acquisition/claim body](night_shift_native_install_boundary.md).
It implements exact-owned worker process-tree containment and observation, not
trusted installation, an authenticated approval channel, a tool, an executable
entry point, a Python provisioning handoff or a VM watchdog:

- `scripts/native_validator_process_guardian.cs`: one-shot lifecycle, original
  deadline, worker observation, stop/empty checks and terminal closure.
- `scripts/native_validator_process_guardian_windows.cs`: private unnamed job,
  atomic process assignment, fixed worker launch and native process handles.

**Never compile or load checkout code elevated.** There is no `Main` or installed
executable in this checkpoint. The native adapter refuses a host whose executable
path is not the future fixed `validator-install-guardian.exe` beneath the reviewed
root, and requires native x64 Windows plus the exact enabled administrator SID.
These checks do NOT authenticate that executable, directory or the supplied
plan. A matching filename/hash/object is not approval or provenance.

The committed focused six-file baseline passed **493 tests with one skip**,
warnings as errors, including all 115 acquisition-boundary tests. Repository
Ruff and Mypy across **104 night-shift source files** pass. These are historical
baseline results, not new guardian/native evidence. The skip remains unavailable
unelevated symlink creation. Existing native primitive tests use disposable
non-secret markers, not this guardian or a protected installation.

## Required trust and independent process placement

The future protected starter must authenticate and permanently consume the actual
installation authorization, establish the guardian's OS/CLR/assembly/DLL provenance
BEFORE loading it, and start it in a process separate from the provisioning
worker. The guardian's reviewed entry point must retain its own freshly verified
private worker/dependency/scratch closure throughout use; it cannot rely on a
parent that might die or release the files. None of that executable/approval/
held-target installation plumbing is supplied here.

Only THEN may this body supervise the fixed sibling
`validator-provision-worker.exe --provision-once`. The worker executable/entry
point is also not supplied here. It must perform the earlier pre-import
acquisition/claim work, then invoke the fixed verified Python provisioning body
inside the supervised tree. The two-process active limit permits that worker
and its one Python child; it does not authorize arbitrary child programs.

The guardian sources intentionally do not reference or load the earlier
acquisition assembly, carried Python, codec, deployment reviewer or provisioning
body. Protection can therefore precede THEIR assembly/import/byte-validation work.
The guardian's own executable/CLR closure still needs independently established
trust; this cannot be established retroactively by its worker.

There is no CLI, caller-provided command/arguments, shell, `RunAs`, deployment,
policy activation, claim reset or production/tool wiring. The root/IDs/approval
fields are forgeable consistency data requiring the future protected approval
channel. A fresh object/process is NOT authorization to retry an attempt.

## Atomic containment, not create-then-assign

The native adapter creates one new private, **unnamed and non-inheritable job**
with an explicit protected BA/SYSTEM-only generic-all descriptor. It sets and
reads back exactly:

- `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`;
- `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`, with a limit of **two**;
- no breakaway or silent-breakaway permission.

The root process is created with `STARTUPINFOEX` and exactly one
**`PROC_THREAD_ATTRIBUTE_JOB_LIST`**, containing that job. It is created suspended,
with an explicit BA/SYSTEM-only process/thread descriptor and handle inheritance
**disabled**. Job assignment is part of creation, before any worker instruction;
there is no unassigned suspended-process window between separate create/assign
calls. Unsupported attribute/job nesting, access errors and creation failures
refuse. There is deliberately no legacy `AssignProcessToJobObject` fallback,
breakaway flag, retry or alternate executable.

While the root is still suspended, require exact-job membership and an active
count of one. Resume the owned primary-thread handle exactly once, requiring the
previous suspend count to be one. A missing/aliased handle, unexpected membership,
count or resume result is terminal. Resource slots are adopted before rejecting
malformed child pairs, and disarmed before each single close attempt.

The non-inherited job handle remains owned by the guardian. If that process dies,
Windows kill-on-last-job-handle-close is intended to terminate the contained tree,
including when the guardian dies during the native creation call. This is a
Windows mechanism to be verified natively, NOT a crash-cleanup result from these
sources/models. No protected receipt or independent absence observation currently
exists for this operation.

## Fixed launch context and remaining held-file prerequisite

The executable is always the fixed sibling worker and the arguments are always
`--provision-once`; installation IDs or request data never become command text.
The working directory is the reviewed private guardian root. The complete Unicode
environment block contains only `PATH`, `SystemRoot`, `WINDIR`, `TEMP` and `TMP`.
Windows/system paths come from Windows APIs, not inherited environment variables;
`PATH` is the system directory and TEMP/TMP point to the fixed private `scratch`
child. The future protected starter/guardian must provision, verify and hold that
scratch directory. This body does not create it or broaden the 87-file import
anchor's inventory.

No parent provider keys, Python hooks, search-path overrides or arbitrary inherited
handles are passed. No stdout/stderr pipe is created or drained by this body;
there is no guest/worker-output parser or unbounded log capture. Protected evidence
production, including independently retained identity/handle facts for uncertain
termination, remains a separate prerequisite. The root PID is local observation
only, NEVER a lookup/termination target; all control uses original process/job
handles. Host pipe/console/DLL behavior still needs native review, not assumptions
from source constants.

The separate
[held executable-target acquisition body](night_shift_native_launch_boundary.md)
is now applied and verified offline: **120 new tests** pass, including compilation
of both actual C# sources with a fake file/token/clock backend. The fresh thirty-file
related selection passes **2,026 with two skips**, warnings as errors. No source
or test repair was needed. Repository Ruff and Mypy across **104 source files**,
Python compatibility/grammar, catalog/dependency/pin/payload checks, links and
whitespace pass; the new document records the scoped Linux-targeted typing result
and the unchanged Windows-specific import-graph limitations.

It checks the fixed four-file executable/config inventory and initially empty
private scratch directory, retaining read-sharing-only file handles. It remains
unwired and unexercised natively, not an authenticated approval channel, protected
starter or runnable integration. That acquisition checkpoint left the guardian's
sources and native behavior unchanged. A failed reverification poisons the lease
without releasing its locks.

The subsequent [held-target / guardian composition candidate](night_shift_native_held_guardian.md)
is now applied and verified offline: **76 new tests** pass, including compilation
of all five actual C# sources together with fake backends. It supplies one derived
process plan, a shared construction-time absolute window, same-handle gates before
atomic creation and primary-thread resume, and conservative target-lock retention
after post-creation failure. Its narrow internal core hooks and terminal local
lease-release facts do not change the native process adapter, fixed command or
environment, or atomic job mechanism. No source or test repair was needed.

The fresh thirty-one-file related selection passes **2,102 with two skips**,
warnings as errors. Repository Ruff and Windows-hosted Mypy across **104 source
files**, scoped Linux typing, grammar, catalog/dependency/pin/payload checks,
links and whitespace pass. The composition document records exact scope and
limitations; the historical 83-test record below concerns the earlier guardian
checkpoint. Neither supplies protected approval, executable entry points,
worker/Python delivery or independent protected absence evidence. The new models
substitute file/job/process/time operations; compilation and modeled cleanup are
not native launch, atomic assignment, kill-on-close or guardian-death evidence.

A root/filename/SID check is not a held-file verifier. Before any native call,
the future trusted caller must have established and retained the complete private
launch closure and its exact approved identities/bytes/DLL/import policy. The
native adapter deliberately has no way to infer that authority from a new
self-hash, incoming manifest or the earlier local provisioning record.

## One original deadline and terminal outcomes

The plan allows **6–900 seconds**, capped by the original approval expiry, which
must initially be within 24 hours. Five seconds are reserved WITHIN that budget
for stop/observation; the worker receives at most the remainder, not 900 seconds
plus a cleanup extension. Setup consumes the same budget. No worker is resumed
after the run window expires.

The guardian waits on the exact root-process handle in slices of at most 500 ms,
checking the original monotonic/UTC window between waits. Successful progress,
wall-clock rollback, worker events and new process activity do not renew time.
A bounded polling count also refuses a backend that reports timeouts without
monotonic progress. The future worker must receive the remaining shared budget,
not create an independently renewable execution grant.

On timeout, failure or a residual child after root exit, attempt termination of
ONLY the exact-owned job **once**. A failed/uncertain termination is not retried.
Poll job accounting and the original root handle within at most five seconds AND
the remaining original budget. Require **active count zero AND root signaled**
when its handle is available; root exit alone is not whole-tree absence. A valid
exit code of 259 is retained when the process handle has actually signaled, not
mistaken for a still-running process.

Every path attempts all owned closes. Native scratch resources are released
before child-handle transfer; a failure before transfer closes both local handles
while the caller still owns the kill-on-close job. Close/stop/accounting/wait/
deadline uncertainty is terminal and cannot yield a completed local observation.
There is no finalizer, retry, PID/name sweep or broad cleanup.

A returned observation is explicitly
`local_process_observations_only_not_install_acceptance`: root exit (with any
exit code), deadline stop or residual-tree stop, plus checked empty-tree facts
and closes. Even exit code zero is not installation acceptance, provenance,
authenticated approval, protected evidence or Gate A. Timeout/unknown cannot
release a permanent claim or authorize another attempt. Future integration must
retain independent exact-owned reconciliation evidence/handles and the protected
input locks when termination is unknown; this body supplies no reconciliation
operation or permission to close an import lease and continue.

The guardian is intended to be independent of a worker stalled in hashing/I/O.
It is not a mathematical hard bound on blocked Windows/CLR/kernel operations,
system suspension or a compromised privileged host. Native platform behavior and
watchdog-process failure need separately approved evidence. It cannot contain
external services, scheduled tasks or VMs created through another host service.
A later VM operation STILL needs its independent **VM-lifetime** watchdog and
confirmed exact-VM absence; neither follows from this process job.

## Applied offline verification and next boundary

The new tests compile both actual guardian C# sources with a same-assembly fake
kernel/token/clock backend. All new process/job/native operations are substituted;
the native adapter's P/Invoke methods are never invoked. CLR layout, SDDL parsing,
fixed environment/command construction and source-constant/dependency guards are
ordinary offline observations, not actual kernel containment. Non-Windows CLR
models skip explicitly, not report native success. Temporary compiler/model files
are ordinary non-secret data, never an installed guardian or worker executable.

### Applied verification record

- New applied selection: **83 passed in 0.68 seconds**, warnings as errors,
  no skips or exclusions: **79 CLR models and four source checks**. Both actual
  guardian C# files compile with the same-assembly fake kernel/token/clock
  backend. Ordinary temporary compiler/model processes and files are not a
  protected build, installation or native guardian attempt.
- Fresh twenty-nine-file related selection: **1,906 passed, two skipped in
  10.87 seconds**, warnings as errors, no exclusions. Counts overlap and must
  not be added. This is not a full-repository runtime test run. The selection is
  every `test_bootstrap*.py` module plus `test_public_bootstrap_kvp.py`,
  `test_maintenance_credentials_prototype.py`, `test_protocol_bootstrap_main.py`,
  `test_protocol_test_bootstrap.py`, `test_linux_payload_newlines.py`,
  `test_maintenance_store_native_prototype.py`, `test_native_metadata_comparison.py`,
  `test_native_validator_install_boundary.py` and
  `test_native_validator_process_guardian.py`.
- The two skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation, not native successes. Existing primitive tests
  use ordinary non-secret disposable markers, not this guardian, a protected
  anchor or an installed worker. Ordinary source snapshot regressions do not
  authenticate or provision the actual deployment inputs.
- All new job/process/token/time observations are substituted. The native
  adapter's P/Invoke methods are never called. The genuine CLR observations are
  compilation, struct layouts, SDDL parsing and fixed environment/command
  construction; source guards check constants, role separation, scratch/handle
  transfer order, tracking exceptions and absence of tool/launcher wiring.
  Neither those guards nor fake job accounting establish native atomic
  assignment, last-handle-close behavior, empty-tree evidence or a live timeout.
- Repository Ruff and Windows-hosted Mypy across **104 night-shift source files**
  pass. Linux-targeted Mypy of the unchanged deployment/provisioning components
  passes; this is Python compatibility evidence, not Linux guardian validation.
- The new test passes warning-as-error in-memory compilation and Python 3.12
  grammar parsing. Both C# sources, the test and both checkpoint documents pass
  UTF-8, final-newline and trailing-whitespace checks; **four local document
  links** resolve. Tracked `git diff --check` passes.
- Exactly two additional `.gitignore` exceptions expose the new C# paths, without
  widening `/scripts/*` otherwise; its existing no-final-newline convention is
  preserved. All **six checkpoint files** are visible in `git status --short`.
  Prior acquisition sources/guards and all production/runtime/protected-helper
  implementations remain unchanged.
- Existing catalog/dependency/pin/payload regressions pass. The **91-entry Python
  deployment bundle** and **87-file pre-import inventory** are unchanged. No
  guardian source is inserted into a Python, guest or protected deployment.

No source or test repair was needed after application. The validation-record
follow-up is documentation-only. These checks do not establish actual native
ABI calls, job/process ACLs, protected-file binding, guardian death behavior,
Windows containment, independently confirmed cleanup, installation acceptance
or any VM-lifetime limit.

The next work is the protected executable/approval/held-target boundary and fixed
worker/Python handoff, then separately reviewed installation and native watchdog/
provisioning experiments. There is no extension to the 91-entry Python deployment
bundle, 87-file import inventory, guest source, existing protected helper, claim
or tool contract.

No guardian/worker executable, protected anchor/claim, actual deployment bundle
or ISO was installed, created or copied. No elevation, carried-runtime/worker
execution, VM operation, deployment activation or commit occurred.
**Gate A remains unrun.**
