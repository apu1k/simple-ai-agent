# Python-side provisioning worker handoff — unwired candidate

## Status and scope

**Applied and verified offline; unwired, not installed or exercised natively.**
All **125 new tests** pass. The fresh thirty-five-module related selection passes
**2,538 with two skips**, warnings as errors. This is the bounded Python-side
consumer of the existing canonical worker-request projection. It
lives in `night_shifts/bootstrap_native_provision.py`, an already catalogued
carried member. No new runtime language, catalog filename, third-party dependency,
CLI, executable entry point, process launcher or protected operation is added.

The [outer installation-request contract](night_shift_native_install_request.md)
and its C# codec already derive the exact worker bytes and their import-file pin.
The applied `ProvisionWorkerHandoff` consumes those bytes AFTER trusted import
acquisition and hands their fixed provisioning fields to the existing
[create-new provisioner](night_shift_native_provisioning_body.md). It does not
complete the C# worker, transport, original-deadline delivery or installed route.
**Never import or run checkout code elevated.**

## Mandatory preconditions, not supplied here

Before importing this module, the separately trusted installed caller must:

- Establish its own OS/CLR/executable/load closure and authenticate the protected
  whole-attempt approval, including permanent early-failure/cancellation policy.
- Enforce the exact enabled same-account operator and fixed worker host role.
- Acquire, verify and hold the complete fixed Python/stdlib/DLL/code/import
  closure, including `provision-request.json`, and consume the fixed import claim.
  Hold it through actual child lifetime and uncertain-outcome reconciliation.
- Derive the independent worker length/hash from the already bound outer request,
  not from whatever incoming file happens to contain. Independently deliver the
  matching outer request hash, budget and expiry.
- Deliver an already earlier deadline in THIS Python monotonic-clock domain,
  with guardian stop/cleanup time excluded. Supervise interpreter load and all
  blocking work with the independent protected process guardian/watchdog.

Python objects and matching hashes are forgeable consistency data, not authority.
This body cannot authenticate the transport or establish its own pre-import trust.
It does not take a policy-shaped object or installation record as approval.
The [C# import-lease update](night_shift_native_install_boundary.md) is now
applied and verified offline: **155 boundary tests**, including **40 added tests**,
and the fresh thirty-five-module related selection of **2,578 with two skips**
pass, warnings as errors. Both actual C# sources compile with fake token/file/time
observations. It adds fixed held-reader worker-byte copying, an internal
shorten-only deadline cap and poisoned lock retention instead of automatic release
on verification failure. No source or test repair was needed after application.
That update is a primitive, NOT a worker lifetime owner: explicit disposal still
requires independently established child absence. Native locking, delivery and
process-absence behavior remain unverified. Actual lifetime-safe launch/
reconciliation integration remains required; this Python body does not fix or
replace that ownership boundary.

## Fixed data and execution sequence

The constructor accepts only independent worker length/hash, outer request hash,
budget, expiry and an explicit earlier local deadline. Worker bytes are 1–8,192,
budget is 6–900 seconds, digests are lowercase SHA-256 and expiry is bounded. It
reads clocks but performs no token, file, claim, native or process operation. The
caller must construct it before request reception; no default/fresh deadline is
available. The constructor can only shorten the supplied deadline using the
budget and then-current time to expiry.

`run(raw)` is serialized and terminal, including null, mutable or malformed input:

1. Disarm the one-shot BEFORE checking clocks, hashing, parsing or provisioning.
2. Require the original local window. Refuse observed nonfinite time, monotonic
   rollback or UTC expiry. A wall-clock rollback cannot renew the monotonic cap.
3. Require immutable `bytes` of exactly the independently bounded length, then
   hash them against the independent worker pin BEFORE any JSON parser.
4. Decode ASCII JSON with duplicate-key refusal. Require exact nested schemas,
   operation/scope/version, canonical SID/installation ID/digests/numbers and
   exact equality to the independent outer hash, budget and expiry. Re-encode
   the entire projection and require the original canonical bytes, including
   the single final newline. No ignored fields, coercion or executable strings.
5. Validate fixed local paths, output-name bound, all five distinct directory
   identities, same-volume launch/scratch identity and lexical path separation.
   These are pure shape checks, NOT observations of actual objects or aliases.
6. Project the source/output paths, source/output identities, bundle pin and all
   six deployment pins into the existing immutable provisioning plan. Recheck
   the window, construct only the fixed `NativeValidationProvisioner`, recheck
   again and invoke it once with the SAME shortened earlier deadline.
7. Require an in-window return of the existing local result for this installation
   ID. Return it unchanged, never acceptance, authorization or an installed grant.

The launch/import references are validated for consistency and separation; this
body does not acquire them. Full import-inventory/code-tree correspondence remains
in the earlier bound outer codec and held pre-import acquisition, not a new
self-verification performed after Python loads. The projection contains no
caller-selected filename, command, script, module, callback or generic writer.

The exact **91-entry deployment bundle** and **87-file import inventory** keep
their names/counts. The existing provisioning source bytes change, so actual code
and bundle pins MUST receive fresh independent review. Unchanged catalogs are NOT
unchanged source hashes. Host reviewer code is not imported into the carried set.
The only new imports are Python standard-library facilities.

## Failures, time and resource limits

Every `run` attempt is terminal. A second/concurrent call refuses before clocks
or provisioning, but a new object is not permanent authorization to retry. No
claim is created/reset/deleted here, and no alternative root is selected.

Pre-entry validation/window refusal cannot create provisioning output. Once the
provisioner call is entered, a refusal or late return is conservatively UNKNOWN:
partial output or even a final consistency record may remain. Unexpected ordinary
exceptions receive fixed labels, without paths, payload or native exception text.
The existing provisioner still owns and closes its own native resources. This
handoff neither closes the caller's import lease nor certifies process absence.
Cancellation/BaseException propagation does not rearm the object or grant retry.

Window checks surround reception/decoding/construction/provisioning/return. The
existing provisioner's cooperative monotonic checks cover its file work using
that same supplied deadline. This does NOT make blocking parsing/kernel/I/O
interruptible or add live UTC checks inside every provisioning I/O. UTC expiry
is checked again on return. Import/load time before construction and cross-process
clock-domain delivery still require the protected caller and independent watchdog.
This is not a hard process-lifetime bound or a VM-lifetime watchdog.

## Baseline and applied verification

Fresh committed baseline before drafting:

- **563 passed, one skipped in 7.97 seconds**, warnings as errors, across
  provisioning, deployment, request codec, approval guardian, media store and
  native primitive tests. The existing skipped fixture is not native success.
- Ruff passes for `night_shifts` and `tests/night_shifts`.
- Windows-hosted Mypy passes across **105 night-shift source files**.

These are historical pre-application baseline results, not native evidence or
validation of the new handoff. Fresh applied results are recorded below.

The applied tests use the actual host-derived canonical worker projection,
fixed fake-clock/provisioner probes, malformed independently pinned synthetic
inputs and one composition through the actual provisioner with the existing
inert archive and fake Windows backend. They cover pin-before-parser ordering,
all provisioning-field mapping, strict schemas/canonical bytes, one-shot/concurrent
calls, no budget renewal, shortening/expiry/rollback, post-entry uncertainty and
checked native-model closure. They invoke no carried interpreter or native
provisioning operation. Cross-language projection equivalence remains covered by
the existing CLR codec tests; no C# source or native adapter is changed here.

The existing provisioner isolation regression gains exactly one permitted internal
`.run` edge: the local `body` constructed by `NativeValidationProvisioner` with
`deadline=self._deadline`, called without arguments in this handoff. All other
process/marker/repair/deletion prohibitions and the no-application-importer guard
remain in place. No broad importer or arbitrary callback exception is added.

### Applied verification record

This record describes the original Python-only handoff checkpoint, not the later
C# import-lease changes linked above. Their separate applied validation record
and remaining limits are in that component's document. No Python source, request
schema or catalog changes are made by the C# update.

The initial applied handoff selection passed **123 tests** and its wider selection
passed **2,536 with two skips**. An additional constructor boundary check then
found that an integer deadline outside float-conversion range leaked a raw
`OverflowError`. The applied narrow repair converts that case to the fixed
`ProvisionRefused('worker_window')` label before any clock or provisioning call.
Two regressions cover positive and negative oversized integers and require no
chained exception or clock/provisioner entry. Valid-deadline behavior, request
wire bytes, native adapters and catalog names/counts are unchanged by the repair.

Fresh verification after application of both repairs:

- New handoff module: **125 passed in 1.55 seconds**, warnings as errors, no skips
  or exclusions. These execute the applied Python sources, not an in-memory
  replacement. The exact host-derived projection maps every provisioning field;
  the actual provisioner composition uses an inert archive and fake Windows API.
- Fresh **thirty-five-module** related selection: **2,538 passed, two skipped in
  18.19 seconds**, warnings as errors, no exclusions. Counts overlap and must not
  be added. This is not a full-repository runtime test run. The selection is all
  `test_bootstrap*.py` modules plus `test_public_bootstrap_kvp.py`,
  `test_maintenance_credentials_prototype.py`, `test_protocol_bootstrap_main.py`,
  `test_protocol_test_bootstrap.py`, `test_linux_payload_newlines.py`,
  `test_maintenance_store_native_prototype.py`, `test_native_metadata_comparison.py`
  and the seven `test_native_validator_*` modules: installation boundary, process
  guardian, launch boundary, held guardian, installation request, request guardian
  and approval guardian.
- Existing skipped fixtures are not native successes. Existing ordinary native
  primitive fixtures are not a protected installation or approval anchor. None
  of the new models invokes native provisioning, carried-runtime execution,
  installed guardian/worker execution, protected claims or any VM operation.
- Repository Ruff and Windows-hosted Mypy across **105 night-shift source files**
  pass. Scoped Linux-targeted Mypy passes for provisioning, deployment and the
  host request reviewer with `--follow-imports silent`; this is not a clean
  complete Linux import-graph claim.
- All three changed/new Python files pass warning-as-error in-memory compilation
  and Python **3.12** grammar parsing. All **six checkpoint files** pass UTF-8,
  final-newline and trailing-whitespace checks. All **eight local document
  links** resolve. Tracked `git diff --check` passes.
- Related catalog/dependency/codec/payload regressions pass, including the
  **91-entry bundle**, **87-file import inventory** and narrow internal call-edge
  guard. No application importer or CLI is added. The provisioning source bytes
  do change and still require fresh independent code/bundle pins before use.
- All C# sources/native adapters, host request reviewer, `.gitignore`, tool and
  PowerShell wiring, fixed worker command/environment, request format, catalog
  filenames and existing protected installations/policies/claims are unchanged.
  All six intended checkpoint files appear in `git status --short`.

The validation-record follow-up is documentation-only. These checks do not supply
pre-import provenance, protected request/deadline delivery, permanent approval,
native locking/containment/durability, installed execution or protected evidence.
No further source or test repair was needed after the integer-deadline fix.

## Remaining integration and non-actions

The [worker lifetime composition candidate](night_shift_native_worker_guardian.md)
is now applied and verified OFFLINE, NOT installed or exercised natively. All
**83 new tests** pass, including **78 CLR scenarios** and compilation of all eight
actual C# sources together. The fresh thirty-six-module related selection passes
**2,661 with two skips**, warnings as errors. The sole repair was test-only
close-event forwarding in the extracted disposable fake, with a regression guard;
production sources, native adapters and the original shared fixture are unchanged.
It composes the actual outer codec, import claim/lease, fixed held-reader copy and
process-guardian core under one mandatory earlier same-origin deadline. It releases
import locks only on the core's terminal release fact and conservatively retains
them after post-create failure. A distinct internal Python-kernel seam has NO
production implementation or fallback to the guardian's C# worker launcher. This
is the first worker-owner composition slice, not completed fixed Python launch
or an invocation of this Python handoff/provisioner. Native transport, clock-domain
delivery and executable entry integration remain required; see that candidate's
separate applied verification record and explicit limits.

Still required: trusted protected build/install/starter; protected policy/request
provisioning and permanent approval delivery including early cancellation; actual
cross-process deadline transport; executable entry points; lifetime-safe held
import acquisition and fixed Python launch; protected receipts/reconciliation;
and separately approved native experiments. This checkpoint supplies only the
Python-side data-to-provisioner edge, not that protected execution path.

No real request, bundle, runtime or ISO was materialized. No elevation, protected
claim, installation, carried-runtime execution, provisioning, native process
launch, VM operation or commit occurred. **Gate A remains unrun.**
