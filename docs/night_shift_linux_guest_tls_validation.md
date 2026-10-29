# Native Linux guest TLS/serial validation candidate

## State and scope

**Applied and verified as a Windows-hosted portable test checkpoint. Native
Linux PTY/TLS execution remains unverified.** This follows the committed
[Linux serial validation harness](night_shift_linux_serial_validation.md)
at `1e42270` and the [guest serial/TLS source candidates](night_shift_guest_serial_candidate.md).
The new test module passes **37 portable tests with seven Linux-only skips**.
The combined ten-file transport selection passes **315 with 16 Linux-only
skips**, including the existing **20 native Windows cases**, warnings treated as
errors. Repository Ruff and Mypy across **91 night-shift source files** pass.
No test/runtime source repair was needed; the applied record below distinguishes
portable verification from the absent native Linux execution.

Before this batch, the committed Windows baseline passed **278 with nine
Linux-only skips**. Those historical results are not substituted for the new
applied results.

The immediate question is whether **the actual GuestTlsSerial adapter and actual
Linux SerialDevice I/O work together** over a newly owned tty. The earlier guest
TLS tests use a deterministic byte peer; the earlier Linux-native harness tests
serial I/O without TLS. This checkpoint joins those two paths in test code only.

No production module, public opening interface, service, installed worker,
protected helper, bundle inventory, credential bootstrap, VM or deployment is
changed. These are not runnable Gate A tasks or a new inspection dispatcher.

## Executable fixtures

- `tests/night_shifts/linux_tls_native_fixture.py` creates a new PTY and one exact
  spawn-process for the guest TLS endpoint. The parent drives a controller
  MemoryBIO endpoint through real nonblocking PTY-master I/O. There is no socket
  listener, existing serial device, fork, reader thread or nested child process.
- `tests/night_shifts/test_guest_bounded_tls_serial_linux.py` supplies the fixed
  native cases and portable framing, context and supervisor regressions. Native
  cases require Linux and explicitly skip on Windows. Portable results are not
  Linux or Hyper-V evidence.
- Only the child's private `SerialDevice.open` test seam is replaced. It returns
  a real `SerialDevice._open` using the prior `_PtyAPI`, which opens and validates
  the exact fresh PTY. All native tty configuration, claims, read/write, polling,
  deadline/cancellation and cleanup code remains real. `GuestTlsSerial` itself
  is not replaced and completes its actual handshake/message loops.
- The parent obtains the slave path and native device/inode identity from its
  own newly created pair; the child checks that identity before configuring it.
  The caller cannot choose an existing device through the fixture interface.
  The production `/dev/ttyS0` constant and 4:64 identity validator stay unchanged.
  A PTY is not relabeled or treated as a real UART.
- A test-only master driver records at most 128 KiB of ciphertext in each
  direction and emits actual short fragments in the fragmentation case. It is
  not a production host transport or replacement for the bounded Windows adapter.

## Fixed native scenarios

1. Pinned mutual TLS and two small, bound request/reply messages.
2. The same exchange with controller ciphertext emitted in 97-byte native writes.
3. A 30,000-byte payload spanning TLS records, then a second message under the
   original budget. Each exact received payload must match its synthetic input.
4. Wrong expected client-leaf pin at the actual guest adapter, despite a valid
   CA chain: refusal before application delivery.
5. Valid mutual TLS but mismatched VM binding: guest frame refusal and no
   application delivery.
6. Authenticated but silent controller: the guest's original session deadline
   expires during an actual native read/poll, with no delivered message.
7. Trusted cancellation set only after an actual post-authentication guest poll:
   terminal cancellation, not a modeled syscall or a pre-handshake refusal.

Each case requires the child's fixed-label finished receipt, explicit channel
release, no cleanup uncertainty, original slave termios restored, and **normal
exit of the exact guest process**. The parent independently reads back the
original tty attributes. Fixture teardown closes and checks only its own PTY
and control-pipe resources. Required forced termination fails the native case;
unconfirmed child exit is `fixture_tls_process_cleanup_unknown`, retaining the
exact process object rather than claiming success.

A random synthetic canary must not appear in the captured TLS data-PTY trace.
The payload and temporary certificate paths are also present in trusted local
process-startup configuration. The confidentiality assertion concerns the TLS
wire only, not every bootstrap/test-process channel. Receipts contain no payload,
byte trace, key, arbitrary native exception text or device/credential path.

## Credentials and report transport

The existing test fixture creates fresh temporary synthetic CA/client/server
credentials. The two test endpoints load only these explicitly supplied paths;
there is no production key discovery, certificate-store registration, key
provisioning, KVP or filesystem permission repair. These temporary files and
ordinary test processes do not establish production credential confinement or
secure erasure. Nothing here authorizes placing production private keys on media.

Contexts require TLS 1.3, strict mutual chain verification, exact peer pins,
server-name validation at the controller and no tickets/key logging. Binding
and sequencing use the existing inspection-only prototype. Synthetic binding
strings and pins are test inputs, not an accepted live bootstrap.

The child reports `ready` only after raw-mode setup, before the parent sends a
ClientHello. `authenticated` is emitted only after the real guest handshake.
Reports use an explicitly framed **nonblocking local byte pipe**: four-byte
length, at most 1024 ASCII JSON bytes, bounded incremental prefix/body I/O and at
most three fixed-schema records. Duplicate fields, excessive lengths, invalid
types and wrong phase order refuse. No `Connection.recv`, received pickle,
blocking partial-header wait or background reader is used. Multiprocessing's
trusted startup serialization still exists and is not an untrusted-data codec.

One ten-second parent budget spans startup observation, controller handshake,
serial traffic and report reads. The guest has one five-second session budget
(1.5 seconds for the explicit deadline case), never renewed per message. Local
child reporting has a separate original eight-second budget, allowing cleanup
status to be sent after serial expiry without reconnecting or retrying traffic.
After the test body, the parent waits two seconds for exact-child exit, then if
necessary terminates, waits two seconds, kills that exact child and waits two
seconds. Any required termination is a failed native case, not graceful cleanup.

These are cooperative native I/O and ordinary test-process bounds, **not a
protected watchdog**. Parent/runtime/provider failure can still strand work;
a shell/test timeout does not establish process or VM absence. No production
lifecycle guarantee is conferred, and no process-name or broad resource cleanup
is supplied. The portable supervisor cases exercise model process objects;
the earlier serial harness separately tests a real deliberately stalled child.

## Verification route and limits

Reproduce the applied Windows-hosted checks:

```text
python -W error -m pytest -q tests/night_shifts/test_guest_bounded_tls_serial_linux.py -rs
python -W error -m pytest -q tests/night_shifts/test_guest_bounded_tls_serial_linux.py tests/night_shifts/test_guest_serial_device_io_linux.py tests/night_shifts/test_guest_serial_device_io.py tests/night_shifts/test_guest_bounded_tls_serial.py tests/night_shifts/test_bounded_tls_pipe_windows.py tests/night_shifts/test_bounded_tls_pipe.py tests/night_shifts/test_serial_pipe_io.py tests/night_shifts/test_serial_pipe_io_windows.py tests/night_shifts/test_hyperv_serial_transport.py tests/night_shifts/test_maintenance_tls_prototype.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
git diff --check
```

On Windows all seven new Linux-native cases must skip. The portable tests cover
fixture framing, partial report reads/writes, report deadlines, schema limits,
strict synthetic contexts, phase ordering, non-Linux refusal and exact-process
cleanup decision logic. They cannot prove Linux ABI or tty behavior.

### Applied verification record

- New module: **37 passed, seven skipped in 0.32 seconds**, warnings treated as
  errors. All seven skipped cases require a native Linux disposable PTY/TLS
  environment. None is a native Linux success.
- Combined ten-file transport selection: **315 passed, 16 skipped in
  9.71 seconds**, warnings treated as errors and with no exclusions. This is the
  prior 278 passes plus 37 new portable regressions; the 16 skips are the nine
  serial-only and seven TLS/serial Linux-native cases. The existing **20 native
  Windows cases** still run and pass; they are not Linux evidence.
- The new portable supervisor regressions exercise model process objects for
  normal, forced and unknown exit; they do not launch a Linux guest peer.
  Portable report tests cover fragmented/incomplete framing, original deadlines,
  non-replayed partial writes, schema bounds, sequencing and sanitized failures.
  Synthetic context tests load only temporary test credentials.
- Repository Ruff, standard Mypy across **91 night-shift source files**, and
  Linux-targeted typing of the two existing guest modules pass. These typing
  checks do not type-check the unannotated fixture or execute Linux syscalls.
- Both new Python files pass strict warning-as-error in-memory compilation and
  Python 3.12 grammar parsing. This is not execution on Python 3.12 or Linux.
- All four checkpoint source/document files pass trailing-whitespace and final
  newline checks; **12 local links** resolve; tracked `git diff --check` passes.
- The actual **31-entry inspection ZIP**, built in memory only, excludes all
  tests and both unwired guest candidates. No deployment inventory is extended.
  `git diff --exit-code HEAD -- night_shifts runtime scripts` passes: production
  source, runtime and script assets remain unchanged.

No test/runtime source repair was needed. These are targeted checks, not the
all-repository suite. The verification-record changes are documentation-only;
no Linux-native fixture or actual guest peer ran in this checkpoint.

### Later Linux execution boundary

In a separately reviewed Linux environment with the existing test requirements
available, execute both native Linux modules. Record source commit,
platform/kernel, Python/OpenSSL and individual outcomes. Missing PTY/runtime
support is a failure, not permission to install packages, switch platform or
relax validation. No Linux environment, WSL instance, media or VM is selected or
started by this checkpoint. Both native Linux suites remain unexecuted here.

A successful Linux PTY/TLS run would close only this local guest-transport
checkpoint. Real Hyper-V ttyS0/device ownership, serial console/getty exclusion,
trusted live credential bootstrap, protected media/runner/watchdog, accepted
protocol image and authenticated Windows-to-VM exchange remain separate. The
next live step must use the reviewed fresh-VM route; this test seam is not a
production device-path option or an inspection security fallback.

No elevation, Hyper-V operation, service/network change, media authoring,
deployment, production credential access, reload or commit occurred in this
source batch. Gate A remains unrun.

Related: [Windows native authenticated transport](night_shift_native_tls_validation.md),
[controller adapter](night_shift_bounded_tls_pipe.md),
[credential/bootstrap design](night_shift_maintenance_credentials_design.md),
[Gate A preflight](night_shift_hyperv_preflight.md).
