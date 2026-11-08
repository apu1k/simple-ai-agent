# Fixed C# worker entry and section receiver — uninstalled candidate

## Status and exact scope

**Applied and verified offline; not installed or exercised natively.** All
**85 new tests** pass, including **81 CLR scenarios**, four source guards and
compilation of all ten actual C# sources together as a library. The fresh
38-module related selection passes **2,822 with two skips**, warnings as errors.
This checkpoint adds `scripts/native_validator_worker_entry.cs`: a fixed worker `Main`, a bounded
inherited-section receiver and composition into the existing
[worker lifetime owner](night_shift_native_worker_guardian.md) and
[fixed Python adapter](night_shift_native_worker_windows.md). It is NOT a
protected parent publisher, trusted build/install/starter, authenticated approval
channel, installed executable or tool operation. Never build, load or execute
checkout code elevated. No roadmap/status/preflight document is changed.

The committed pre-application focused baseline passed **284 tests**, warnings
as errors, across worker lifetime, fixed Python launch and Python worker handoff.
That historical baseline is not verification of this entry/receiver checkpoint.

The applied tests compile **ten actual C# sources as a library**, including the
entry source, and use fake input/clock/file/process backends. They exercise the
actual frame/deadline/owner composition but never invoke `Main`, any receiver
P/Invoke or a carried interpreter. Source guards describe native policy shape,
NOT observed Windows behavior. No worker executable or real approval/request/
section input is created by these tests.

## Applied verification and timing repair

The initial applied module passed **82 tests**, including compilation of all ten
sources; its related selection passed **2,819 with two skips**. An additional
fault check then reproduced a gap BETWEEN deadline sampling and owner
construction: the entry forwarded the raw clock, so the new inner clock wrapper
could forget the earlier sample and accept a rollback at its first observation.
Those initially passing suites did not cover that boundary.

The applied repair creates ONE existing `WorkerClock` guard in the entry before
any samples. It spans translation, owner construction and request reception;
the owner's additional wrapper cannot reset the outer guard's history. Three
new regressions inject rollback, NaN and infinity immediately after sampling and
require UNKNOWN **before input reception, import claim or process work**.
Initial/in-sample invalid clock observations also use the guard's UNKNOWN code
125, rather than the earlier local refusal classification. Unsupported but
finite clock profiles and invalid frame/counter shapes remain refusals. No
native receiver/adapter, request format, catalog or launch policy was changed.

Fresh verification after application of source and regression repairs:

- New applied module: **85 passed in 1.15 seconds**, warnings as errors, no skips
  or exclusions: **81 CLR scenarios plus four source guards**. All ten actual C#
  sources compile together as a library. Cases include strict frame bounds,
  pin-first actual codec/owner composition, no renewed budget after reception,
  clock faults across the sampling/constructor boundary, fixed import-claim
  replay refusal, conditional owner retention, local outcome labels and terminal
  concurrent/repeated calls. Native receiver methods and `Main` are NOT invoked.
- Complete **38-module** related selection: **2,822 passed, two skipped in
  23.44 seconds**, warnings as errors, no exclusions. This is every
  `test_bootstrap*.py` and `test_native_validator_*.py` module, plus
  `test_public_bootstrap_kvp.py`, `test_maintenance_credentials_prototype.py`,
  `test_protocol_bootstrap_main.py`, `test_protocol_test_bootstrap.py`,
  `test_linux_payload_newlines.py`, `test_maintenance_store_native_prototype.py`
  and `test_native_metadata_comparison.py`. Counts overlap and must not be added.
  This is not a full-repository runtime run. The new module has no skips;
  existing skips and ordinary disposable native primitive fixtures are not
  evidence of protected/native-worker success.
- Repository Ruff and Windows-hosted Mypy across **105 night-shift source files**
  pass. Scoped Linux-targeted Mypy passes for provisioning, deployment and the
  host request reviewer with `--follow-imports silent`; this is not a complete
  clean Linux import-graph claim.
- The changed Python test passes warning-as-error compilation and Python **3.12**
  grammar parsing. All **five checkpoint files** pass UTF-8 and trailing-
  whitespace checks; all **four local documentation links** resolve. Tracked
  `git diff --check` passes, with untracked-file whitespace checked separately.
  The intended five files are the entire `git status --short` scope.
- Related catalog/dependency/pin/codec/payload regressions pass. Existing carried
  Python, native adapters, runtime/catalog names, tool/PowerShell wiring and
  protected installations/policies/claims remain unchanged. No deployment or
  worker executable was materialized; independently reviewed worker build and
  launch pins remain prerequisites.

No further source or test repair was needed after applying the shared guard.
These results verify compiled composition and modeled lifetime ownership, NOT
actual section rights/layout/inheritance, QPC coherence, Windows loader/job/death
behavior, native child absence, parent authentication, installed execution or
provisioning. In particular, source guards do not establish the native park or
the mandatory external supervisor's bound/reconciliation.

## Why a different incoming transport

The outer canonical request can be **32,768 bytes**; its Base64 cannot fit the
Windows command-line limit. The subsequent Python edge carries only the derived
held worker request (at most 8 KiB) and remains unchanged. This receiver copies
only the outer request through one read-only unnamed section handle; it does not
reopen a request file or accept stdin, an environment blob, a pipe or a named
object. There is no command-line full-request fallback and no shortened schema.

The future protected parent must supply exactly eight arguments after the EXE:

1. `--provision-once-section-v1`.
2. Canonical positive decimal inherited section handle (x64, at least four,
   multiple of four, at most `Int64.MaxValue`).
3. Independently bound outer-request byte count, 1–32,768.
4. Independently bound lowercase SHA-256 of the entire canonical outer request.
5. Original budget, 6–900 seconds.
6. Original UTC expiry.
7. Earlier absolute common-machine Windows QPC counter limit.
8. Matching QPC frequency, 1–1,000,000,000 ticks/second.

There are no selected commands, code paths, reset, cleanup or retry options.
Arguments are immutable consistency metadata, not credentials or secrets. The
array is cloned, field counts/alphabets/ranges are strict, and noncanonical
numbers or hashes refuse before host, clock or input operations. The mode is
intentionally incompatible with the unchanged historical guardian command
(`--provision-once` without a frame). That command cannot operate this entry;
no installed runnable route or backward-compatible default is supplied.

## Trust prerequisites — NOT established by these checks

Before this assembly loads, a separately reviewed protected parent/starter must:

- Establish exact OS/CLR/executable/DLL provenance and the reviewed worker build.
- Authenticate and permanently consume whole-attempt approval, including the
  separately defined early-failure/cancellation policy.
- Hold the exact launch executables/configuration/private scratch/load closure.
- Bind these metadata and actual request bytes to that approval and the original
  deadline; reserve its own stop time INSIDE the same earlier window.
- Publish a private, unnamed section with exact reviewed bytes, remove every
  writable view/handle/alias, and retain only the read capability to be delivered.
- Use an explicit `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` containing ONLY that exact
  read handle, together with atomic `JOB_LIST` assignment, suspended creation,
  controlled environment/CWD and the existing held-target pre-resume checks.
- Independently supervise the exact worker/Python tree, including starter,
  guardian or worker death, with protected outcomes/reconciliation.

**This checkpoint implements NONE of that parent publisher/launcher or trust
setup.** The existing outer adapter still disables inheritance and is unchanged.
It must not simply be switched to unrestricted inheritance or have metadata
appended. The new Python adapter also still disables handle inheritance.

The entry checks x64 Windows, the exact worker basename and an enabled
Administrator role before receiving bytes. After the actual canonical request
has been independently pinned/decoded, the existing Python kernel checks the
full bound worker host path and exact enabled operator SID BEFORE consuming the
import claim. These checks are necessary consistency/role checks, not pre-load
provenance, parent authentication or approval consumption. An inherited handle,
matching pins or a successful hash cannot retroactively establish any of those.
Administrators/SYSTEM and the trusted OS/CLR/load closure remain in the TCB.

The receiver requires `GetHandleInformation` to show exactly inheritance enabled
and `NtQueryObject(ObjectBasicInformation)` to report exactly `SECTION_MAP_READ`
(no query/write/all-access grant). A successful bounded read-only `MapViewOfFile`
proves section type before adopting native cleanup ownership. It removes and
reads back the inheritance flag before copying. It unmaps/closes once, disarming
local ownership before each checked release; either release failure overrides
any data return with UNKNOWN. Before adoption, a rejected raw handle is not
closed speculatively. Process exit still closes its process handle table; that
is not a claim of individually checked native closure. No interpreter or import
acquisition has begun at that stage.

Rights/layout/inheritance checks need native characterization. They do not prove
that the parent removed all writable aliases, or establish an unnamed section's
origin/security, immutability or parent authorization. Those are independently
reviewed publisher obligations, not evidence inferred from `MapViewOfFile`.

## Original window and fixed composition

The entry is terminal and serialized before parsing or any platform work. ONE
rollback/nonfinite guard spans translation, owner construction and reception;
inner wrappers cannot forget that earlier sample history. It translates the
common-machine cap conservatively into its local clock:

1. Sample local monotonic time BEFORE common QPC samples.
2. Require matching frequency, ordered positive counters, local ordering and both
   sampling spans at most 250 ms; reject nonfinite/negative/oversized local time.
3. Use the LATER QPC sample and EARLIER local sample. UTC expiry can only shorten
   the remaining counter interval, which must be at most 900 seconds.
4. Subtract one millisecond plus one microsecond for conversion/addition margin
   at supported local clock magnitudes. Refuse without an execution window beyond
   the existing five-second inner stop reserve.
5. Construct the ACTUAL `WorkerProvisionGuardian` under that mandatory earlier
   local cap BEFORE reading the section. Read/copy/close/decode/import/setup and
   interpreter loading all consume that cap. There is no fresh duration or
   serialized foreign `Stopwatch` timestamp.
6. Pass the copied bytes through the actual pin-first canonical codec/owner. Its
   import claim, held-request copy, pre-resume closure checks, fixed native Python
   adapter and process stop/observation rules remain unchanged.

The parent must send a cap no later than its OWN execution stop point. The inner
five-second reserve remains INSIDE that already earlier window; reserves are not
added back. Small remaining windows therefore refuse, even when the schema's
six-second minimum budget was valid at approval time. Native QPC coherence/rate,
loader and clock behavior remain assumptions to characterize, not model proof.
Cooperative checks cannot interrupt arbitrary blocked kernel/CLR work; the
independent original-window watchdog remains mandatory.

## Exit versus hold: do not drop imports after uncertainty

`WorkerEntry.Run` returns only a local code: 0 for checked normal child exit 0,
126 for known refusal/checked normal child exit 126, otherwise 125 (UNKNOWN).
Timeout, residual-tree stop, other child codes or missing observations do not
become success. Exit 0 is NOT an installation grant or protected receipt.

Crucially, these local codes do NOT always authorize process exit. The entry
retains the actual owner and exposes an internal `MustParkForSupervisor` fact.
When imports are deliberately retained after uncertain child creation,
termination or process-handle closure, `Main` holds a strong reference and parks
without disposing/unlocking/exiting or retrying. There is deliberately no local
exit timer: it would drop locks while child absence is unknown. Only the
independent exact-tree job/watchdog may stop this worker together with its child.
The park is NOT a self-contained bounded operation; the mandatory parent and
watchdog must supply that bound. Source/model tests do not execute or prove this
native stop/death behavior. Protected reconciliation and final process absence
remain missing.

The owner is released normally only through its existing checked absence/close
path. A false retained flag is not a protected absence receipt. No exception text,
stdout/stderr evidence, acceptance record, claim reset, deletion or automatic
retry is emitted. A new entry object cannot reset an existing import claim.

## Remaining route and non-actions

Next: implement/review the protected immutable section publisher and explicit
one-handle atomic worker launch, original-request/window binding through approval
and held-target guardians, guardian executable entry, trusted build/install/
starter, early-failure/cancellation policy, independent watchdog and protected
receipts/reconciliation. Then characterize actual Windows behavior before a
separately approved provisioning attempt. VM lifetime supervision and actual
Gate A protocol/image acceptance remain separate later boundaries.

No elevation, protected installation/claim, actual section acquisition, native
worker/Python execution, carried-runtime load, provisioning, VM operation or
commit occurred. **Gate A remains unrun.**
