# Exact-child validator owner — source candidate only

## Milestone and status

This is the native owner/spawn and pipe-I/O component of the **fixed diskless
validation-VM operation**, following the [fixed child bootstrap](night_shift_native_child_bootstrap.md).
It is not a runnable nine-worker validator, boot entry, protected host operation,
cleanup receipt or Gate A implementation. Source application is not execution
approval. **Applied and verified offline; not deployed or executed natively.**
All **118 new owner tests** pass with substituted native adapters. The six-file
owner/child/RAM/core/worker/audit selection passes **648 with no skips**; the
wider sixteen-file related selection passes **1,196 with two skips**. These
counts overlap and must not be added together. Applied results are recorded below.

The committed baseline was rerun before drafting: the fifteen-file related
selection passed **1,078 tests with two skips**, warnings treated as errors.
Repository Ruff and Mypy across **95 night-shift source files** passed; the
working tree was clean. The skips remain Linux-only disposable-fd behavior and
unavailable unelevated symlink creation, not native successes.

`night_shifts/bootstrap_native_owner.py` is intentionally unwired and absent from
production/public media inventories. Import alone does not acquire resources;
**constructing NativeWorkerOwner would spawn a native child**. Do not construct
it on the workstation or run a generated launch command as a validation shortcut.
There is no CLI or caller-selected command, plan, path, source, environment,
profile, signal target or executable API. Existing worker/bootstrap bytes,
AppArmor policy, launcher and protected deployments are unchanged.

## Acquisition and launch

Before creating pipes the owner requires the pinned Linux/x86-64 kernel and
isolated/no-site/no-bytecode Python 3.12, root identity without supplementary
groups, exact LANG/LC_ALL environment and unconfined label. It requires one
kernel task, no existing direct children, no retained prior uncertain process,
default SIGCHLD disposition, and absent ignored/caught/blocked SIGCHLD bits in
bounded proc status. No signal-handler repair, subreaper setup or global reaper
is supplied. Complete immutable-media/tool identity, established private
namespace/chroot/RAM layout and held fixture checks remain external prerequisites.

It creates two pipes with O_NONBLOCK and O_CLOEXEC, verifies root-owned mode-0600
FIFO identities/flags, and internally renders the existing fixed setpriv/fresh
Python plan using the original absolute guest-monotonic deadline. It enforces:

- argv directly, shell=False, close_fds=True and only the two exact pass_fds;
- stdin/stdout/stderr=DEVNULL, cwd `/`, environment exactly LANG=C and LC_ALL=C;
- no preexec_fn, shell, selectable helper, process-group signal or alternate plan.

The child bootstrap remains responsible for alias-safe 3/4 mapping, closing all
extra descriptors, capability/NNP and label checks before worker evaluation. The
parent promptly closes its child-end pipe copies and acquires a non-inheritable
pidfd. It never calls Popen.poll/wait/kill/terminate/send_signal or uses Popen as
a context manager: those APIs can consume/reinterpret the child lifetime.

A strong private Popen reference is retained until a verified exact consuming
wait. Dropping the owner or a constructor exception must not let Popen.__del__
automatically poll/reap before capture. A retained uncertain object blocks a new
owner; this intentionally does not pretend to clean up a lost process. The
caller must still explicitly abort in a finally block. Interpreter termination
is not an absence proof and requires the independent host watchdog.

Single-task/proc checks are prerequisites, not proof against hostile supervisor
code, external reapers or unobservable native signal flags. Exact-child waitid
errors (including ECHILD) remain UNKNOWN and latch off further lifecycle calls.
In particular a pidfd acquired after a failed/autoreaped launch is not itself
proof of a direct-child relationship: cleanup first performs exact-child
waitid(P_PIDFD, WEXITED|WNOHANG|WNOWAIT), never signals after a failed observation,
and never uses a numerical-PID kill fallback.

## Operational sequence and bounds

The trusted future supervisor must perform:

```text
await_ready
  -> acquire fresh authentic audit cursor and check held fixtures
  -> release_gate
  -> observe_exit (WNOWAIT; retain unreaped child)
  -> finish authentic audit capture/correlation and held-fixture checks
  -> reap_after_capture
```

The owner does not implement or authenticate the caller's cursor, capture,
correlation or fixture checks. Method names and local observations are not
native evidence. There is deliberately no caller-supplied `audit_ok` boolean or
host-receipt acceptance field. Full supervisor integration must enforce the
above order before it can be considered runnable.

- Readiness/report evaluation uses the existing strict WorkerReportSession,
  including 256-byte/two-frame/512-byte aggregate bounds and fixed exit-37 exec
  control handling. EOF alone is not success. Pipe reads are nonblocking and at
  most 512 bytes. Queued pre-gate data is rechecked and never discarded.
- Gate release is one nonblocking write of exactly G, then one close, then the
  report-session gate observation. Short write, EAGAIN, disconnect or uncertain
  close is terminal; no gate-write retry can duplicate the operation.
- Every operation uses the same original at-most-five-second deadline, including
  render/startup/readiness, gate, reports and exit. No stage renews it. Poll has no
  selector descriptor and waits at most 20 ms per slice, supporting high fd
  numbers without select's FD_SETSIZE restriction.
- Report EOF and a matching normal waitid observation are required to return
  LocalWorkerObservation. The child is **not reaped** by that call. Signals,
  unexpected status, protocol failures, missing observations and budget failure
  cannot become a successful local worker observation.
- Only explicit reap_after_capture consumes a successful child with an exact
  nonblocking waitid. It checks PID/code/status against the held observation,
  sets Popen.returncode and releases the private reference only after that check.
  A consuming wait can have taken effect even if it reports an error; uncertainty
  is latched before the syscall, so no second reap/signal is attempted.

Deadline checks and cancellation callbacks are cooperative, trusted supervisor
code, not enforcement against a hung callback, kernel syscall, source read or
Popen startup. Kernel/native scheduling and setpriv/exec behavior remain
unverified. The independent host lifetime bound is still mandatory.

## Failure cleanup is not an execution retry

Errors latch the owner terminal. A constructor failure performs one cleanup
attempt; after a method failure the caller must invoke abort once, discarding
all success/attribution claims. Failure cleanup has a separate **one-second**
monotonic waiting bound, which does not renew the worker's deadline or permit
result acceptance. Cancellation must not suppress cleanup.

Cleanup observes an exact child without reaping; if still running, it sends
SIGKILL only through the owned pidfd and then performs bounded exact observation
and reap. An already exited child needs no signal. If pidfd acquisition failed,
only exact direct-child P_PID observation/reaping of an already exited child is
allowed; a live child is retained UNKNOWN without numerical signaling. No
wait(-1), process search, killpg, broad cleanup or permission repair exists.

An uncertain prior wait/reap disables further lifecycle operations. Signal or
wait error, timeout, mismatched identity/status or uncertain descriptor close
returns cleanup_unknown. Every remaining owned descriptor is still attempted
once. A descriptor is removed from ownership **before** close; a consumed or
uncertain integer is never retried. An uncertain cleanup cannot be restarted.
Known-closed abort is a no-op, not a new attempt or VM/tree-absence receipt.

## Applied offline verification

`tests/night_shifts/test_bootstrap_native_owner.py` replaces every native OS,
process, poll, runtime reader and clock adapter before construction. It uses the
real fixed renderer and report evaluator; embedded code is only decoded/parsed
as data. The model covers fixed spawn options, all six case/mode combinations,
fragmentation, protocol/gate ordering, original deadlines/cancellation, stalled
I/O and exit, exact unreaped ownership, failed pidfd acquisition, wrong PID,
ECHILD, abnormal exits, redacted errors, uncertain wait/reap/close handling and
one-shot cleanup. It also builds the actual inspection ZIP in memory and checks
that the owner remains excluded there and from the public support source list.

Reproduce the applied checks:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_owner.py tests/night_shifts/test_bootstrap_native_child.py tests/night_shifts/test_bootstrap_native_ram.py tests/night_shifts/test_bootstrap_native_supervision.py tests/night_shifts/test_bootstrap_native_worker.py tests/night_shifts/test_bootstrap_native_denials.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/bootstrap_native_owner.py --follow-imports=silent --platform linux
git diff --check
```

### Verification record

- Owner-only selection: **118 passed in 0.32 seconds**, warnings as errors, no
  skips or exclusions. The real renderer and report core run against substituted
  process/OS/poll/clock adapters; no native child, signal, pipe or wait is used.
- Six-file owner/child/RAM/core/worker/audit selection: **648 passed in
  1.22 seconds**, warnings as errors, no skips or exclusions.
- Wider sixteen-file related selection: **1,196 passed, two skipped in
  5.43 seconds**, warnings as errors, no exclusions. This includes the 118 new
  owner tests and prior 1,078 passes; it is not a full-repository runtime run.
  The two skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation. Neither counts as native success.
- Repository Ruff and Mypy across **96 night-shift source files** pass.
  Linux-targeted Mypy of the owner also passes. Cross-target typing is not
  execution on Linux or native ABI validation.
- Both new Python files pass warning-as-error in-memory compilation and Python
  3.12 grammar parsing. No generated launch command or worker code is executed.
- All four checkpoint files pass final-newline/trailing-whitespace checks;
  **six local document links** resolve; tracked `git diff --check` passes.
- The actual inspection ZIP, built only in memory by the passing inventory
  regression, and public support source inventory exclude the owner. No other
  night-shift source imports it. Existing tracked production/runtime/script
  sources match HEAD; only the bootstrap documentation is tracked-modified,
  alongside the new owner, test and owner-document files.

No source or test repair was needed after application. This record update is
documentation-only. Passing models cannot establish Linux pipe/pidfd ABI
behavior, actual capability dropping, AppArmor transition, authentic audit
capture or absence of a native process/VM.

## Next runnable-milestone integration

Still required before the fixed diskless operation can execute:

1. Integrate the [kernel-log capture and single-worker sequence
   candidate](night_shift_native_kernel_capture.md) into full paired sequencing.
   It wires fixed /dev/kmsg collection, this held-child lifetime, held fixtures
   and local denial correlation. Its **107 collector tests**, two additional RAM
   tests and **1,305 combined related tests with two skips** pass. Ruff and
   Linux-targeted typing pass; the linked record covers the narrow Windows-
   hosted Linux-stat declaration follow-up and required applied-file check.
   Full paired sequencing and actual native lossless attribution remain
   unverified.
2. The complete nine-worker order plus confined allowed-pool read/write/record-
   lock positive controls, bounded summary and unresolved network/capability
   audit-visibility decision; no broader policy to force a pass.
3. Reviewed immutable complete media and one protected diskless host operation,
   independent watchdog/evidence and independently verified exact-VM absence.

These are prerequisites of the selected autonomous route, not Gate A success.
Image acceptance, trusted real credential bootstrap and authenticated Hyper-V
UART communication remain open. No native worker, policy transition, media
write, elevated command, VM operation, deployment or commit is part of this
checkpoint. **Gate A remains unrun.**
