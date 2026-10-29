# Process-isolated native Linux serial validation candidate

## State and immediate purpose

**Applied and verified as a Windows-hosted test/supervisor checkpoint. Native
Linux PTY execution remains unverified.** This follows the committed
[guest serial/TLS candidates](night_shift_guest_serial_candidate.md). It adds
executable Linux PTY tests, not another guest runtime or a protected VM runner.
The production serial/TLS modules, fixed device policy, installed worker,
service, deployment inventories and protected helpers are unchanged.

The committed guest checkpoint is `524322b`. Before drafting these tests, its
52 Windows-hosted model/MemoryBIO tests were rerun with warnings as errors and
passed. That is baseline verification, not a result for this new checkpoint.

The immediate missing evidence is whether the candidate's real Linux tty
configuration, polling and cleanup calls work, rather than just their modeled
call sequence. Disposable pseudo-terminals let us test much of that without
claiming access to a physical serial device or an accepted VM image.

## Executable test boundary

- `tests/night_shifts/linux_serial_native_fixture.py` owns the test supervisor
  and the fixed native case implementations. It has no CLI, service entry,
  arbitrary command interpreter or production import/activation path.
- `tests/night_shifts/test_guest_serial_device_io_linux.py` contains **nine native
  PTY cases** and **24 portable supervisor/receipt/input regressions**. On this
  Windows host, **24 pass and nine skip**. None of those skips is a native pass.
- Only a fresh child's `pty.openpty()` pair is used. The private test API changes
  **open and identity validation only**, requiring the exact newly owned PTY
  device/inode and nonblocking/non-inheritable flags. It does not patch the
  production `DEVICE`, forge `stat` results or pretend a PTY is major/minor 4:64.
- Native production `termios`, flock, TIOCEXCL/TIOCNXCL, read/write, poll and close
  implementations remain in use. Instrumentation records real poll calls and
  actual accepted write bytes; it does not synthesize success or short writes.
- One case explicitly verifies the **unmodified production identity validator
  rejects the PTY**. The public opening interface remains fixed to `/dev/ttyS0`;
  neither this case nor any other test calls that public opening interface.
- There is no VM, network socket, existing tty, service, mount, target disk,
  production credential, policy load, package installation or media operation.

## Native cases and evidence

| Case | Required observation inside the owned child |
| --- | --- |
| Raw round trip | Actual raw settings, speeds and control-byte settings read back; all byte values survive in both directions, including NUL, CR/LF and software flow-control bytes. |
| Production identity refusal | Actual PTY fails the production ttyS0 device check, with no device-policy relaxation. |
| Fragmented input | Short independently written fragments and control bytes are reconstructed unchanged. |
| Silent read | Actual EAGAIN/poll and expiry under the original budget, not an artificial clock. |
| Stalled write | Undrained PTY causes actual partial writes and polling, then deadline failure; accepted prefix is not replayed. |
| Cancelled read/write | Trusted cancellation is set only after a real poll completes; terminal cancellation and close follow. |
| Shared deadline | A successful first read followed by a silent second read retains the same authoritative deadline. |
| Claim/recycled descriptor | An independent existing open cannot take the held flock; after close it can, attributes match the original, and repeated channel close cannot close a reopened descriptor. |

Every successful native case also requires original tty attributes restored,
owned channel fd detached and observed EBADF before reuse, no cleanup uncertainty,
and a successful new slave open after release. An already-open observer fd is a
fixture resource, not evidence that TIOCEXCL evicts pre-existing opens. Privileged
bypass of tty claims is not ruled out.

PTYs are not a UART emulator. Passes do **not** establish ttyS0 identity, Hyper-V
serial behavior, guest console/getty exclusion, device ownership in a deployed
image, real host/guest TLS interoperability, trusted credentials, AppArmor/KVP
confinement, image acceptance or Gate A success.

## Exact-child supervision and reports

Each case runs in a fresh `spawn` child. The parent waits at most eight seconds
for normal exit before reading one at-most-1024-byte fixed-schema JSON receipt.
The receipt has no paths, byte traces, exception text or keys. Child data is never
received as pickle; trusted process startup still uses multiprocessing's own
bootstrap serialization. Receipt schema, duplicate names, types and ranges are
checked, and a missing/malformed/failure receipt cannot become a native pass.

On an overrun the parent terminates only its exact child, observes it for two
seconds, then if necessary kills that exact child and observes for two seconds.
**Any required termination fails that native case.** An unconfirmed exit is
`fixture_process_cleanup_unknown`, and the exact process object is retained.
There is no process-name search, broad cleanup, reader thread or unbounded join.
The portable deliberate-hang regression expects the supervisor's failure; it
is not a successful native tty test or evidence of graceful tty restoration.

These are ordinary test-process controls, not a protected watchdog: a parent
crash/provider hang or external test timeout does not prove child exit. The
outer shell/tool cap does not replace fixture observations. No production
lifetime or VM cleanup guarantee is conferred.

## Verification and execution route

Reproduce the applied Windows-hosted checks:

```text
python -W error -m pytest -q tests/night_shifts/test_guest_serial_device_io_linux.py
python -W error -m pytest -q tests/night_shifts/test_guest_serial_device_io.py tests/night_shifts/test_guest_bounded_tls_serial.py tests/night_shifts/test_guest_serial_device_io_linux.py
ruff check .
git diff --check
```

On Windows the **nine Linux cases must skip**. Only portable supervisor/receipt
results can pass there. Do not record collection, grammar parsing, Linux-targeted
typing, Windows syscall models or those skips as native Linux execution.

Later, in a separately reviewed Linux test environment with the existing test
dependencies available, run the same native test file. Each of the nine PTY
cases must execute and exit normally; missing PTY/native ABI support is a failure,
not an automatic fallback or package-install request. Retain platform/kernel,
Python/OpenSSL versions and per-case outcomes alongside the exact source commit.
No Linux environment is selected, started or authorized by this source batch.
Do not silently substitute WSL, change a retained VM or activate guest candidates.

### Applied verification record

- New test module: **24 passed, nine skipped in 1.37 seconds**, warnings treated
  as errors. All nine skips explicitly require a native Linux disposable PTY.
- Combined nine-file transport selection: **278 passed, nine skipped in
  9.19 seconds**, warnings treated as errors, with no exclusions. This includes
  the 24 portable regressions, the prior 254 transport cases and their existing
  **20 native Windows cases**. It includes no native Linux execution.
- The deliberate-hang supervisor regression observed and reaped its exact child
  after forced termination, and correctly rejected that outcome as native
  success. Failure, malformed and missing receipt cases also passed their
  refusal regressions. These observations do not validate protected supervision
  or guest tty restoration after a killed process.
- Repository Ruff and Mypy across **91 night-shift source files** pass.
  Linux-targeted Mypy of the two existing guest serial/TLS modules also passes.
  These source typing checks do not type-check the unannotated test harness or
  execute Linux syscalls.
- Both new Python files pass strict warning-as-error in-memory compilation and
  Python 3.12 grammar parsing. This is not execution on Python 3.12 or Linux.
- All four checkpoint source/document files pass trailing-whitespace and final
  newline checks; **11 local links** resolve; tracked `git diff --check` passes.
- `git diff --exit-code HEAD -- night_shifts runtime scripts` passes: production
  source, deployment and runtime assets remain unchanged. The combined suites
  include the existing in-memory actual-inspection-bundle exclusion regression.

No test/runtime source repair was needed. These are targeted checks, not an
all-repository test run. The verification-record edits themselves are
documentation-only; native Linux PTY results remain absent.

### What this closes, and what comes next

A successful Linux run would establish the disposable-PTY native serial
checkpoint only. The next transport evidence is the real guest TLS adapter over
native Linux tty I/O, followed by actual ttyS0 and authenticated Windows/guest
exchange in a reviewed fresh VM. The selected production credential-bootstrap
and protected media/runner/watchdog requirements remain in force; synthetic test
keys cannot substitute for that bootstrap. Preparation of the accepted protocol
image and the protected autonomous Gate A entry point remain separate blockers.

No elevation, Hyper-V operation, deployment, reload or commit is requested here.
Gate A remains unrun.

Related: [native Windows TLS evidence](night_shift_native_tls_validation.md),
[bounded Windows pipe I/O](night_shift_bounded_serial_io.md),
[credential/bootstrap design](night_shift_maintenance_credentials_design.md),
[Gate A preflight](night_shift_hyperv_preflight.md).
