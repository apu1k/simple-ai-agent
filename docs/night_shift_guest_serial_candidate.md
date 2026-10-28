# Guest bounded serial I/O and TLS-server candidate

## State and boundary

**Applied and verified as a Windows-hosted source/model checkpoint. Native Linux
serial behavior remains unverified.** Two unwired source modules are present:

- `night_shifts/guest/serial_device_io.py`: fixed Linux ttyS0 nonblocking byte I/O.
- `night_shifts/guest/bounded_tls_serial.py`: inspection-only mutual-TLS server
  and bound-message adapter over that byte channel.

The new guest suites pass **52 tests**. The combined eight-file transport
selection passes **254 tests**, including the prior **20 native Windows cases**,
with warnings treated as errors and no skips/exclusions. Repository Ruff, Mypy
across **91 source files**, and Linux-targeted typing of the two new modules pass.
No test or runtime source repair was needed after application.

The earlier committed baseline at `c6c2ab0` passed 202 related tests and Mypy
across 89 files. Those historical results are not substituted for the new
applied results. None of the new 52 tests is a native Linux execution claim.

This batch deliberately does not edit the installed plaintext protocol worker,
its service, existing maintenance runner, host connector, protected allowlists
or any deployment/media inventory. The new modules have no CLI, daemon entry,
key discovery, task interpreter or automatic activation. They remain excluded
from the actual inspection bundle. No live channel authorization is implied.

## Fixed device and Linux ABI

The public opening interface accepts only an existing trusted `IOBudget`, not a
device path or borrowed descriptor. Native calls are loaded after a Linux guard.
The fixed path is `/dev/ttyS0`, opened read/write with `O_NOCTTY`, `O_NONBLOCK`,
`O_CLOEXEC` and `O_NOFOLLOW`. The opened descriptor must identify a character
device with Linux major/minor **4:64**, be non-inheritable and remain nonblocking.
There is no symlink following, alternate device, automatic reopen or fallback.
If the target guest uses a different ABI/configuration, stop for review rather
than widening the accepted device identity automatically.

The candidate requests an advisory nonblocking exclusive flock and `TIOCEXCL`,
saves the original termios state, then configures/read-backs immediate raw
115200-baud 8N1 operation with `CREAD`/`CLOCAL`, no software/hardware flow control,
no canonical processing/echo/output transformations, `VMIN=1` and `VTIME=0`.
`TCSANOW` is used, not a flush/drain or `TCSAFLUSH`. Linux's baud bits may be
represented in cflag; the readback checks frame/control masks and both speeds.
VMIN=1 with nonblocking I/O avoids treating a zero-timeout/no-data read as EOF.

These settings are an **unverified native ABI implementation**, not evidence
that the actual guest accepts them. Flock is advisory, TIOCEXCL does not evict
pre-existing opens and privileged processes can bypass it. They do not prove
exclusive guest ownership, authenticate a peer, stop kernel console output or
disable a getty. Serial console/service ownership and native behavior still
require independent guest inspection before deployment. No such service changes
are performed by these modules.

## Deadline, cancellation and exact ownership

One authoritative budget covers open, validation, claim/configuration,
handshake, every poll slice and every message fragment. It is never renewed per
read/write or message. Read/write sizes match the host component's bounds:
64 KiB per native transfer and at most 4 MiB per `write_all` call. EAGAIN waits
for readiness in slices at most 50 ms; EINTR retries only under the same budget.
Partial writes advance by the actual byte count, never replaying prior bytes.
A late result is not returned after cancellation/deadline expiry.

One owning thread controls each session; wrong-owner and reentrant operations
refuse without tearing down another active operation. There is no background
reader, synchronous buffered-file adapter, unbounded flush or reconnect.
EOF is delivered to the TLS adapter as a terminal disconnect, never a reason to
switch to plaintext or retry a possibly delivered write.

The existing `IOBudget`, error base and size constants are reused from
`serial_pipe_io.py`. Importing these does not load a Win32 DLL or open a Windows
handle; the Linux candidate does not invoke the Windows native adapter. This is
source-level reuse, not an approved guest deployment dependency inventory.

## POSIX cleanup is intentionally different from Windows

Cleanup attempts immediate restoration of saved termios state, clearing the
owned TIOCEXCL claim, and exactly one close of the acquired descriptor. It is
attempted even after traffic expiry, with no expired-budget check blocking it.
All cleanup phases are attempted if a prior phase fails.

The fd is detached from the object **before** the close attempt. A POSIX/Linux
close can release the descriptor even when it reports an error; retrying the
number could close an unrelated subsequently opened resource. Therefore any
restore/release/close failure is terminal `SerialCleanupUnknown` with fixed
label `cleanup_unknown`. Repeated close only reports that uncertainty; it never
retries the detached descriptor. This differs from exact-OVERLAPPED completion
re-observation in the Windows component. No automatic repair or new attempt is
authorized by either exception.

No asynchronous kernel buffer is submitted by this POSIX implementation, so
there is no Windows-style pending-buffer quarantine. Uncertain tty restoration
or release is still not success. Native tty open/configuration/poll/close,
OpenSSL, trusted callbacks or the Python runtime can hang inside a provider call.
These cooperative bounds are **not** a protected process-lifetime guarantee.
An independent protected watchdog and VM/disk observations remain necessary.

## TLS server interface

`GuestTlsSerial(context, binding, peer_sha256=..., timeout_seconds=...)` opens
the fixed serial device and finishes the TLS-server handshake before returning.
It exposes only `send_message`, `receive_message`, context-manager support and
explicit same-owner `close`. The operation stays fixed to **inspect_image_copy**;
there is no Gate A protocol-task dispatcher or arbitrary guest command.

Trusted callers must supply a correctly configured server SSLContext, exact
expected controller leaf pin and trusted attempt/VM binding. The existing
prototype enforces TLS 1.3, strict mutual certificate validation, peer pinning,
no tickets/resumption/key logging and bounded sequenced JSON envelopes. Pins do
not replace CA validation or establish the provenance/secrecy of their keys.
The host TLS adapter remains unchanged by this batch.

No key is generated or loaded by the guest adapter. Production credential
creation/protection, guest RAM-key lifetime, authenticated bootstrap, Linux
OpenSSL availability and protected code/media binding remain separate blockers.
The unfinished KVP/confinement requirements on the selected bootstrap route are
not waived by providing a serial I/O implementation.

## Verification scope

`test_guest_serial_device_io.py` models native syscall order, fixed open flags,
device identity/flags, raw-mode intent/readback, configuration failures, bounded
polling, EAGAIN/EINTR, partial writes, cancellation, late completion, cleanup
uncertainty and owner/reentry refusal. Native-ABI views are synthetic test inputs,
not evidence that Linux applied the requested settings.

`test_guest_bounded_tls_serial.py` uses real OpenSSL MemoryBIO TLS against a
**deterministic byte peer**, reversing the roles of the existing fixture. It
covers mutual authentication, fragmented/multi-record traffic, message binding,
one cumulative budget, refusal/error/EOF behavior, no write replay and POSIX
cleanup-uncertainty propagation. Existing temporary synthetic certificate
fixtures are reused; there are no production keys or certificate-store changes.
An actual in-memory inspection ZIP exclusion assertion covers both modules.

Reproduce the applied checks with the new selection, then the combined
transport selection:

```text
python -W error -m pytest -q tests/night_shifts/test_guest_serial_device_io.py tests/night_shifts/test_guest_bounded_tls_serial.py
python -W error -m pytest -q tests/night_shifts/test_guest_serial_device_io.py tests/night_shifts/test_guest_bounded_tls_serial.py tests/night_shifts/test_bounded_tls_pipe_windows.py tests/night_shifts/test_bounded_tls_pipe.py tests/night_shifts/test_serial_pipe_io.py tests/night_shifts/test_serial_pipe_io_windows.py tests/night_shifts/test_hyperv_serial_transport.py tests/night_shifts/test_maintenance_tls_prototype.py
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/guest/serial_device_io.py night_shifts/guest/bounded_tls_serial.py --follow-imports=silent --platform linux
git diff --check
```

### Applied verification record

- New guest serial/TLS suites: **52 passed in 0.42 seconds**, warnings treated as
  errors, with no skips/exclusions. These are deterministic ABI/ownership models
  and real MemoryBIO TLS against a modeled byte channel, not native Linux I/O.
- Combined eight-file transport selection: **254 passed in 7.78 seconds**,
  warnings treated as errors, no skips/exclusions. The **20 native Windows
  cases** come from the existing host suites; they are not guest-native passes.
- Repository Ruff and Mypy across **91 night-shift source files** pass.
  Linux-targeted Mypy of both new guest modules also passes. Typing is not
  execution on Linux or evidence of termios/device behavior.
- Strict in-memory compilation, Python 3.12 grammar and whitespace checks pass
  for both new modules and both new test files. This is not execution on
  Python 3.12.
- Ten local links across this document and the native Windows validation record,
  documentation whitespace and tracked `git diff --check` pass.
- The actual **31-entry inspection ZIP**, built only in memory, excludes both
  guest candidates. No existing night-shift source imports them. Existing
  tracked `night_shifts`, `runtime` and `scripts` assets are unchanged from HEAD;
  only the two new unwired modules are added to the source tree.

No source correction was needed. These targeted passes do not constitute an
all-repository test run, native Linux validation, `/dev/ttyS0` runtime
compatibility, protected deployment or authenticated real-VM evidence.

## Next boundary

After source verification, independently validate Linux device identity, tty
ownership/configuration, bounded native I/O and authenticated guest/host exchange
in a separately approved Linux environment. Do not add candidates to a protected
bundle or activate them as a shortcut. Native validation still needs reviewed
media/runner/watchdog scope, trusted credential bootstrap and evidence handling.
Image acceptance and the exact-owned autonomous Gate A runner remain separate.

No elevation, VM operation, policy loading, service/network change, media
writing, deployment, production credential access, reload or commit is part of
this source batch. Gate A remains unrun.

Related: [Windows native TLS evidence](night_shift_native_tls_validation.md),
[controller adapter](night_shift_bounded_tls_pipe.md),
[bounded host I/O](night_shift_bounded_serial_io.md),
[credential design](night_shift_maintenance_credentials_design.md),
[Gate A preflight](night_shift_hyperv_preflight.md).
