# Fixed validator installation-request contract — unwired candidate

## Status and purpose

**Applied and verified offline; not installed or exercised natively.** All
**166 new tests** pass, including compilation of five actual C# sources together
and cross-language request/worker-byte checks. The fresh thirty-two-file related
selection passes **2,268 with two skips**, warnings as errors. This slice supplies
a single bounded input contract for the future protected starter and worker,
following the
[held-target / process-guardian composition](night_shift_native_held_guardian.md).
It does not implement a protected starter, install anything, authenticate approval,
consume an authorization or invoke the guardian/provisioner.

- `night_shifts/bootstrap_native_install_request.py`: stdlib-only, memory-only
  **host reviewer**, canonical request builder, independent-pin checker and
  bounded local review/worker projections. Not a carried Python entry point.
- `scripts/native_validator_install_request.cs`: bounded pin-first JSON decoder,
  fixed-schema/canonical verifier and immutable launch/import-plan factories.
- `tests/night_shifts/test_native_validator_install_request.py`: host fault tests,
  independent projection oracle and CLR cross-language corpus. Five actual C#
  sources compile together; only the new codec/plan factories are invoked.

**Never compile or load checkout code elevated.** OS/CLR/self-load provenance and
authenticated permanent whole-attempt authorization remain external prerequisites.
A fresh hash, correctly shaped request, object or process confers no authority.

## One whole request, no self-hash cycle

The canonical ASCII JSON request is at most **32 KiB**, version 1, with operation
`native_validator_provision_once` and scope
`reviewed_installation_inputs_not_authorization`. It contains exactly:

- installation ID, exact operator SID, budget metadata and expiry metadata;
- launch root path/identity, separate scratch identity and the **four** fixed
  guardian/worker executable/config length/SHA-256 pins;
- import-anchor path/identity and the **86** fixed runtime/code/codec input pins;
- provisioning source and output-parent paths/identities;
- complete bundle length/hash, code/codec descriptor-tree pins, original runtime
  archive length/hash and recovery-ISO length/hash reference.

There is no caller-selected command, executable/import name, script, plugin,
credential, cleanup target, claim reset, acceptance flag or retry permission.
Both catalogs are independently checked against the existing fixed profiles.
Files are exact sorted arrays of `{bytes,name,sha256}` descriptors; missing,
extra, duplicate, case-alias and reordered entries refuse. File size/aggregate
bounds remain explicit. The import descriptors reserve 8 KiB inside the 96 MiB
closure cap for the later worker-request leaf.

**The whole request excludes `provision-request.json` and any hash of itself.**
After independently checking the complete outer bytes, the codec derives the
worker JSON projection, adds the outer request SHA-256 to it, and computes the
projection's own length/hash. The C# import-plan factory adds that derived leaf
as the **87th** pin. Thus the request need not contain a hash which depends on
itself. The projection is never supplied as incoming manifest-selected code.

The worker projection, at most **8 KiB**, has scope
`bound_worker_request_not_authorization`. It repeats context/provisioning fields,
outer request digest and path/identity summaries, but not the 90-file pin lists.
Both plan factories derive their ID/SID/expiry and approval-digest consistency
fields from the same private decoded request. The existing plan property named
`ApprovalSha256` carries the reviewed outer request digest here; that does not
make the digest an approval authenticator. The actual protected approval channel
must independently authenticate and permanently consume precisely those bytes.
The existing worker-side install claim cannot substitute for that outer channel.

Factories return fresh copied pin dictionaries and immutable string/number data.
The worker-byte accessor returns a copy. Mutating input bytes or an earlier plan's
internal model dictionary cannot change a later factory result. None of these
factories acquires a file, checks a token, instantiates a native acquisition body,
creates a claim, renews a deadline or launches a process.

## Pin first, bounded parsing, exact canonical bytes

Both codecs require independently supplied **length and SHA-256** before JSON
parsing. Python requires immutable `bytes`; C# bounds the caller array before
cloning, hashes the snapshot and parses only that snapshot. Recomputing a pin
from operator-unreviewed bytes is not independent review or authorization.

The C# decoder uses concrete sealed data contracts with required fixed members,
no object-valued members, incoming type resolver, application deserialization
callbacks or carried-code imports. Framework JSON quotas are explicit: depth 12,
array length 128, object-graph items 1,024, bounded string/name-table/read sizes.
Python catches malformed encoding/JSON and recursion refusal behind the same
fixed-label boundary; accepted schema depth is fixed and small.

After schema checks, each side regenerates canonical ASCII bytes and requires
**complete byte equality**, including sorted object keys, ordered file lists,
integer spelling, escaping and exactly one final newline. Unknown/missing keys,
duplicates, alternate whitespace/key ordering, quoted/floating number forms,
noncanonical escapes, prefixes, trailers and changed metadata cannot be normalized
into an accepted request, even when such malformed bytes are rehashed. A different
valid canonical plan can of course be encoded; only the future authenticated
whole-attempt channel can decide whether it was actually approved.

The C# implementation uses the platform **System.Runtime.Serialization** and
**System.Xml** framework assemblies. This adds no third-party package or carried
application DLL, but expands the framework code/load policy that the independent
bootstrap trust review must cover, including any framework-generated code/search
behavior. The four carried executable/config hashes do NOT authenticate those
system assemblies, CLR policy, hooks or DLL resolution. Tests compile/load them
unelevated, not establish protected provenance for them.

## Shape constraints are not host observations

- Canonical drive paths use uppercase drive letters and the earlier restricted
  ASCII component grammar. Launch root is at most 200 characters, other existing
  paths at most 240; the derived `native-validator-<id>` output path must fit 240.
- Launch, import, source and output-parent directories must be lexically disjoint,
  case-insensitively, with no ancestor/descendant overlap. Shared-prefix siblings
  remain valid. All four identities and scratch must be distinct; scratch must
  share the launch volume. Zero indexes, oversized volume/index values and
  noncanonical SID subauthority numbers refuse.
- These are **plan-shape checks only**, not existence, NTFS/ACL/reparse/sharing,
  identity or aliasing observations. The separately trusted handle-based bodies
  still have to acquire and check the real objects without substitution windows.
- Disabled-site `_pth`, empty initializers and both fixed CLR config pins must
  match exact profile bytes. Code/codec descriptor-tree hashes must agree with
  their complete fixed inventories. This checks descriptor consistency, not the
  actual files, archive correspondence, publisher signatures or code safety.
- Runtime, deployment bundle and recovery pins remain **unverified references**
  here. No source/runtime/archive/ISO is opened, parsed, copied or executed.

Budget is **6–900 seconds** and expiry is a bounded integer timestamp shape only.
Neither codec reads a clock or decides that an attempt is timely. The projection's
budget metadata must NEVER start a new full window. Future protected entry points
must hand off the one actual original deadline, enforce current expiry, supervise
assembly loading/acquisition and conserve the process guardian's cleanup reserve.
The prior held-guardian construction-time budget is not that missing outer handoff.

The host review output is at most **64 KiB**, with scope
`local_install_request_consistency_only`. It exposes the complete reviewed input
descriptors, outer/projection fingerprints and derived output path, not an
installed/accepted/authorized/cleanup/Gate-A result. It is ordinary in-memory data,
not protected evidence or a durable receipt.

## Applied verification and committed baseline

The pre-application committed nine-file focused baseline passed **772 tests with one skip**,
warnings as errors: installation boundary, process guardian, held-target boundary,
held guardian, deployment, provisioning, media store, native primitives and native
metadata. Repository Ruff and Windows-hosted Mypy across **104 night-shift source
files** pass. Existing primitive regressions use ordinary disposable non-secret
markers, not a protected installation or this contract. Those are historical
baseline results; the applied results are recorded below.

The applied cross-language corpus uses synthetic inert descriptors and an
independent worker-projection oracle. Cases cover strict host types,
canonical serialization, exact catalogs/profile pins/trees, path/identity
separation, unsigned 64-bit identities, malformed and noncanonical input,
pre-parser pin refusals, resource caps, self-hash/self-pin exclusion, derived
87th pin and factory/input-copy isolation. Compilation includes both prior
acquisition bodies/adapters solely to resolve their fixed types/catalogs; the
models never call their token/file/native P/Invoke methods. Non-Windows CLR tests
skip explicitly; host-only contract tests remain portable.

Ordinary compiler/model processes and temporary inert corpus/source files are
not a protected build, request inbox, native input acquisition, installed guardian,
worker or provisioning attempt.

### Applied verification record

The applied compilation/lint repairs pass. No further source or test repair was
needed after those corrections.

- New applied selection: **166 passed in 1.24 seconds**, warnings as errors,
  no skips or exclusions: **79 host corpus cases, 79 CLR corpus cases and eight
  helper/source checks**. All five actual C# sources compile together. The CLR
  cases invoke the actual new codec/plan factories on synthetic inert inputs,
  not substituted JSON/hash/serialization operations. None invokes an acquisition
  body or native adapter P/Invoke, guardian, worker, interpreter or provisioner.
- Fresh thirty-two-file related selection: **2,268 passed, two skipped in 13.59
  seconds**, warnings as errors, no exclusions. Counts overlap and must not be
  added. This is not a full-repository runtime test run. The selection is every
  `test_bootstrap*.py` module plus `test_public_bootstrap_kvp.py`,
  `test_maintenance_credentials_prototype.py`, `test_protocol_bootstrap_main.py`,
  `test_protocol_test_bootstrap.py`, `test_linux_payload_newlines.py`,
  `test_maintenance_store_native_prototype.py`, `test_native_metadata_comparison.py`,
  `test_native_validator_install_boundary.py`,
  `test_native_validator_process_guardian.py`,
  `test_native_validator_launch_boundary.py`,
  `test_native_validator_held_guardian.py` and
  `test_native_validator_install_request.py`.
- Skips are not native successes. Existing primitive regressions use ordinary
  disposable non-secret marker fixtures, not this contract, a protected launch
  anchor, installed worker or provisioning attempt.
- The initial applied selection passed **86** tests but blocked **79 CLR cases**
  at their one shared compile fixture: warnings-as-errors rejected serializer-
  populated DTO fields as unassigned (`CS0649`). The correction uses **36 trivial
  auto-properties**, preserving every required member name/type and the exact
  wire contract. No warning suppression, fabricated field initializer, schema,
  pin, bound, canonicalization or authorization-policy relaxation was introduced.
- Ruff initially identified **33 one-line block formatting errors** in the test
  helpers. Expanding those blocks preserves their Python AST. One additional
  source regression checks the 36 required auto-properties and absence of pragma
  suppression. The original 79-case CLR corpus also passed with the proposed
  repair in a disposable compiler fixture before application; the results above
  are the subsequent fresh **applied-file** run, not that probe.
- Genuine CLR observations include framework JSON decoding, hashing, complete
  canonical/projection byte equality, unsigned 64-bit identity handling and
  clone/factory isolation. These do not establish trusted framework load
  provenance, native file acquisition, actual input validity, current approval,
  containment, cleanup or installation acceptance.
- Repository Ruff and Windows-hosted Mypy across **105 night-shift source files**
  pass. Scoped Linux-targeted Mypy passes for the new host request module and
  unchanged deployment/provisioning modules with `--follow-imports silent`.
  This is not a clean complete Linux import-graph or Linux C# claim; the earlier
  held-target checkpoint records existing Windows-specific dependency limits.
- Both new Python files pass warning-as-error in-memory compilation and Python
  **3.12** grammar parsing. All **six checkpoint files** pass UTF-8 and
  trailing-whitespace checks; non-ignore files have final newlines. All **four
  local document links** resolve. Tracked `git diff --check` passes.
- One exact `.gitignore` exception exposes the C# codec without widening
  `/scripts/*`; all six checkpoint files are visible in `git status --short`.
  Existing acquisition/guardian sources, both native adapters, tools, PowerShell,
  carried payloads and protected installations/policies/claims are unchanged.
- Catalog, dependency, pin and payload regressions pass. The **91-entry deployment
  bundle**, **87-file import inventory** and guest catalogs are unchanged. The
  new host reviewer is not inserted into the carried Python/import closure.

The validation-record follow-up is documentation-only. Passing real CLR codec
checks on inert descriptors is not independent acquisition of actual inputs,
protected request delivery, approval consumption, original-deadline enforcement,
trusted installation, native provisioning or Gate A.

## Subsequent same-process request/guardian composition

The [request/original-window/held-guardian candidate](night_shift_native_request_guardian.md)
is now applied and verified offline: **59 new tests** pass, including compilation
of nine actual C# sources together and the actual codec exercised with fake
file/process/time backends. The fresh thirty-three-file related selection passes
**2,327 with two skips**, warnings as errors. Repository Ruff and Windows-hosted
Mypy across **105 source files**, scoped Linux typing, Python grammar,
catalog/dependency/pin/payload regressions, links and whitespace pass. No source
or test repair was needed after application.

It adds one terminal byte-request admission path, independent budget/expiry
metadata equality and an internal earlier-deadline cap on the same clock origin.
Waiting for the request and decoding it must consume that local original window
rather than precede a newly started guardian budget. It uses this unchanged codec,
not an alternate parser or a separately supplied launch plan. Native adapters,
request wire bytes, worker projection and all catalogs remain unchanged.

This is a same-process library composition, not authenticated approval, protected
request transport, permanent authorization consumption or cross-process deadline
delivery. It does not supply a worker entry point or Python handoff. The linked
record distinguishes the applied composition checks from this contract's
historical verified 166-test record. Neither is native installation, containment
or protected approval evidence.

## Subsequent approval-anchor isolation check

The [protected-policy approval/permanent-claim guardian body](night_shift_native_approval_guardian.md)
is now applied and verified offline: **86 new tests** pass, including compilation
of ten actual C# sources together and actual codec/composition logic with fake
token/file/process/time backends. Complete claim bytes match an independent
oracle. The fresh thirty-four-file related selection passes **2,413 with two
skips**, warnings as errors. Repository Ruff and Windows-hosted Mypy across
**105 source files**, scoped Linux typing, Python grammar, catalog/dependency/
pin/payload regressions, links and whitespace pass. No source or test repair was
needed after application.

It adds one pure internal method to this codec's bound-input object: require that the separate
approval-root path is lexically disjoint from the launch/import/source/output-
parent paths and its volume/index differs from all five request directory
identities, including scratch. That check runs after the new body's fixed claim
is consumed and before target/process work. It is not a native alias/security
observation, protected approval channel or executable entry point. Wire bytes,
canonical validation, public factories, worker projection and catalogs are
unchanged. The linked record distinguishes the applied isolation/composition
checks from this contract's historical record. Neither is native alias/security,
claim-durability, protected authorization or installation evidence.

## Remaining integration and non-actions

This is the fixed-data-contract prerequisite for the future protected delivery
route, **not** that route. Still required: independently trusted build/install/
starter and load policy; authenticated permanent approval (including early
failure/cancellation consumption); actual original-deadline/request delivery;
guardian/worker entry points; fixed verified Python handoff; independent protected
receipts/reconciliation; then separately approved native experiments.

The host Python reviewer is deliberately **not added to the carried closure**.
The deployment bundle stays at **91 entries**, import catalog at **87 files**,
and guest catalogs/policies are unchanged. A future Python worker entry point or
additional carried module requires its own reviewed catalog/closure change; this
codec does not silently extend the import path or inject inline Python code.
At this contract checkpoint, the existing C# acquisition/guardian bodies, native
adapters, tools, PowerShell and protected installations/claims were unchanged.
The subsequent composition adds the held guardian's internal deadline cap and
calls this codec as documented above; native adapters, tools, PowerShell and
protected installations/claims remain unchanged and unwired.

After trusted provisioning still follow the fixed diskless VM operation,
permanent execution claim, independent **VM-lifetime watchdog/evidence**, native
confinement proof and trusted image/channel work. Process/request checking does
not contain service-created VMs or establish their final absence.

No actual request, bundle, executable or ISO was materialized, no protected claim
consumed and no installation deployed. No elevation, carried-runtime execution,
provisioning, guest execution, VM operation or commit occurred.
**Gate A remains unrun.**
