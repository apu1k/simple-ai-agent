# Fixed Python launch and worker entry — unwired candidate

## Status and scope

**Applied and verified offline; not installed or exercised natively.** All
**76 new tests** pass, including **26 CLR scenarios**, compilation of all nine
actual C# sources together and a CLR-frame-to-Python entry/handoff composition.
The fresh thirty-seven-module related selection passes **2,737 with two skips**,
warnings as errors. This connects the worker lifetime owner's launch interface
to a separate fixed Windows Python adapter and a private entry in the existing
carried provisioning module. It is not a protected starter or installed runnable
chain. No Rust, third-party dependency, runtime catalog filename, CLI, `Main`,
PowerShell operation or tool wiring is introduced.

- `scripts/native_validator_worker_windows.cs`: fixed native Python adapter,
  bounded argument construction and conservative QPC deadline frame.
- `scripts/native_validator_worker_guardian.cs`: the immutable launch context
  additionally carries the SAME internal clock used by its lifetime owner.
- `night_shifts/bootstrap_native_provision.py`: private fixed-host/argument
  receiver, QPC-to-local translation and invocation of the existing handoff.

The [worker lifetime composition](night_shift_native_worker_guardian.md) still
has no live default or executable constructor. The existing outer guardian's
native adapter/command/environment are unchanged. This new adapter must not
be substituted into that independent guardian: it belongs in the exact contained
C# worker and starts ONLY its one carried Python child.

**Never compile, load or run checkout code elevated.** The separately trusted
build/install/starter must establish OS/CLR/executable/DLL provenance BEFORE
this assembly loads, authenticate and permanently consume whole-attempt approval,
deliver the original request/deadline, hold the executable/scratch targets and
arm an independent protected process watchdog. The worker must acquire/retain
its verified import closure before interpreter load. None of these prerequisites
can be established retroactively by argument, path, SID or hash equality.

## Fixed launch and lifetime

The adapter checks native x64 Windows, the exact enabled administrator SID and
the fixed `validator-provision-worker.exe` host path. Repeated host checks must
bind the same plan. These checks are NOT provenance or authorization. Its
`Bind` is terminal and stages immutable bounded context only; no native work or
process starts there.

The new exact-owned unnamed/non-inheritable BA/SYSTEM-private job has checked
kill-on-close/no-breakaway flags and an active limit of **one**. It is nested
under the separate guardian's two-process worker/Python job. Unsupported nested
jobs or atomic job-list assignment refuse, without a fallback or retry. The
interpreter is created suspended with the job assigned AT creation; the existing
process core checks membership and the owner's full import closure before
resume. It retains import locks after any uncertain creation/termination outcome.
Native temporary allocations are released before transferring child handles;
failures close local handles while the caller still owns the kill-on-close job.

The application is ALWAYS `<bound-import-root>\runtime\python.exe`, with fixed
`-I -S -B -c` and a fixed source literal. No request-selected executable, module,
script, option, environment variable, stdin stream, pipe name or inherited handle
is accepted. The literal replaces `sys.path` with ONLY held payload, stdlib ZIP
and runtime directories, then invokes the private `_run_fixed_worker` once.
The disabled-site `python314._pth` profile remains independently verified by
the import boundary. No payload initializer is allowed to gain code.

The complete environment still has only PATH/SystemRoot/WINDIR/TEMP/TMP, built
with the original fixed environment helper and Windows API system paths. CWD and
TEMP/TMP use the separately held launch root/private scratch, not a caller's
current directory. Handle inheritance is disabled. No provider keys or hooks are
copied. The interpreter/DLLs and all dynamic imports remain inside the separately
verified held runtime plus trusted OS load closure. Actual Windows/CPython loader
search behavior, framework dependencies, command parsing and nested job semantics
STILL require pre-load review and native characterization; source constants are
not evidence of those platform behaviors.

## Bounded non-secret delivery

The nine arguments following fixed code are:

1. Bound import root.
2. Base64 of the ACTUAL held-reader worker bytes.
3. Independently derived worker byte count.
4. Independently derived worker SHA-256.
5. Bound outer request SHA-256.
6. Original budget seconds.
7. Original UTC expiry.
8. Earlier absolute Windows QPC counter limit.
9. Matching QPC frequency.

Only the existing canonical path alphabet, Base64, lowercase hashes and bounded
canonical positive decimal fields can reach command construction. Paths have no
quotes or trailing separators. Worker bytes remain at most 8 KiB; the complete
command must be strictly below 16,384 UTF-16 characters, below the Windows limit.
No shell performs expansion. These are NON-SECRET consistency fields, visible
in process command lines; credentials/tokens MUST NEVER be added here. No real
input frame or executable is materialized by the offline tests.

Protected exact-process creation and trusted immutable installed code must supply
the delivery authority. A matching command/hash/QPC number is not authentication:
a forged invocation cannot become approved just because all consistency checks
pass. The protected parent/entry route and permanent early-failure/cancellation
handling are still missing, so no installed authenticated channel is claimed.

## Preserve, do not recreate, the deadline

A process-relative C# `Stopwatch` value is never sent as a Python `monotonic()`
timestamp. Immediately before fixed process construction, the adapter samples
common-machine QPC BEFORE the owner's local clock, then QPC/frequency again.
It refuses nonpositive/changed frequency, rollback, a sample wider than 250 ms,
nonfinite/expired local time, counter overflow or more than 900 seconds remaining.
It maps the shortened remaining original execution window onto the EARLIER QPC
instant, floors ticks, subtracts one millisecond plus one tick and freezes that
absolute limit before further setup/loading. Stop reserve is already excluded.

The Python entry samples local monotonic time BEFORE two common QPC samples,
then local time again. Frequency, ordering and both 250 ms sampling bounds must
match. It maps the original remaining counter interval onto the EARLIER local
instant, subtracts a millisecond and rounds down one float step. Extremely large
local clock values refuse to bound rounding error. The existing handoff can only
shorten that deadline with budget/UTC expiry. Setup, interpreter/module load,
argument decoding and provisioning all consume the earlier cap, never renew it.
Native coherence/rate behavior of these clocks remains an OS/CLR/CPython premise
to characterize; the model does not prove platform time behavior or hard bounds
on blocking kernel work. The separate watchdog is still mandatory.

The private entry checks exact host/runtime/isolation/import-path consistency and
strict tuple/field bounds. It constructs the actual one-shot handoff under the
translated deadline BEFORE Base64 decoding. Canonical Base64 and complete byte
pins precede JSON parsing. No file reopen occurs. It invokes the existing fixed
provisioner only through that handoff. Exit 0 is local consistency success ONLY;
126 is refusal and 125 is unknown. Post-provisioning uncertainty cannot become
success. No output, exception text, acceptance record or protected receipt is
emitted. Process exit alone is never an installation grant or retry permission.

## Baseline and applied verification

Fresh committed focused baseline: **343 passed in 3.92 seconds**, warnings as
errors, across worker lifetime, Python handoff/provisioner and process guardian.
These are baseline results, not verification of this new source or tests.

The applied tests compile all nine actual C# sources together, invoke only pure
command/frame operations with synthetic counters, and pass the resulting CLR
argument frame to the actual Python entry/handoff with a fake provisioner. They
cover frame bounds/canonical encodings, cross-language field mapping, no renewed
budget, counter/clock refusal, fixed host refusal and unknown outcome labels.
Source guards check fixed atomic job/handle/command policy. Existing composition
models continue to cover import lifetime and process-core faults. No P/Invoke,
carried interpreter, native child or real provisioning is invoked by these tests.
Textual tokenization is NOT evidence of native Windows CRT command parsing.

The provisioner isolation regression admits exactly the new internal
`handoff.run(raw)` edge in `_run_fixed_worker`, constructed with the translated
earlier deadline. It retains the existing exact `body.run()` edge and all broad
process/import/repair/deletion prohibitions. `sys` is permitted only for the two
fixed host/counter gates, never generic argv/exit handling in the carried module.

### Applied verification record

The initial applied new selection had **49 passing Python/source checks**, while
**27 CLR-dependent checks** were blocked before compilation: embedding the large
outer request in PowerShell's UTF-16/Base64 compiler command exceeded Windows'
command-line limit. The test-only repair stores that inert request in the owned
temporary fixture directory and reads it from the compiler harness, with an
explicit compiler-command length guard. This does NOT reopen a real held worker
request or change the production interpreter's separate 16,384-character bound.

Once compilation was reached, the oversized-window model needed one input
correction: UTC expiry was correctly reducing its attempted 901-second window
to 900, so it was not actually out of range. The adjusted synthetic wall time
leaves 901 seconds and exercises the intended refusal; no deadline guard or
assertion was removed. An unused test import and extra EOF blank line were also
removed. Explicit callable field annotations and configuration of local function
references before publication fix scoped Linux typing for Windows-only counter
initialization. The native function signatures/ABI and deadline algorithm are
unchanged. No C# source repair or warning/type suppression was needed.

Fresh verification after application of all repairs:

- New applied module: **76 passed in 1.25 seconds**, warnings as errors, no skips
  or exclusions: **26 CLR scenarios and 50 Python/composition/source checks**.
  All nine actual C# sources compile together. The real CLR command-frame
  output reaches the actual private Python entry and handoff using a fake
  provisioner/counter/host profile. The fixed bootstrap literal is parsed, NOT
  executed in a carried interpreter; no new adapter P/Invoke method is invoked.
- Focused four-module selection: **336 passed in 4.60 seconds**, warnings as
  errors, no skips. This includes the new module, worker lifetime composition,
  Python handoff and provisioning body. This selection differs from the earlier
  343-test committed baseline, which included the process guardian instead of
  the new 76-test module; the counts are not directly comparable or additive.
- Complete **thirty-seven-module** related selection: **2,737 passed, two skipped
  in 20.41 seconds**, warnings as errors, no exclusions. This is every
  `test_bootstrap*.py` and `test_native_validator_*.py` module, plus
  `test_public_bootstrap_kvp.py`, `test_maintenance_credentials_prototype.py`,
  `test_protocol_bootstrap_main.py`, `test_protocol_test_bootstrap.py`,
  `test_linux_payload_newlines.py`, `test_maintenance_store_native_prototype.py`
  and `test_native_metadata_comparison.py`. Counts overlap and must not be added.
  This is not a full-repository runtime run. Existing fixture skips and ordinary
  disposable native primitive fixtures are not protected/native-worker success.
- Repository Ruff and Windows-hosted Mypy across **105 night-shift source files**
  pass. Scoped Linux-targeted Mypy passes for provisioning, deployment and the
  host request reviewer with `--follow-imports silent`; this is not a complete
  clean Linux import-graph claim.
- All **four changed/new Python files** pass warning-as-error in-memory
  compilation and Python **3.12** grammar parsing. All **eleven checkpoint
  files** pass UTF-8 and trailing-whitespace checks. Newline conventions are
  preserved, including the pre-existing missing final newline in `.gitignore`.
  All **18 local document links** resolve. Tracked `git diff --check` passes;
  the eleven intended files are the entire `git status --short` scope.
- Related catalog/dependency/pin/codec/payload regressions pass. The **91-entry
  bundle** and **87-file import closure** retain names/counts. The original
  outer guardian native adapter/command/environment, tool/PowerShell wiring and
  existing protected installations/policies/claims remain unchanged. Actual
  deployment pins/runtime/bundle/ISO were not materialized. Changed carried
  Python source STILL requires fresh independent code/bundle pins before use.

This follow-up is documentation-only. These results verify compiled adapter
shape, synthetic counter arithmetic, bounded codec composition and Python
behavior with fake provisioning. They do NOT establish actual QPC coherence,
Windows CRT parsing, native loader/locking/job/death/cleanup behavior, protected
parent authentication, installed execution or real provisioning.

## Remaining route and non-actions

Still required: protected build/install/starter and guardian/worker executable
entry points; authenticated original request/approval/deadline delivery into the
worker (this candidate covers ONLY the worker-to-Python edge); permanent
cancellation/early-failure policy; protected outcome receipts and independent
reconciliation; native token/ACL/loader/locking/QPC/CRT/job/death characterization.
No end-to-end installed-worker/provisioning success is claimed. VM supervision
remains a distinct later boundary with its own watchdog and exact VM/disk absence.

No actual bundle/runtime/ISO/approval frame was materialized. No elevation,
protected claim, installation, native worker/Python launch, provisioning,
VM operation or commit occurred. **Gate A remains unrun.**
