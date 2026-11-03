# Held validator executable-target acquisition body — unwired candidate

## Status and scope

**Applied and verified offline; not installed or exercised natively.** All
**120 new tests** pass, including compilation of both actual C# sources. The
fresh thirty-file related selection passes **2,026 with two skips**, warnings
as errors. This is the held-target source slice following the
[provisioning-process guardian body](night_shift_native_process_guardian.md).
It does not change that guardian, install a starter, authenticate approval,
consume authorization, launch a process or invoke Python. Never compile or load
checkout code elevated.

- `scripts/native_validator_launch_boundary.cs`: immutable copied plan pins,
  fixed launch inventory, bounded complete hashing and explicitly held lease.
- `scripts/native_validator_launch_windows.cs`: read-only relative Windows
  acquisition, strict security/identity checks and checked handle closure.
- `tests/night_shifts/test_native_validator_launch_boundary.py`: fake file,
  token and clock models compiling both actual C# sources, plus source guards.

The clean committed focused baseline passes **576 tests with one skip**,
warnings as errors. That seven-file selection is the installation-boundary,
process-guardian, deployment, provisioning, media-store, native-primitive and
native-metadata test modules. Repository Ruff and Mypy across **104 night-shift
source files** pass. Those results concern the committed baseline, not these new
sources. The skip is unavailable unelevated symlink creation. Existing primitive
tests use ordinary disposable non-secret markers, not a protected launch anchor.

## Two distinct trust boundaries

1. A separately reviewed protected starter must establish its own executable,
   OS/CLR/assembly/DLL/configuration provenance and the guardian's provenance
   **before their first instruction/assembly load**. It must authenticate and
   permanently consume the actual whole-attempt authorization, sanitize the
   initial environment/search context and bind the reviewed plan. None of that
   starter/approval/install machinery is supplied here.
2. The independently trusted guardian must acquire and retain its own launch
   closure before creating its worker. It cannot depend on a parent's locks
   surviving, a filename/self-hash as authority, or a Python verifier checking
   the runtime after imports. This body supplies the file-acquisition part only.

Hashing an already running guardian is a consistency observation, not proof of
its prior load provenance. Fixed .NET configuration bytes do not authenticate
Windows/.NET, machine policy, environment hooks or system DLL resolution. Those
remain independently reviewed prerequisites. No cryptographic signing/key
workflow or alternate approval mechanism is introduced in this checkpoint.

## Fixed, preprovisioned launch anchor

This is a new, independently reviewed private launch root, not the Python import
anchor, provisioning output, data inbox or an existing protected installation:

```text
validator-install-guardian.exe
validator-install-guardian.exe.config
validator-provision-worker.exe
validator-provision-worker.exe.config
scratch/                              # must initially be empty
```

The future build profile is two self-contained application assemblies compiled
from the separately reviewed sources, with no extra application DLL, probing
subdirectory, plugin or incoming configuration. Neither executable/build recipe
nor an entry point is supplied here. OS/.NET/system-DLL dependencies live outside
this four-file inventory and require their separate trust boundary, NOT omission
from trust review. The two source names/config names match the guardian's fixed
roles. The worker's later Python import closure remains separately acquired by
the earlier boundary inside the contained process tree.

The plan binds a canonical local drive path (maximum 200 characters), the root's
NTFS volume/index identity, the scratch directory's distinct index, exact
operator SID, installation ID, external approval digest/expiry, at most 900
seconds and four independent length/SHA-256 pins. Each executable is bounded to
16 MiB. Both .config pins must additionally match the fixed byte profile: CLR v4,
.NET Framework 4.8, no legacy-v2 activation and remote-source loading disabled.
Even rehashing another config does not authorize it. No XML parser or assembly
loader is used by this body; executable bytes are opaque reviewed inputs, not
proof of architecture, signatures or safe behavior.

All root children must match exactly, including case. Extra DLLs, configs,
missing names, case aliases and duplicate enumeration entries refuse. Scratch is
independently identity-bound, same-volume, private and initially empty; the
pre-launch reverification also requires it empty. Scratch can subsequently hold
fixed worker/CLR temporary data under future reviewed execution. This API is
specifically **pre-launch** verification, not a post-worker temp-cleanup API.
There is no create, populate, overwrite, delete, ACL repair or claim operation.

## Acquisition and lease contract

1. Validate and copy the complete fixed pin dictionary before native access.
   The plan is forgeable data; IDs, hashes and fresh objects confer no authority.
2. Disarm one-shot acquisition before the first token/file operation. Require
   native x64 Windows, the exact SID and enabled Administrators membership.
3. Acquire one fixed local NTFS volume and all path ancestors with no-delete
   directory handles. Traverse relative to held parents with no-reparse object
   and file options. Require volume-GUID final names, same volume, distinct
   identities and the independent root/scratch identities.
4. Require the same strict ancestor mutation policy as the earlier boundary.
   Private directories/files require BA/SYSTEM ownership, BA group, protected
   DACL and exactly the two full-control ACEs with the fixed inheritance flags.
   No TrustedInstaller exception is introduced. Incompatible stock ancestry
   refuses; this is not permission to change Program Files or Windows ACLs.
5. Open all four input leaves with READ access and **FILE_SHARE_READ only**;
   directories allow read/write sharing but not delete. Reject reparse, multilink,
   sparse, compressed, offline, encrypted or wrong-kind shapes. Check held parent
   metadata before and after child acquisition. There is no path reopen handoff.
6. Check exact root/scratch inventories, complete length/hash/exact EOF for every
   leaf and exact fixed config bytes. Recheck every held identity/security/path
   before returning. Short successful reads are bounded progress; failed reads,
   zero progress, excess data and metadata/byte drift are terminal.
7. Keep all handles held. `ReverifyBeforeLaunch()` repeats inventories, complete
   hashes and metadata checks through the same handles, with no reopen, renewed
   budget or native token reacquisition.

The native adapter is independent of the earlier acquisition/provisioning
assembly and carried Python. That separation is intentional: the guardian must
protect a worker before loading the worker's larger closure. This checkpoint
keeps its strict read-only adapter separate rather than silently changing the
previous independently reviewed source/claim contract. The duplicated native
security rules are covered by explicit SDDL models; future consolidation would
need its own dependency/load-order review.

The constructor's original monotonic budget is capped by the external UTC expiry,
initially at most 24 hours away. It is cooperative, not a process watchdog or a
mathematical bound on blocked Windows/CLR calls. Future integration must derive
this and the guardian/worker budgets from **one original attempt deadline**;
starting each component with a fresh full budget is forbidden. Protection of the
starter/guardian during assembly loading and this acquisition remains required.

## Failure, uncertainty and lock retention

Acquisition and lease operations are serialized separately. Failed acquisition
attempts every acquired close in reverse order; each resource slot and native
handle is disarmed before its single close attempt. A duplicate handle is not
adopted/closed twice; a distinct aliasing object is owned before rejection.
Native scratch allocations are released before returned-handle transfer. Close
uncertainty overrides other outcomes, and there is no retry or finalizer.

**A returned lease that fails reverification is poisoned but does not release
its locks.** It cannot reverify successfully after data is restored. This is
intentional: the boundary cannot know whether another component already created
a child or whether termination is uncertain. Automatically disposing locks on a
verification error could release the very targets still in use.

The caller must explicitly dispose exactly once only when no child has been
started, or after independently established exact-owned process-tree absence.
Idempotent disposal does not retry uncertain closes. A dropped lease leaks process
resources; it is not permission to continue, start another process or retry an
attempt. Process death releases file handles; future protected integration must
retain independent reconciliation/evidence and deal with that case rather than
assuming this managed object survives it.

This body cannot distinguish authenticated approval from invented plan fields,
prevent replay across processes, retain locks after its host dies, bind a lease
to a concrete guardian invocation, or establish cleanup evidence. The future
starter/guardian integration must explicitly cross-bind the launch plan with the
guardian and worker/import/request plans, verify the actual loaded target and
search policy before use, preserve the original deadline and enforce permanent
whole-attempt consumption including cancellation/failure before any worker claim.
The existing fixed install claim does not supply that outer approval channel.

## Applied offline verification and remaining work

No source or test repair was needed after application. The new tests compile
both actual C# sources with a same-assembly fake file/token/clock backend. All
new file/token/time observations are substituted, and the native adapter's
P/Invoke operations are never invoked. Models cover exact catalogs/configs,
bounded reads, identity/security/path drift, close uncertainty, poisoned-lease
retention, concurrent one-shot acquisition, SDDL/ABI layout and directory-buffer
decoding.

### Applied verification record

- New applied selection: **120 passed in 0.83 seconds**, warnings as errors,
  no skips or exclusions: **116 CLR models and four source checks**. Compilation
  occurs in ordinary temporary compiler/model processes, not an installed or
  protected build. Model executable bytes are synthetic, inert and never run.
- Fresh thirty-file related selection: **2,026 passed, two skipped in 12.15
  seconds**, warnings as errors, no exclusions. Counts overlap and must not be
  added. This is not a full-repository runtime test run. The selection is every
  `test_bootstrap*.py` module plus `test_public_bootstrap_kvp.py`,
  `test_maintenance_credentials_prototype.py`, `test_protocol_bootstrap_main.py`,
  `test_protocol_test_bootstrap.py`, `test_linux_payload_newlines.py`,
  `test_maintenance_store_native_prototype.py`, `test_native_metadata_comparison.py`,
  `test_native_validator_install_boundary.py`,
  `test_native_validator_process_guardian.py` and
  `test_native_validator_launch_boundary.py`.
- The skips remain Linux-only disposable-fd behavior and unavailable unelevated
  symlink creation, not native successes. Existing primitive regressions use
  ordinary non-secret disposable markers, not this adapter, a protected anchor,
  installed guardian, worker or provisioning attempt.
- Genuine CLR observations are compilation, SDDL parsing, struct layouts and
  bounded directory-buffer decoding. Source guards check fixed role names,
  read-only native flags, scratch-resource/handle-transfer ordering, poisoned
  lease retention, tracking exceptions and absence of launcher/tool/bundle
  wiring. They do not establish native sharing, ACLs, load provenance or cleanup.
- Repository Ruff and Windows-hosted Mypy across **104 night-shift source files**
  pass. Linux-targeted Mypy of the unchanged deployment/provisioning targets
  passes with `--follow-imports silent`. The initial unscoped Linux import-graph
  check reported **21 attribute errors in three unchanged Windows-specific
  dependencies** (`hyperv_image_preflight.py`, `ubuntu_preparation_control.py`
  and `maintenance_store_native_prototype.py`). Those dependencies are unchanged
  from HEAD; no source repair or blanket error suppression was introduced.
  This scoped result is not a clean full Linux import graph or C# portability
  claim.
- The new Python test passes warning-as-error in-memory compilation and Python
  3.12 grammar parsing. Both C# sources, the test and both checkpoint documents
  pass UTF-8, final-newline and trailing-whitespace checks; **three local document
  links** resolve. Tracked `git diff --check` passes.
- Exactly two additional `.gitignore` exceptions expose the new C# paths without
  widening `/scripts/*` otherwise; its no-final-newline convention is preserved.
  All **six checkpoint files** are visible in `git status --short`. All runtime,
  Python application, earlier acquisition and guardian source files remain
  unchanged. The validation-record follow-up is documentation-only.
- Catalog, dependency, pin and payload regressions pass. The **91-entry Python
  deployment bundle** and **87-file import inventory** are unchanged, and no new
  C# source is inserted into a Python/guest/protected deployment.

Ordinary CLR compilation, SDDL parsing and layout observations are not native
read-locking, sharing, ACL or installed-executable evidence. Non-Windows CLR models
skip explicitly, never report native success. No executable test bytes are run;
model executable data is inert, synthetic and kept in memory. Temporary compiler
files are ordinary non-secret test harness data, not a protected build.

Next remains the separately reviewed protected starter/build/install route,
authenticated and permanently consumed approval, fixed guardian entry point and
worker/Python handoff, followed by separately approved native provisioning and
watchdog experiments. This candidate is not called by the guardian, any tool,
launcher or installer; it does not expand the 91-entry Python deployment bundle,
87-file import inventory, guest payloads, existing claims or protected policies.
The later diskless VM operation STILL needs independent VM-lifetime enforcement
and exact-VM absence evidence; process containment does not supply those.

No protected anchor/claim, deployment bundle, executable or ISO was created,
installed or copied. No elevation, guardian/worker/carried-runtime execution,
provisioning, VM operation, deployment activation or commit occurred.
**Gate A remains unrun.**
