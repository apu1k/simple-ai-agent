# Bounded Windows serial byte-pipe I/O candidate

## State and scope

`night_shifts/serial_pipe_io.py` is an applied, **unwired** native I/O component
for modern Windows. The seven disposable Windows named-pipe tests pass, including
native stalled-read/write cancellation and exact-handle cleanup. These are local
I/O observations, not Hyper-V channel trust or Gate A. The test-ID repair is
applied; the complete four-file selection passes **161 tests with no exclusions
or skips**, including all seven native cases. A declaration-only typing adjustment
is described below; applied source changes always require normal re-verification.

It does not change `backends/hyperv_serial.py`, its connector, production imports,
protected bundles, inspection claims, pipe policy or any existing guest payload.
It performs no Hyper-V, VM, service, networking, media or credential operation.
It is not authentication, an accepted image, a protected watchdog or Gate A.
Existing plaintext maintenance refusal remains unchanged; do not point this
candidate at a VM as a shortcut around that check.

## Implemented interface

- `IOBudget(timeout_seconds, cancelled=...)`: one trusted monotonic deadline,
  maximum 900 seconds, shared by connection and every read/write fragment. A
  deadline/cancellation callback is trusted application code, not peer input.
- `BoundedPipe.connect(path, budget)`: only the local canonical
  `\\.\pipe\night-shift-<32 lowercase hexadecimal characters>-com1` form.
  Missing/busy endpoints retry under the same budget; access denial and other
  failures are terminal. A path shape is **not** authenticated endpoint identity.
- `read(size)`: at most 64 KiB; a short read is valid, empty bytes mean EOF.
- `write_all(data)`: at most 4 MiB per call, chunked into at most 64 KiB native
  operations, handling short writes without replaying already written bytes.
- Context-manager support and explicit same-owner `close()`; no background
  thread, destructor cleanup, automatic reconnect, retry of failed traffic or
  transport fallback. Callers must close in `finally` or use the context manager.

There is intentionally no `BinaryIO` adapter and no flush operation. The handle
is unbuffered; `FlushFileBuffers` can wait for the peer and is not a safe substitute
for a bounded write. No existing serial caller is switched to this interface.
Future TLS integration must use this remaining budget, not restart a budget per
record or silently continue through the existing synchronous connector.

## Native I/O and ownership

The client opens a non-inheritable handle using `FILE_FLAG_OVERLAPPED`, exact
read/write-data access bits (not generic write/pipe-instance creation), and
identification-level security quality of service. These choices limit the
client's requested rights/impersonation exposure; they do not set, fix or attest
the server DACL, server process, intended guest or credential secrecy.

Each operation owns a dedicated manual-reset event, `OVERLAPPED` and stable
buffer. `ReadFile`/`WriteFile` submit asynchronous I/O; non-waiting
`GetOverlappedResult` observations supply actual completion counts. No stack-local
byte-count output is passed to asynchronous submission. One thread owns the
session, with no concurrent/reentrant read/write/close and no shared-handle clone.
The production caller and all injected clocks/native adapters remain trusted.

On deadline/cancellation/error, the session becomes unusable. The component
calls `CancelIoEx` for the **exact owned OVERLAPPED**, then observes completion
before freeing kernel-visible memory. Successful cancellation and
`ERROR_NOT_FOUND` are not by themselves completion evidence. A successful
completion racing cancellation is also a terminal observation, not permission
to deliver a result after the session deadline.

Cleanup has a separate drain allowance: default 2 seconds, configurable up to 5.
If completion or handle release cannot be confirmed, it raises
`PipeCleanupUnknown` with fixed text `cleanup_unknown`, retaining the channel,
buffer, event and handle in a strong-reference quarantine. It does not claim
resources are gone, free potentially live memory, reuse the session, or silently
retry cleanup. The exception's `.channel` allows an explicit same-owner
`close()` to re-observe/release those exact resources later. This does not
reauthorize traffic, a VM operation or a new inspection attempt. Log only fixed
labels, never buffers or exception-attached channel internals.

Cancellation cannot undo bytes the peer may already have received. A timed-out
write must not be replayed automatically. An EOF is returned to the framing layer;
that future layer must treat premature EOF as terminal and close the session.

### Boundaries of the bound

Polling/deadline checks do not preempt a hung native/provider call, trusted
callback or Python runtime. A late observed result is rejected, but this module
is **not a hard process-lifetime guarantee**. Cleanup time is additional to the
session budget. It cannot stop a VM or establish VM removal. The separately
protected host watchdog and independent VM/disk observations remain required for
autonomous live use. Unknown resources must never be reported as a passed gate.

## Applied verification

- Native Windows fixture suite: **7 passed in 0.85 seconds**, warnings as errors,
  on Windows/Python 3.14.3. Silent read and write-backpressure cases each took
  approximately 0.30 seconds; absent endpoint approximately 0.10 seconds. Exact
  client/server handle and pending-request release checks passed; read fixtures
  also observed native peer disconnect. These are observations from this host,
  not a hard provider/process lifetime guarantee or VM cleanup evidence.
- Complete four-file selection after the applied test-ID repair: **161 passed in
  1.61 seconds**, warnings as errors, with no exclusions or skips. This includes
  **71 model/fault cases, 7 native Windows cases and 83 existing serial/TLS
  regressions**. The oversized-input test body now executes normally.
- Historical partial run: 157 passed, 4 deselected. The earlier complete run
  failed at oversized-case setup/teardown because pytest put the 4 MiB bytes
  parameter into `PYTEST_CURRENT_TEST`, exceeding Windows' environment-variable
  length limit. Four short explicit IDs fix only test naming; inputs, assertions,
  I/O behavior and security policy remain unchanged.
- Repository Ruff and Mypy across **88 night-shift source files** pass.
- In-memory strict compilation/Python 3.12 grammar and whitespace pass for all
  three new Python files. This is not execution on Python 3.12 or Linux.
- The actual in-memory **31-entry inspection ZIP** and public support inventory
  exclude the candidate; no existing night-shift source imports it. Three local
  links and tracked whitespace checks pass. No media or deployment ZIP was written.

The complete non-Hyper-V verification command is:

```text
python -W error -m pytest -q tests/night_shifts/test_serial_pipe_io.py tests/night_shifts/test_serial_pipe_io_windows.py tests/night_shifts/test_hyperv_serial_transport.py tests/night_shifts/test_maintenance_tls_prototype.py
```

The model tests cover malformed input, finite budgets, fixed failures, partial
transfers, cumulative deadline, late completion, cancellation races, ownership,
reentrancy, retained memory on uncertainty and explicit exact-resource release.
The native Windows fixtures use a random first-instance local byte pipe with an
explicit current-user-only DACL, synthetic non-secret bytes, and no worker
thread. They exercise fragmented round trips, EOF, absent endpoint, silent-read
and write-backpressure deadlines, and cancellation after actual submission.
Non-Windows fixture skips are not native passes. Fixture observations do not
attest Hyper-V's actual ACLs, guest identity, TLS deployment or image readiness.

An additional Linux-targeted Mypy check exposed eight missing inferred attribute
types because the native constructor's Windows-only branch is unreachable to
that checker. Explicit class-scope declarations of the existing dynamic ctypes
bindings address this without changing calls, signatures, platform refusal or
runtime behavior. The declaration-only candidate passed in-memory Windows/Linux
Mypy, Ruff and compilation; this is not applied-file or Linux execution evidence.
Repeat the normal tests/type/lint checks after any applied source change.

No native helper is loaded in ordinary fake tests; no production caller,
plaintext ACL allowlist or guest payload is changed. No elevation, Hyper-V/VM,
service/network change, media authoring, deployment, reload or commit occurred.

## Next boundary

The committed component has now been rechecked after its declaration-only typing
adjustment: the complete selection passes **161 tests**, including all seven
native Windows cases, with repository Ruff and Mypy across **88 night-shift
source files** passing. This is not Linux execution or live channel evidence.

The follow-on [bounded controller TLS adapter](night_shift_bounded_tls_pipe.md)
is applied as a separate source checkpoint. It uses this pipe component beneath
the existing inspection-only TLS prototype; it does not switch the production
connector or any protected payload. The combined applied selection passes
**193 tests**, including all **11 native Windows cases**, and Mypy across
**89 source files** passes. The two test-only Ruff callback-style errors were
corrected and the applied files passed the complete runtime/lint selection
before commit `0907c0d`; no runtime repair was needed. See the adapter record for
scope and limits. The 161-test historical baseline is not evidence for the
adapter itself.

The separate [native authenticated round-trip checkpoint](night_shift_native_tls_validation.md)
is now applied and verified: **9 native Windows tests passed**, and the combined
six-file selection passed **202 tests**, including **20 native Windows cases**,
with no skips/exclusions and warnings treated as errors. Repository Ruff and
Mypy across **89 source files** pass. Exact test-peer exits and pipe resources
were checked; no source repair was needed. This adds real local TLS round-trip
evidence, not Linux/Hyper-V operation, production credential trust or VM cleanup.

Actual trusted credential/bootstrap provisioning (including the remaining
confinement validation on the selected KVP route), guest-side serial I/O, native
end-to-end channel evidence, image acceptance, protected deployment and an
exact-owned Gate A runner with an independent watchdog are still outstanding.
There is no plaintext downgrade, ACL widening, live VM approval or route switch.

Related: [pipe security review](night_shift_pipe_security_review.md),
[TLS prototype](night_shift_maintenance_tls_prototype.md),
[Gate A preflight](night_shift_hyperv_preflight.md).
