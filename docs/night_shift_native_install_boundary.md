# Validator pre-import acquisition and install-claim body — unwired candidate

## Status: applied and verified offline, not a trusted bootstrap

**Original checkpoint applied and verified offline; not installed or exercised
natively.** Its **115 new tests** passed, including compilation of both actual
C# sources; its twenty-eight-file related selection passed **1,823 with two
skips**, warnings as errors. Those are historical original-checkpoint results.
The worker-input/lease update below is now separately applied and verified
offline: **155 boundary tests**, including **40 added tests**, and the fresh
thirty-five-module related selection of **2,578 with two skips** pass, warnings
as errors. Neither checkpoint is installed or exercised natively. This is the
first implementation slice of the installation
trust boundary after the
[create-new provisioning body](night_shift_native_provisioning_body.md).
It is two C# library sources, not an executable, installer, approval mechanism,
protected tool, Python entry point, watchdog or VM operation:

- `scripts/native_validator_install_boundary.cs`: fixed acquisition/verification
  ordering, inventory, byte hashing, install-claim contents and held lease.
- `scripts/native_validator_install_windows.cs`: relative Windows opens,
  handle-based metadata/security, directory enumeration and create-new claim I/O.

**Never compile or load checkout code elevated.** Before this assembly is loaded,
a separately reviewed protected bootstrap must establish the OS/.NET/assembly
trust closure, authenticate the actual approval/plan and arm an independent
process watchdog. This candidate cannot make its own assembly or CLR trustworthy
by checking Python files afterward. There is no such installed executable,
authenticated approval channel or process watchdog in this checkpoint.

The clean committed focused baseline passed **378 tests with one skip**, warnings
as errors, across deployment/provisioning/media-store/native-primitive/metadata
regressions. Repository Ruff and Mypy across **104 night-shift source files** pass.
These are baseline results, not results for the proposed C# or tests. The skip is
unavailable unelevated symlink creation. Existing primitive tests use ordinary
non-secret disposable markers, not a protected installation or this adapter.

## The prerequisite anchor is not the provisioning output

The input is one separately preprovisioned private bootstrap anchor whose exact
canonical local path, NTFS volume/index identity and entire byte inventory have
been independently reviewed. This component does not create or populate that
anchor. Its secure preparation/build/install route remains required; it must not
be improvised by elevating the checkout or reusing an old inspection installation.
The later provisioning output remains a separate create-new tree.

The fixed anchor has exactly these root children:

```text
claims/                         # only the fixed install-attempt.claim after creation
payload/night_shifts/...         # 29 fixed code/policy members, including empty initializers
payload/pycdlib/...              # 17 fixed codec members
payload/pycdlib-1.21.0.dist-info/ # three fixed metadata/license members
runtime/...                     # 37 fixed CPython 3.14 x64 embeddable-profile members
provision-request.json           # independently pinned opaque request bytes
```

There are **87 independently pinned input files**: the deployment bundle's
86 runtime/code/codec members plus the request. The retained public/runtime
input archives and recovery ISO are NOT added to the import path. The
[91-entry deployment bundle](night_shift_native_deployment_inputs.md) and all
public/native/inspection payload catalogs are unchanged. The C# boundary must
be protected independently; carrying it inside an unchecked Python bundle would
not establish pre-import trust.

The base import-plan request bound remains 32 KiB; request bytes are hashed but
never parsed here. The fixed worker-copy API additionally
requires 1–8,192 bytes, matching the existing derived worker projection. The
[Python-side worker handoff](night_shift_native_worker_handoff.md) validates that
projection's canonical provisioning semantics, including source/output paths,
identities and bundle/recovery pins. Trusted pre-load acquisition, delivery and
actual fixed launch are still required before invoking that Python body. A hash
of operator-unreviewed bytes is not authorization.

## Fixed acquisition and claim ordering

1. Validate the immutable copied pin inventory, path components, operator SID,
   installation ID and external approval-digest shape without native acquisition.
   Budget is 1–900 seconds, capped by the original UTC approval expiry; approval
   expiry must initially be within 24 hours. Hashes/objects confer no authority.
2. Disarm one-shot acquisition before native work. Require native x64 Windows,
   the exact operator SID and enabled Administrators membership. Acquire the
   fixed local NTFS root and each ancestor with no-delete directory handles.
3. Open components relative to their held parents with `OBJ_DONT_REPARSE` and
   no-reparse file options. Require the independently reviewed anchor identity,
   stable volume-GUID final names and same-volume, distinct object identities.
   Directory allocation size is not identity; file size and bytes are checked.
4. Verify the existing private `claims` directory, then atomically create only
   **`claims/install-attempt.claim`**, with `FILE_CREATE`, exclusive sharing and
   the exact protected Administrators/SYSTEM-only file descriptor at creation.
   This name does not vary with the installation ID. A new object or ID cannot
   bypass a claim in the same approved anchor. Existing/partial claims refuse.
5. Write the bounded non-secret claim once, check the exact write, flush, and
   read it back through the same held handle. Require unchanged identity/security
   and exact bytes. Only the controlled archive-bit delta and expected new file
   length are allowed. No writer-to-reader reopen gap is introduced for the claim.
6. Acquire every fixed directory and file. All input leaf readers use
   **FILE_SHARE_READ only**. Held directories permit read/write sharing but not
   delete. Reject reparse, multilink, sparse, compressed, offline and encrypted
   shapes. Recheck parent metadata and final names during acquisition.
7. Enumerate each held directory, rejecting missing/extra/duplicate/case-alias
   entries. Hash every complete pinned input with exact EOF and before/after
   metadata checks. Enforce empty package initializers and the exact disabled-site
   `python314._pth` bytes even if a changed profile is rehashed. No archive parser,
   carried Python/codec import, interpreter or DLL is invoked.
8. Return a held `ImportClosureLease` only after all final checks within the
   original deadline. Explicit reverification repeats inventory, bytes and
   metadata checks without acquiring new handles or renewing time.

The claim binds the complete root identity/path, installation ID, external
approval digest, SID, approval expiry and fixed file pins, using an unambiguous
length-prefixed plan digest. Its JSON scope is
`install_attempt_consumed_not_acceptance`. It contains no accepted/installed/
execution/Gate-A grant. The request's complete hash is part of this binding;
its contents cannot select the import inventory or an executable here.

The ancestor mutation policy remains the strict native primitive's BA/SYSTEM
owner policy; no TrustedInstaller exception or ACL repair is introduced. Private
objects additionally require group BA, protected DACL and exactly the two full
control entries, with the fixed directory/file inheritance flags. An incompatible
existing anchor/ancestry refuses. This does not authorize changing stock Windows
or Program Files permissions to make it work. Administrators, SYSTEM, the kernel
and the independently established OS/CLR closure are trusted, not adversaries.
Read-sharing rules do not exclude all metadata-only opens; descriptor policy and
repeated metadata checks remain separate protections.

## Lifetime, failure and remaining authorization boundary

Acquisition is serialized and one-shot, including concurrent callers. Lease
reverification/copy/disposal is serialized separately. Acquisition failure still
attempts every acquired handle close in reverse order; it has returned no lease
and starts no process. Both the resource slot and native handle are
disarmed before the single close attempt; close uncertainty overrides otherwise
successful work. Native scratch allocations are released before handle transfer,
so a release failure cannot strand a returned, unowned handle.

The worker-input update changes the original lease failure behavior:
after successful acquisition, reverification or fixed request-copy failure poisons
the lease but NEVER automatically closes its handles. Further verification/copy
refuses before native access, even if a fault is repaired or a clock recovers.
This prevents a failed check from silently unlocking a potentially live child's
import closure; it is NOT proof of child absence or a complete lifetime owner.

Explicit disposal remains available and idempotent, including after poisoning;
an uncertain first close is not retried. The future worker lifetime owner MUST
establish child absence before calling it. Do not wrap a potentially live/uncertain
child's lease in an unconditional `using`/`finally`. No process starts here, so
explicit test disposal after failure is only a no-child model cleanup, not native
reconciliation evidence. There is no finalizer, automatic retry, overwrite,
unlink, rollback, claim reset, permission repair, source/output copy, process
start or cleanup sweep. A dropped undisposed lease is a process-resource leak;
external process containment and protected reconciliation remain mandatory. Locks
do not survive disposal/host death and cannot authorize a later import. A
successful/idempotent disposal is not a process-absence certificate.

A successful flush/read-back is not a power-loss/storage-rollback guarantee.
Native filesystem durability remains to be established. Claims/artifacts after
failure must be retained for review; apparent absence after uncertainty never
authorizes a retry. Token/anchor failures before atomic claim creation do not
create a claim. The future protected authorization channel must enforce its
whole-attempt/cancellation policy independently, including failures before this
body runs. This claim component does not supply that channel.

The monotonic/UTC checks are cooperative. Native hashing, reads, flushes or CLR
operations can block between checks. **The independent protected process watchdog
must cover assembly loading/acquisition as well as later provisioning.** It is
not supplied by these sources. The eventual VM runner additionally needs its
independent VM-lifetime watchdog and exact-VM absence evidence; neither follows
from terminating a provisioning process.

Even while the lease is held, the future trusted wrapper must enforce fixed
Python executable/arguments/import paths, environment, working directory and DLL
search policy BEFORE first carried-code execution, retain this lease for the
entire child lifetime, and reconcile uncertain child termination before closing
it. This checkpoint supplies no such wrapper or Python provisioning entry point.
A locally verified lease is NOT a launch grant or protected receipt.

## Worker-input lease update — applied and verified offline

The applied boundary suite passes **155 tests**: **148 CLR models and seven
source guards**, including **37 added CLR models and three added source guards**.
Both actual C# sources compile with the fake token/file/time backend. No source
or test repair was needed after application. The changes stay in the existing
two-source compilation unit and introduce no native API, adapter change, executable entry
point, C# application DLL, tool wiring, runtime language or third-party dependency.
The C#/Python split is unchanged; no Rust is introduced.

`ImportClosureLease.CopyWorkerRequest()` has no path/name/handle argument. It:

1. Requires a still-open, unpoisoned lease and the independent fixed request pin's
   1–8,192-byte bound. An over-bound request poisons without starting a copy.
2. Repeats the complete held inventory/metadata/hash/claim verification.
3. Allocates one fresh bounded byte array and hashes/copies ONLY
   `provision-request.json` through its ALREADY HELD read-only reader. Exact
   length, full pin/hash, EOF and before/after metadata still apply. There is no
   reopen, new handle, source path, parser, caller callback, claim write or reset.
4. Repeats the complete closure/claim verification BEFORE releasing any bytes.
   The returned array is independent of the held file and every other return.
   Caller mutation cannot change the held data or the next copy.
5. On any failure, returns no bytes, permanently poisons the lease and retains
   its locks. Unknown native exception text remains normalized to fixed labels.

This supplies actual fixed held-file bytes, not proof of protected transport or
request authorization. The trusted caller must derive the worker pin from the
bound outer request and must still deliver the bytes/pins under the independent
original deadline BEFORE Python reception/decoding. No live policy or actual
worker request is acquired in the offline models.

A new INTERNAL constructor overload accepts an earlier absolute deadline in the
SAME supplied monotonic-clock origin. It can only shorten the existing budget/
expiry window; NaN, infinity and expired/equal caps refuse before native work.
The public constructor is unchanged. All acquisition, hashing, verification and
fixed-copy passes consume that original cap; observed monotonic rollback and
nonfinite readings refuse. A clock/window failure after acquisition also poisons
and retains the lease. Null internal file/clock dependencies refuse at construction.
This is same-process budget conservation, NOT authenticated cross-process clock
translation or hard interruption of a blocked native call. The future process
watchdog and its stop/cleanup reserve remain independently required.

Fresh committed baseline before drafting this update: **709 passed in 7.84
seconds**, warnings as errors, no skips, across installation boundary, request
codec, request guardian, approval guardian, Python worker handoff, deployment and
provisioning. Repository Ruff and Windows-hosted Mypy across **105 night-shift
source files** pass. These are historical baseline results, not validation of
the new C# or test additions. Fresh applied results are recorded below.

The applied CLR models extend the existing fake token/file/time backend. They
cover fixed held-file bytes and independent copies, full pre/post verification,
short reads, bounds, read/hash/metadata/inventory/EOF faults, post-copy drift,
poisoned lock retention/no-I/O reuse refusal, concurrent copies, checked explicit
close failure and shorten-only/original-window/rollback behavior. The original
reverification-failure model is intentionally updated from automatic close to
poisoned retention. Source guards bind the independent 8 KiB limit to both worker
contracts and prohibit a new opener/parser/claim/reset or production wiring.
These are not native Windows sharing, claim durability, Python execution or
process-absence observations.

Catalog names/counts remain **91 bundle entries / 87 pinned import files**.
The updated C# is outside the carried Python catalog. Future guardian/worker
builds require fresh independently reviewed executable pins; this does not
materialize an executable, deployment bundle, request or protected anchor.

### Worker-input update applied verification record

- Applied boundary suite: **155 passed in 1.08 seconds**, warnings as errors,
  no skips or exclusions. All **148 CLR cases** compile/run the actual two C#
  sources with substituted token/file/time observations; **seven source guards**
  pass. Relative to the original suite, this adds **37 CLR cases and three source
  guards**. The original verification-failure case now requires poisoning and
  retained handles rather than automatic closure. Counts overlap and must not
  be added.
- Fresh **thirty-five-module** related selection: **2,578 passed, two skipped in
  18.60 seconds**, warnings as errors, no exclusions. This is not a full-repository
  runtime test run. The selection is all `test_bootstrap*.py` modules plus
  `test_public_bootstrap_kvp.py`, `test_maintenance_credentials_prototype.py`,
  `test_protocol_bootstrap_main.py`, `test_protocol_test_bootstrap.py`,
  `test_linux_payload_newlines.py`, `test_maintenance_store_native_prototype.py`,
  `test_native_metadata_comparison.py` and the seven `test_native_validator_*`
  modules: installation boundary, process guardian, launch boundary, held
  guardian, installation request, request guardian and approval guardian.
- Existing skipped fixtures are not native successes. Ordinary disposable native
  primitive fixtures are not this C# adapter or a protected installation/anchor.
  No new model invokes the adapter's P/Invoke, native import acquisition, a real
  claim, installed worker/guardian, carried interpreter, provisioner or VM.
  Temporary CLR compiler/harness files are ordinary non-secret model fixtures.
- New cases establish modeled fixed held-reader copying, independent arrays,
  full pre/post verification, no reopen/extra handle/claim write, the exact 8 KiB
  copy bound, short-read progress, hash/metadata/inventory/read/EOF/post-copy
  faults, permanent poison/no-I/O reuse refusal, lock retention, concurrent
  serialization and terminal explicit-close uncertainty. Deadline cases cover
  shortening/non-extension, invalid caps, reception/hash/copy budget consumption,
  UTC expiry, observed rollback/nonfinite values and null internal dependencies.
- Repository Ruff and Windows-hosted Mypy across **105 night-shift source files**
  pass. Scoped Linux-targeted Mypy of provisioning, deployment and the host request
  reviewer passes with `--follow-imports silent`. This is not complete Linux
  import-graph validation or native Windows ABI/locking evidence.
- The changed Python test passes warning-as-error in-memory compilation and
  Python **3.12** grammar parsing. All **four checkpoint files** pass UTF-8,
  final-newline and trailing-whitespace checks. All **seven local document links**
  resolve. Tracked `git diff --check` passes; exactly the four intended files
  appear in `git status --short`.
- The Windows adapter and native open/security/claim contracts are unchanged.
  Public acquisition construction, fixed claim bytes/name, `.gitignore`, tool/
  PowerShell wiring, guardian/request codec sources, all Python sources and
  deployment/import/guest catalogs are unchanged. The bundle remains **91
  entries**, the pinned import inventory **87 files**. Updated future executable
  builds still need fresh independent pins and protected review before use.

The validation-record follow-up is documentation-only. These models do not prove
native share modes, lock retention, claim durability, protected delivery,
pre-load provenance, process absence, installed execution or watchdog behavior.
Explicit disposal still needs an external lifetime owner's absence decision;
this API is not that owner or a protected cleanup/evidence channel. No source
or test repair was required after application.

## Original applied offline verification and next milestone

The new Python test module compiles both actual C# files with an ordinary
same-assembly fake token/file/clock backend using the existing Windows CLR
compiler. Its temporary source/compiler files contain only non-secret models.
All file/token/native-adapter operations are substituted; the native adapter's
P/Invoke methods are never called. Real CLR SDDL parsing, managed ABI layouts
and bounded directory-buffer decoding are tested, not live Windows ACL or lock
behavior. Non-Windows systems explicitly skip CLR models, not report native
success. Catalog/dependency/native-constant assertions remain ordinary source
checks. No compiler, carried interpreter or privileged program is deployed.

### Applied verification record

- New applied selection: **115 passed in 0.93 seconds**, warnings as errors,
  with no skips or exclusions: **111 CLR models and four source checks**. Both
  actual C# files compile in the ordinary test process with the same-assembly
  fake backend. This is not a protected build or installation. All observations
  of native files, handles, tokens and time are substituted; no candidate
  P/Invoke method is invoked.
- Fresh twenty-eight-file related selection: **1,823 passed, two skipped in
  10.23 seconds**, warnings as errors, no exclusions. Counts overlap and must
  not be added. This is not a full-repository runtime test run. The selection is
  every `test_bootstrap*.py` module plus `test_public_bootstrap_kvp.py`,
  `test_maintenance_credentials_prototype.py`, `test_protocol_bootstrap_main.py`,
  `test_protocol_test_bootstrap.py`, `test_linux_payload_newlines.py`,
  `test_maintenance_store_native_prototype.py`, `test_native_metadata_comparison.py`
  and `test_native_validator_install_boundary.py`.
- The two skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation, not native successes. Existing native primitive
  tests use ordinary non-secret disposable marker fixtures, not this C# adapter
  or a protected anchor. Source snapshot regressions are ordinary read-only
  observations, not independent approval or protected provisioning.
- Initial applied tests found **two test-fixture errors**, not C# behavior
  defects: SDDL `DC` parses as the directory-service bit `0x2`, not NTFS
  delete-child `0x40`; `WA` is not a valid rights token. The repair uses explicit
  file-right masks and asserts the CLR's parsed masks. Additional models cover
  that `DC` distinction, write-EA, write-owner and generic-all. Neither C# source
  nor the native ancestor/private policy needed a repair after application.
- Exactly two `.gitignore` exceptions expose the C# source paths; the existing
  `/scripts/*` exclusion otherwise remains. A new source guard checks their
  exact spelling/order. Its pre-existing no-final-newline convention is retained.
  All **six checkpoint files** are now visible in `git status --short`.
- Repository Ruff and Windows-hosted Mypy across **104 night-shift source files**
  pass. Linux-targeted Mypy of the unchanged deployment/provisioning components
  passes; this is Python compatibility evidence, not Linux C# validation.
- The test module passes warning-as-error in-memory compilation and Python 3.12
  grammar parsing. Both C# sources, the test and both documents pass UTF-8,
  final-newline and trailing-whitespace checks; **five local document links**
  resolve. Tracked `git diff --check` passes.
- The independent fixed runtime/code/codec catalogs match the existing host
  closure. Existing related pin/payload/dependency regressions pass. The host
  bundle stays at **91 entries** and the boundary's pinned input inventory at
  **87 files**. No C# member is added to a Python/deployment or guest payload,
  and no runtime/launcher/tool/protected-policy/guest implementation is changed.

The verification-record follow-up is documentation-only. Passing these models,
compiler and source checks does not establish actual Windows sharing, native ABI
calls, private-token/ACL protection, claim durability, protected installation,
import/DLL confinement, watchdog behavior, native boot or final VM absence.

The separate
[provisioning-process guardian body](night_shift_native_process_guardian.md) is
now applied and verified offline: **83 new tests**, including compilation of
both actual C# sources with a fake kernel/token/clock backend, pass. The fresh
twenty-nine-file related selection passes **1,906 with two skips**, warnings as
errors. Its private unnamed kill-on-close job, atomic job-list assignment,
fixed worker role, original deadline and exact-owned empty-tree checks remain
unexercised natively. No source/test repair was needed after application.
Repository Ruff and Mypy across **104 source files**, Python compatibility/
grammar, catalog/dependency/pin/payload checks, links and whitespace pass.

It is not installed, not an executable entry point and not a native watchdog
result; the trusted approval channel, held-target bootstrap and worker/Python
handoff remain absent. It deliberately does not load this acquisition assembly
before containment; the original guardian checkpoint did not change this
component or its 87-file inventory. The worker-input lease update above changes
only this acquisition body and its models, not that guardian. It is now verified
offline, not wired into a worker or protected execution route.

The remaining runnable boundary is the separately protected executable/approval/
held-target installation and fixed provisioning handoff, followed by separately
approved native validation. No existing tool, installation, claim, protected
policy or guest source is wired or changed here.

No actual anchor, claim, input bundle or ISO was created or copied. No elevation,
protected installation, carried-runtime execution, guest execution, VM operation,
deployment activation or commit occurred. **Gate A remains unrun.**
