# Request / original-window / held-guardian composition — unwired candidate

## Status and scope

**Applied and verified offline; not installed or exercised natively.** All
**59 new tests** pass, including compilation of nine actual C# sources together.
The fresh thirty-three-file related selection passes **2,327 with two skips**,
warnings as errors. This is the same-process composition between the
[fixed installation-request codec](night_shift_native_install_request.md)
and [held-target/process guardian](night_shift_native_held_guardian.md). It closes
a specific library integration gap: decoding a request and then constructing a
guardian must not start a fresh execution budget after parsing has consumed time.

- `scripts/native_validator_request_guardian.cs`: captures one local window before
  request reception/decoding, binds the actual canonical request bytes, checks time
  metadata equality and invokes the existing held guardian under that earlier cap.
- `scripts/native_validator_held_guardian.cs`: one internal optional absolute cap
  on the **same clock origin**, shortening rather than extending its earlier
  construction-time window. Existing public APIs and both native adapters remain
  unchanged. The cap does not become a public timestamp authorization interface.
- `tests/night_shifts/test_native_validator_request_guardian.py`: real CLR codec
  plus fake file/process/time composition models, compiling nine actual C# sources
  together, with source/dependency guards. Compilation and model execution remain
  ordinary unelevated test operations, not a protected build.

This remains the narrow C# Windows boundary and Python provisioning split. No
Rust, new runtime package, application DLL or language migration is introduced.
**Never compile or load checkout code elevated.** This source must ultimately be
compiled into the one independently protected application assembly, not loaded
as an incoming bridge DLL or dynamically compiled by the protected operation.

## Independent pins and one-shot admission

The public constructor takes only the independently supplied whole-request length,
SHA-256, budget and expiry metadata. It does not receive paths, a launch plan,
commands, callbacks or raw request bytes. Those values are forgeable consistency
data, **not approval**. The future trusted caller must authenticate and permanently
consume the whole-attempt authorization, including early failure/cancellation,
before using this body. A new object or successful hash cannot grant another try.

Construction validates the bounded inputs and starts a monotonic window capped
by the earlier of the 6–900 second budget and approval expiry. No token/file/job/
process operation is performed by construction. Request reception/waiting after
construction therefore consumes this window. If a future transport receives or
parses data before construction, this body cannot account for that earlier time;
that is not the required protected integration.

`Run(byte[])` disarms its local one-shot before any parsing, file or process work:

1. Require time remaining before the original five-second cleanup reserve.
2. Invoke the actual codec's bounded clone, independent whole-request length/hash,
   fixed-schema and complete canonical-byte checks. No parser runs before its
   existing pin check; incoming mutable plans are not accepted instead of bytes.
3. Check the original run window again after decoding. This is a cooperative
   pre/post check, not an interrupt for a blocked parser or framework load.
4. Derive the immutable launch plan only from that decoded request. Its budget
   and expiry must exactly match the independently captured metadata. Even a
   different well-formed request cannot silently substitute another window.
   The request hash binds the remaining reviewed fields, identities and inventories.
5. Construct the held guardian with both the **same clock origin** and earlier
   absolute deadline. Recheck time before target acquisition. The prior acquisition,
   pre-create/pre-resume gates, job execution, stop/absence observations and checked
   closure all remain capped inside this window.
6. Check the total original window again before returning the unchanged
   `local_process_observations_only_not_install_acceptance` result.

The cleanup reserve remains **inside** the budget, not an additional grant. Delay
before `Run()`, decode time and target acquisition are not followed by renewed
full budgets. UTC rollback cannot enlarge the already computed monotonic cap;
observed monotonic rollback/nonfinite values refuse. Expiry continues to cap
operations. A cap can shorten the existing held guardian but cannot extend it.
Near expiry, the older component constructors can conservatively refuse before
any target acquisition; this is not a new minimum-duration entitlement.

No request or timestamp is serialized, transmitted, authenticated, persisted or
turned into a worker command by this composition. It does not write the derived
worker projection, read the import closure or invoke the provisioner. The fixed
worker command/environment and native atomic job API are unchanged. This slice
must not be described as delivering the original deadline across processes.

## Failures and lock ownership

Every `Run()` result or failure is terminal for this object, including null,
malformed, mistimed or differently pinned request inputs. Concurrent calls are
serialized; at most one can enter the attempt. Retry returns a fixed one-shot
refusal before clock, codec or backend work. These local properties are not a
permanent whole-attempt claim.

The outer object retains its inner guardian after failure. It does not dispose,
unlock, clear, transfer or retry its held-target lease. Pre-create refusals and
checked successful closure retain the earlier release rules; uncertainty after
creation keeps the locks conservatively owned. `LaunchLeaseRetained` exposes only
that local ownership fact. False is **not** a cleanup receipt or proof of absence;
true does not preserve locks after host process death. There is no finalizer,
public reset/dispose/unlock path or exception-text forwarding. Externally returned
failure labels are fixed, not paths, request data or backend exception details.

Independent process-death supervision, protected outcome records and exact-owned
reconciliation are still mandatory. Cooperative deadline checks do not bound
blocked CLR/kernel calls, system suspension or a compromised privileged host.
The body cannot retroactively protect its own assembly/framework loading.

## Applied verification and committed baseline

The **pre-application committed baseline** passed **938 tests
with one skip**, warnings as errors, across ten files: installation boundary,
process guardian, held-target boundary, held guardian, installation request,
deployment, provisioning, media store, native primitives and native metadata.
Repository Ruff and Windows-hosted Mypy across **105 night-shift source files**
pass. The skip is an existing ordinary primitive fixture, not native success.
The earlier request/held-guardian pair also passed **242 tests** in a separate
baseline run. These counts overlap and must not be added.

The applied models compile the actual codec, acquisition bodies/native adapters,
held composition, process guardian and new request composition into one ordinary
CLR model assembly. Only the codec and the fake-backed compositions are invoked;
native adapter P/Invoke and import-closure acquisition are not invoked. Executable
pins, archives, identities, paths and request inputs are synthetic inert DATA.
The two existing backend harnesses are read as literal source via AST extraction,
not imported or executed as sibling test modules.

The passing cases cover independent pin/canonical refusals, time-metadata mismatch,
construction without I/O, arrival/decode/acquisition sharing, original expiry caps,
wall rollback, nonfinite/rollback clock observations, defensive-copy isolation,
minimum/maximum budgets, terminal concurrent calls, internal cap refusals and
shorten-only behavior, normal/nonzero/residual/timeout outcomes, pre-create safe
release and post-create retained-lock uncertainty, target-close faults and late
closure. Synthetic time jumps at the post-decode observation model elapsed decode
time; they do not prove a parser can be interrupted or measure its real duration.
Non-Windows CLR cases skip explicitly; source guards remain portable.

### Applied verification record

No source or test repair was needed after application.

- New applied selection: **59 passed in 1.59 seconds**, warnings as errors, no
  skips or exclusions: **56 CLR composition models and three source checks**.
  All **nine actual C# sources** compile together. The genuine observations are
  compilation, framework codec/hash/canonical-byte behavior and fake-backed
  composition execution, not native file locking, atomic job assignment,
  process-tree cleanup or protected authorization.
- Fresh **thirty-three-file** related selection: **2,327 passed, two skipped in
  20.88 seconds**, warnings as errors, no exclusions. Counts overlap and must
  not be added. This is not a full-repository runtime test run. The selection
  is every `test_bootstrap*.py` module plus `test_public_bootstrap_kvp.py`,
  `test_maintenance_credentials_prototype.py`, `test_protocol_bootstrap_main.py`,
  `test_protocol_test_bootstrap.py`, `test_linux_payload_newlines.py`,
  `test_maintenance_store_native_prototype.py`, `test_native_metadata_comparison.py`,
  `test_native_validator_install_boundary.py`,
  `test_native_validator_process_guardian.py`,
  `test_native_validator_launch_boundary.py`,
  `test_native_validator_held_guardian.py`,
  `test_native_validator_install_request.py` and
  `test_native_validator_request_guardian.py`.
- Existing skipped fixtures are not native successes. No new model invokes
  native adapter P/Invoke, a worker/interpreter/provisioner or import acquisition.
  Existing ordinary primitive fixtures are not protected installation evidence.
- Repository Ruff and Windows-hosted Mypy across **105 night-shift source files**
  pass. Scoped Linux-targeted Mypy passes for the unchanged request reviewer,
  deployment and provisioning modules with `--follow-imports silent`. This is
  not a clean complete Linux import-graph or Linux CLR claim; earlier checkpoints
  retain their documented Windows-specific dependency limitations.
- The new Python test passes warning-as-error in-memory compilation and Python
  **3.12** grammar parsing. All **seven checkpoint files** pass UTF-8 and trailing-
  whitespace checks; non-ignore files have final newlines. All **eight local
  document links** resolve. Tracked `git diff --check` passes.
- The exact `.gitignore` exception exposes the new C# source without widening
  `/scripts/*`; all seven checkpoint files appear in `git status --short`.
  Related catalog/dependency/pin/payload regressions pass: the **91-entry bundle**,
  **87-file import inventory**, guest catalogs and fixed profiles are unchanged.
- Both native adapters, the fixed worker command/environment, request wire
  contract, worker projection, runtime payloads, tools, PowerShell and protected
  installations/policies/claims are unchanged. The existing held composition's
  sole behavior extension is its internal shorten-only original-window cap.

The validation-record follow-up is documentation-only. Passing codec/composition
models on synthetic inputs is not protected request transport, authenticated
permanent authorization, actual original-deadline delivery across processes,
trusted installation, native containment, native provisioning or Gate A.

## Subsequent protected-policy consumption body

The [protected-policy approval/permanent-claim guardian body](night_shift_native_approval_guardian.md)
is now applied and verified offline: **86 new tests** pass, including compilation
of ten actual C# sources together, actual codec/composition logic and complete
claim bytes checked against an independent oracle with fake token/file/process/
time backends. The fresh thirty-four-file related selection passes **2,413 with
two skips**, warnings as errors. Repository Ruff and Windows-hosted Mypy across
**105 source files**, scoped Linux typing, Python grammar, catalog/dependency/
pin/payload regressions, links and whitespace pass. No source or test repair was
needed after application.

It verifies a separately installed private policy through the unchanged native
relative-acquisition adapter, creates/flushes/reads back one fixed claim before
request decoding and holds that policy through this request/target/process chain.
Its earlier same-process clock/deadline is passed through a new internal
shorten-only cap; this body's public API, worker command and native adapters are
unchanged. It retains the approval lease conservatively on any exception after
entering this body's `Run()`, not treating a false launch-retention flag as proof
of child absence. Its claim and returned observations never imply acceptance.

The protected policy's installation/pre-load provenance, authenticated delivery,
permanent early-failure/cancellation handling and cross-process original-deadline
transport still require the future trusted starter/channel. This is not an
installed authorization mechanism. The linked record separates its applied
cap/composition checks from the historical records above. Neither establishes
native policy security, claim durability, containment or protected installation.

## Remaining protected integration and non-actions

Still required before native use:

1. Independently reviewed protected build/install/starter and OS/CLR/self-load/
   framework/DLL search policy, established before executing these bodies.
2. Authenticated, permanently consumed whole-attempt approval; protected delivery
   of the exact reviewed request and the **actual original** deadline across
   starter/guardian/worker boundaries. Do not reconstruct this local object later
   and call its fresh construction time the original approval/start time.
3. Fixed executable entry points, worker request acquisition/import claim and
   verified Python handoff, with independent process watchdog/load supervision,
   protected evidence and uncertain-outcome reconciliation.
4. Separately approved native installation, acquisition, containment and guardian-
   death experiments with independent exact-tree absence/outcome evidence.

This is not a protected starter, transport, authenticated authorization, installer,
worker or native experiment. No CLI, tool/PowerShell wiring, approval consumption,
new protected operation, permission repair, deletion, retry or VM control is added.
The **91-entry deployment bundle**, **87-file import inventory**, guest catalogs,
protected policies/claims and runtime payloads remain unchanged.

After protected provisioning still follow the fixed diskless runner, permanent
execution claim, independent **VM-lifetime watchdog/evidence**, native confinement
validation and trusted image/channel work. A Windows process job does not contain
service-created VMs or establish their final absence.

No actual request, bundle, executable or ISO was materialized. No protected claim,
installation, native guardian/worker execution, elevation, provisioning, carried-
runtime execution, guest execution, VM operation or commit occurred.
**Gate A remains unrun.**
