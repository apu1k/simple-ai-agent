# Protected-policy approval / permanent-claim guardian body — unwired candidate

## Status and purpose

**Applied and verified offline; not installed or exercised natively.** All
**86 new tests** pass, including compilation of ten actual C# sources together.
The fresh thirty-four-file related selection passes **2,413 with two skips**,
warnings as errors. This adds a protected-policy consumption body before the
[request/original-window guardian](night_shift_native_request_guardian.md).
It is not an installed approval channel, trusted starter, installer, executable
entry point or tool operation. **Never compile or load checkout code elevated.**

- `scripts/native_validator_approval_guardian.cs`: verifies a separately installed
  private approval policy through held handles, creates one fixed permanent
  claim before request decoding, and retains the policy through the request/
  target/process guardian under the same earlier local deadline.
- `scripts/native_validator_request_guardian.cs`: internal shorten-only cap from
  this earlier same-process window. The public API and fixed launch are unchanged.
- `scripts/native_validator_install_request.cs`: pure internal isolation check
  against the decoded launch/import/source/output-parent paths and identities.
  The request wire bytes, canonical codec, worker projection and catalogs do not
  change. This check performs no host observation or authorization itself.
- `tests/night_shifts/test_native_validator_approval_guardian.py`: ten actual C#
  sources compiled together with fake file/token/job/time backends, synthetic
  policy/request bytes and an independent claim-byte/plan-digest oracle.

The C#/Python split remains unchanged. No Rust, third-party package, carried
application DLL, new native adapter or platform API is introduced. The existing
relative Windows acquisition/claim adapter is reused without modification.
The future executable must compile these bodies into its one independently
protected application assembly, not dynamically load an incoming bridge.

## Separate approval anchor and conditional authority

The prerequisite is one separately reviewed, privately installed approval anchor
with an independently reviewed canonical path, NTFS volume/index identity and
complete policy length/SHA-256. It must be established by the future protected
build/install/starter route, **before** these bodies execute. It is not the launch
anchor, import anchor, source/output-parent directory or provisioning output:

```text
<separate approval anchor>/
    approval.json
    claims/
        install-attempt.claim    # absent before the one create attempt
```

The exact policy is bounded to 1 KiB and fixed canonical ASCII JSON with one final
newline. Its only keys are `budget_seconds`, `expires_unix`, `operation`,
`operator_sid`, `request_bytes`, `request_sha256`, `scope` and `version`. Scope is
`protected_native_validator_install_approval_once`, operation is
`native_validator_provision_once`, version is 1. Budget is 6–900 seconds and the
request is 1–32,768 bytes. SID numbers are canonical bounded Windows subauthorities.
There is no generic acceptance flag, code path, command, plugin, script, reset,
retry or cleanup permission. The **complete independently reviewed outer request
hash** binds the installation ID, reviewed paths/identities and launch/import/
provisioning pins already defined by the existing request contract.

The body generates these exact expected policy bytes from its validated immutable
references and first requires their length/hash to match the independently supplied
policy pin. It later compares the entire held file and exact EOF to those bytes.
There is no incoming policy JSON parser or normalization path. A freshly computed
hash of unreviewed data is not independent review.

**A plan, policy-shaped byte array or successful hash does not confer authority.**
The authority is conditional on the authentic separately installed protected
policy, exact enabled same-account Administrator token, independently reviewed
anchor identity, strict no-reparse NTFS acquisition/security and trusted pre-load
host. An ordinary-user-writable policy or an assembly loaded from the checkout
cannot satisfy that boundary merely by presenting matching pins. The native
adapter must enforce the earlier strict BA/SYSTEM-only ownership/group/DACL and
ancestor policy; there is no ACL repair or TrustedInstaller exception.
Administrators, SYSTEM, the OS/kernel and reviewed CLR/load closure remain trusted.
This is filesystem-backed conditional authorization, not a cryptographic message
signature or authentication of an untrusted transport.

The approval anchor must be lexically disjoint, case-insensitively and in both
ancestor/descendant directions, from the decoded launch/import/source/output-
parent paths. Its actual reviewed root volume/index must not equal any of the
five request directory identities, including scratch. These additional checks
run **after claim consumption but before target/process operations**. They are
plan-shape checks, not proof of real-path alias absence; later native acquisitions
still have to verify the approved objects. Sharing a prefix without a component
boundary does not itself imply overlap.

## Acquisition, claim and execution ordering

Construction validates the bounded references, creates the expected policy/claim
bytes and captures a monotonic window before any native acquisition. No token,
file, claim or process operation occurs during construction. The expiry must
initially be 6 seconds to 24 hours away. Assembly loading and all work preceding
construction still require the independently supervised protected starter.

`Run(byte[])` is terminal and serialized, including null/malformed request inputs:

1. Disarm the object's one-shot before any token/file/process operation. Require
   the original run window, then the existing native x64 exact enabled operator.
2. Acquire the local NTFS root and each ancestor with relative no-reparse opens,
   unchanged strict security/shape policy and held no-delete directory handles.
   Require the reviewed approval-root identity, same-volume final-name continuity
   and distinct object identities/handles.
3. Require exactly `approval.json` and `claims` in that root. Acquire the policy
   read-only with `FILE_SHARE_READ` only. Verify all its bytes, EOF and stable
   metadata against the independently pinned canonical policy. Acquire the private
   `claims` directory and require it empty. Unauthorized/mismatched policies do
   not authorize creating a claim.
4. Mark creation attempted **before** calling the unchanged adapter's fixed
   `FILE_CREATE` for **`claims/install-attempt.claim`**. The leaf does not vary
   with request ID/digest, installation ID or process/object identity. A collision,
   partial file or existing claim refuses; there is no overwrite or alternative.
5. Write once, check the write, flush and read back through the **same held
   exclusive writer handle**, with exact bytes/EOF and identity/security checks.
   Only expected length and archive-bit changes are allowed for the controlled
   write/directory creation. Reverify the complete held policy/claim inventory.
6. Only now decode the actual outer request with the existing independent
   length/hash and canonical checks. Enforce approval-anchor plan separation.
   Even null, incorrectly pinned or noncanonical requests consume the fixed
   claim once this point is reached.
7. Construct the request guardian with both the same clock origin and this
   earlier absolute deadline. Reverify held policy/claim bytes before entering
   it. The inner body rebinds the **same independently pinned request bytes**;
   caller-array mutation after the outer check cannot substitute another plan.
   It also enforces exact budget/expiry equality with the protected policy.
8. Retain approval handles through target acquisition, both launch gates, worker
   run/stop/absence observations and checked target closure. After a normal inner
   return, reverify the approval inventory/bytes/metadata, attempt each approval
   handle close once in reverse ownership order and check the original window.
   Return only the existing local process observation, never install acceptance.

The claim scope is `approval_attempt_consumed_not_acceptance`. It binds the policy
and request hashes plus a versioned length-prefixed plan digest covering root
path/volume/index, exact SID, independent policy/request lengths/hashes and budget/
expiry. Its bytes are bounded below the existing adapter's 1 KiB write cap.
Successful flush/read-back is not proof against power loss, storage rollback or
privileged host tampering. Native durability remains unverified.

Both the approval and worker import anchors deliberately use the same **fixed
leaf name in different separately reviewed roots**. They are different claims:
this one consumes the protected whole-request policy before parsing; the older
worker claim guards import acquisition later. Neither touches a legacy inspection
installation/claim, and neither authorizes automatic reset/retry or another root.
Changing approved request bytes, a process or a model object cannot bypass a
claim already present in this approved anchor. A different anchor would require
separate review/installation/authorization, not a runtime retry choice.

## Window, failure and lifetime limits

All approval acquisition, hashing/claim I/O, both request decodes, target/process
work and final approval verification/closure consume one local original window.
The five-second cleanup reserve stays **inside** that window. The new internal
request cap can only shorten, never renew or extend, the previous window. UTC
expiry still applies; observed monotonic rollback/nonfinite values refuse.
These are cooperative checks, not interruption of blocked native/CLR operations,
and not protected delivery of an actual original deadline across processes.

All acquired approval handles close once on failures before entering inner
`Run()`. Once that inner invocation is entered, **any exception conservatively
retains the approval lease**, even a known-looking pre-create refusal. Only a
normal inner return is used as the release fact; `LaunchLeaseRetained == false`
is deliberately not used as proof of child absence. Post-return approval or
close faults still prevent a successful observation. There is no public unlock,
dispose/reset path, finalizer, automatic retry, deletion or exception-text leak.

The three public booleans are local facts only:

- `ClaimCreationAttempted`: the native create boundary was entered, not proof
  that creation, write, flush, read-back or permanent durable consumption succeeded.
- `ApprovalLeaseRetained`: this object deliberately still owns approval handles,
  not a cleanup/acceptance result. False is not proof every close succeeded.
- `LaunchLeaseRetained`: the inner guardian's existing local target ownership
  observation, still not proof of absence when false.

A dropped object cannot authorize process exit or reconciliation. OS handles do
not survive host death. Independent guardian-death/load supervision, protected
receipts and exact-owned uncertain-outcome reconciliation remain mandatory.
The returned process observation's `ApprovalSha256` continues to mean the outer
request digest; it is not a policy authenticator, authorization receipt or new
scope. Existing nonzero/timeout/residual-tree outcomes do not become acceptance.

This body cannot consume a claim before it runs. Invalid constructor references,
expired windows, failed token/anchor acquisition, transport cancellation or a
starter failure before claim creation still require the future protected channel's
permanent whole-attempt/cancellation policy. A missing claim after uncertainty
never grants a retry. Do not describe this as a complete authenticated approval
channel or a complete solution to early cancellation.

## Applied verification and committed baseline

The **pre-application committed baseline** passed **997 tests with one skip**,
warnings as errors, across eleven modules: installation boundary, process guardian,
held-target boundary, held guardian, request codec, request guardian, deployment,
provisioning, media store, native primitives and native metadata. Repository Ruff
and Windows-hosted Mypy across **105 night-shift source files** pass. The skip is
an existing ordinary primitive fixture, not native success. These baseline checks
do **not** validate the new sources, cap or codec-isolation addition.

The applied models compile ten actual C# sources together and run the actual
codec/claim/window/composition logic against fake file/token/process/time backends.
An independent Python oracle builds the canonical policy, .NET length-prefixed
plan digest and complete claim bytes. The reused backend harnesses are read as
literal source, without executing their sibling test modules; only the earlier
inert request fixture function is AST-extracted and executed as test setup.
All executable/archive/policy/request inputs and directory identities are inert
synthetic data. Temporary compiler/corpus files are ordinary non-secret fixtures,
not an installation, actual approval input or native claim.

The passing cases cover exact policy pins/bytes, canonical request refusal after
claim consumption, short reads, fixed-name replay/new-object/changed-request
refusals, claim write/flush/read-back and metadata faults, root/path/identity
separation, request mutation between the two pin checks, shared policy/request/
execution time, cleanup lock lifetime, conservative post-entry retention, late/
uncertain closure, normal/nonzero/residual/timeout outcomes and terminal concurrent
calls. New cap cases exercise NaN/infinite/past refusal and shortening/non-extension.
Non-Windows CLR cases skip explicitly; portable source guards remain available.
None of the new models invokes a native adapter P/Invoke or proves native policy
security, share modes, claim durability, atomic job assignment or process absence.

### Applied verification record

No source or test repair was needed after application.

- New applied selection: **86 passed in 1.98 seconds**, warnings as errors,
  no skips or exclusions: **83 CLR models and three source checks**. All **ten
  actual C# sources** compile together. The actual codec, policy/claim byte
  construction, plan digest, original-window logic and composed guardian bodies
  execute against fake token/file/process/time backends. The independent Python
  oracle's complete claim bytes match, including the versioned length-prefixed
  plan digest. These are not native policy/ACL/lock/durability observations.
- Fresh **thirty-four-file** related selection: **2,413 passed, two skipped in
  17.09 seconds**, warnings as errors, no exclusions. Counts overlap and must
  not be added. This is not a full-repository runtime test run. The selection
  is every `test_bootstrap*.py` module plus `test_public_bootstrap_kvp.py`,
  `test_maintenance_credentials_prototype.py`, `test_protocol_bootstrap_main.py`,
  `test_protocol_test_bootstrap.py`, `test_linux_payload_newlines.py`,
  `test_maintenance_store_native_prototype.py`, `test_native_metadata_comparison.py`,
  `test_native_validator_install_boundary.py`,
  `test_native_validator_process_guardian.py`,
  `test_native_validator_launch_boundary.py`,
  `test_native_validator_held_guardian.py`,
  `test_native_validator_install_request.py`,
  `test_native_validator_request_guardian.py` and
  `test_native_validator_approval_guardian.py`.
- Existing skipped fixtures are not native successes. Existing ordinary native
  primitive fixtures are not a protected approval anchor or installation. No
  new model invokes native adapter P/Invoke, an installed guardian/worker, the
  carried interpreter, import acquisition, provisioner or any VM operation.
- Repository Ruff and Windows-hosted Mypy across **105 night-shift source files**
  pass. Scoped Linux-targeted Mypy passes for the unchanged host request reviewer,
  deployment and provisioning modules with `--follow-imports silent`. This is
  not a clean complete Linux import-graph or Linux CLR claim; prior documented
  Windows-specific dependency limitations remain.
- The new Python test passes warning-as-error in-memory compilation and Python
  **3.12** grammar parsing. All **eight checkpoint files** pass UTF-8 and
  trailing-whitespace checks; non-ignore files have final newlines. All **seven
  local document links** resolve. Tracked `git diff --check` passes.
- The one exact `.gitignore` exception exposes the new C# source without widening
  `/scripts/*`; all eight checkpoint files appear in `git status --short`.
  Related catalog/dependency/pin/payload regressions pass: the **91-entry bundle**,
  **87-file import inventory**, guest catalogs and fixed profiles are unchanged.
- All three native adapters, the fixed worker command/environment, request wire
  bytes, public codec factories, worker projection, runtime payloads, tools,
  PowerShell and protected installations/policies/claims are unchanged. Existing
  source behavior additions are limited to the internal request deadline cap
  and pure decoded-plan approval-anchor isolation check.

The validation-record follow-up is documentation-only. These compiled models do
not supply trusted policy installation, authenticated transport, permanent
pre-entry/early-cancellation handling, cross-process original-deadline delivery,
native claim durability, atomic containment, protected evidence or Gate A.

## Remaining integration and non-actions

Still required: independently trusted protected build/install/starter and pre-load
policy; actual protected policy/request provisioning and approval delivery with
permanent early-failure/cancellation handling; actual original-deadline transport;
guardian/worker executable entry points; fixed import-closure claim and verified
Python handoff; independent watchdog/load supervision; protected receipts and
uncertain-outcome reconciliation; separately approved native experiments.

No CLI, tool/PowerShell wiring, native adapter change, elevated checkout compile,
permission repair, installation, claim reset, overwrite, deletion, retry, generic
command or VM operation is added. The **91-entry deployment bundle**, **87-file
import inventory**, guest catalogs, runtime payloads and existing protected
installations/policies/claims remain unchanged. These sources do not activate or
reuse the old inspection installation.

After protected provisioning still follow the fixed diskless runner, permanent
execution claim, independent **VM-lifetime watchdog/evidence**, native confinement
validation and trusted image/channel work. A process job does not contain VMs
created by a host service or prove their final absence.

No actual approval/request/bundle/ISO or protected anchor/claim was created. No
elevation, protected installation, native guardian/worker execution, provisioning,
carried-runtime execution, guest execution, VM operation or commit occurred.
**Gate A remains unrun.**
