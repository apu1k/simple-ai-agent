# Bounded controller TLS/pipe adapter candidate

## State and purpose

Source checkpoint toward an autonomous Gate A, **not a Gate A runner or live
channel authorization**. `night_shifts/bounded_tls_pipe.py` joins the existing
inspection-only mutual-TLS/framing prototype to the bounded Windows pipe client.
The existing production serial connector, plaintext maintenance refusal,
protected installations, deployment allowlist and guest payload are unchanged.

The initial applied verification passes **193 tests with no skips or exclusions**,
including the adapter, TLS receive-loop change and **11 native Windows cases**.
Mypy across **89 night-shift source files** and the three-component Linux-targeted
typing check pass. Repository Ruff found two test-only E731 style errors; a
narrow named-callback correction passes Ruff and compilation in memory. Repeat
applied-file lint/tests after that correction before committing; no runtime
source repair was identified by these checks.

The earlier committed four-file serial/TLS baseline passed 161 tests, including
seven native Windows pipe cases, with repository Ruff and Mypy across 88 files.
Those historical baseline results are not substituted for the new results.

## Interface and ownership

`BoundedTlsPipe(path, context, binding, peer_sha256=..., timeout_seconds=...)`
opens and authenticates during construction. A controller is the TLS client; the
existing guest endpoint is the TLS server. Use a context manager or `finally`
with explicit `close()`. There is no automatic reconnect, destructor, hidden
worker thread, flush, raw plaintext API or transport fallback.

- `send_message(payload)` accepts the existing bounded JSON-object frame.
- `receive_message()` returns one authenticated and attempt-bound payload.
- The existing operation remains fixed to **`inspect_image_copy`**. This does
  not add a Gate A protocol dispatcher or authorize a new guest operation.
- The caller must supply trusted contexts, exact peer-leaf pins and attempt/VM
  identity. TLS 1.3, strict CA/hostname verification and mutual authentication
  are still enforced by `OfflineTlsEndpoint`; a pin cannot bypass CA validation.
- The adapter does not generate, discover, load, protect or provision production
  keys or trust pins. No TOFU, certificate-store change or bootstrap is added.
- The native connector still accepts only its canonical local pipe path. Path
  shape is not authentication, and this module does not attest or repair the
  Hyper-V pipe DACL or the server's identity before TLS.

One owning thread performs one operation at a time. Wrong-owner and reentrant
calls refuse without closing another operation's resources. No thread is used
to disguise an uninterruptible synchronous read.

## One session deadline, terminal failures

One authoritative `IOBudget` starts **before** opening the pipe. The exact same
budget object is passed to `BoundedPipe.connect` and remains in force across
handshake, encrypted fragments and every application message. It is never reset
per record, message or send/receive call. Endpoint-local defensive checks use the
same trusted clock/cancellation predicate and cannot extend the outer deadline.
Late native/provider results are rejected before an application result returns.

Every ciphertext write uses `write_all`, so partial native writes do not replay
already-written bytes. A failed write is terminal even if the peer may have
received some or all of it; this adapter never resends it or reconnects. EOF,
malformed input, authentication failure, cancellation and expiry close both
layers. Known failures retain fixed labels; unexpected ordinary operation errors
become `channel_failure` without exposing provider text or peer payloads.

`OfflineTlsEndpoint.receive_message` now drains already-buffered TLS records
until it has one frame or TLS actually needs transport progress. A large frame
can span multiple records: returning after one successful decrypt would make a
pipe adapter wait unnecessarily for bytes already available inside TLS. Existing
frame/buffer/message bounds, sequencing and per-iteration budget checks remain.

Cleanup is independent of the expired traffic budget. It uses the native pipe's
separate cancellation/completion-drain allowance. `PipeCleanupUnknown` takes
precedence over traffic failure, retains the exact underlying channel, and is
**not** implicitly retried by the adapter. An explicit same-owner `close()` may
re-observe those resources; it cannot resume traffic or authorize a VM action.

These are cooperative/provider-call boundaries, not hard process preemption.
OpenSSL, a native provider or trusted callback can still hang inside a call.
The separately protected watchdog and independent VM/disk cleanup observations
remain necessary for autonomous live work. Closing a pipe never proves a guest
stopped or a VM/disk was removed.

## Validation scope

`tests/night_shifts/test_bounded_tls_pipe.py` reuses the existing fresh synthetic
certificate fixtures. Temporary test keys are not production credentials or
native credential-ACL evidence. Real OpenSSL TLS is exercised against a
**deterministic byte-peer model** for fragmented exchange, buffered multi-record
and multi-frame input, a cumulative budget, late completion, cancellation,
wrong pins, insecure configuration, plaintext/EOF refusal, non-replayed writes,
cleanup uncertainty, owner/reentry checks and interruption.

Four separate **native Windows named-pipe failure-path fixtures** exercise a
silent handshake, cancellation after a read submission, plaintext refusal and
disconnect. They check exact client handle/pending-operation release. These are
local current-user-only pipe fixtures, not Hyper-V ACL evidence, a complete
native authenticated round trip, guest execution or VM cleanup evidence.
Non-Windows skips are not native passes. An in-memory ZIP check verifies that
the adapter, pipe component and TLS prototype remain absent from the actual
inspection deployment bundle; no ZIP or media is published.

The complete runtime selection was run with warnings treated as errors; repeat
the checks after applying the test-only lint correction:

```text
python -W error -m pytest -q tests/night_shifts/test_bounded_tls_pipe.py tests/night_shifts/test_serial_pipe_io.py tests/night_shifts/test_serial_pipe_io_windows.py tests/night_shifts/test_hyperv_serial_transport.py tests/night_shifts/test_maintenance_tls_prototype.py
ruff check .
mypy night_shifts --follow-imports=silent
git diff --check
```

### Initial applied verification record

- Complete five-file runtime selection: **193 passed in 2.54 seconds**, with
  warnings treated as errors and no skips/exclusions. This includes **32 new
  cases** (four native Windows handshake-failure cases) and the 161 prior
  serial/TLS cases (seven native Windows pipe cases).
- Windows/default Mypy: **89 source files passed**. Explicit Linux-targeted Mypy
  of `serial_pipe_io.py`, `bounded_tls_pipe.py` and
  `maintenance_tls_prototype.py`: **three files passed**. This is not execution
  on Linux or native guest evidence.
- Strict in-memory compilation and Python 3.12 grammar checks for the three
  changed/new Python files pass; this is not execution on Python 3.12.
- Eight local documentation links, changed Python whitespace and tracked
  `git diff --check` pass. The bundle-exclusion test in the runtime selection
  builds the actual inspection ZIP in memory only and passes.
- Repository Ruff initially found two E731 assigned-lambda errors in test
  callbacks. Replacing just those assignments with named functions passes
  in-memory Ruff, compilation and grammar checks, without changing inputs,
  assertions or runtime source. The applied correction must pass the complete
  runtime/lint selection before this checkpoint is called ready to commit.

No complete native authenticated round trip or successful VM/TLS exchange is
claimed. Native observations cover local failure-path I/O and resource release,
not production Hyper-V pipe trust, credential protection or VM cleanup.

## Remaining route to autonomous Gate A

This closes an adapter implementation boundary, not the entire trust bootstrap.
Still required: complete native host/guest channel evidence, the guest-side
bounded serial adapter and trusted per-attempt credential bootstrap; acceptance
of a cleaned/frozen protocol-test image; and the protected exact-owned Gate A
entry point with independent watchdog and cleanup evidence. The remaining KVP
confinement prerequisites on the selected bootstrap route are not waived.

No production caller or protected bundle should be switched to this candidate
as a shortcut. No elevation, Hyper-V/VM, service/network change, media authoring,
production credential access, deployment, commit or application reload is part
of this source batch.

Related: [bounded native I/O](night_shift_bounded_serial_io.md),
[TLS prototype](night_shift_maintenance_tls_prototype.md),
[pipe security review](night_shift_pipe_security_review.md),
[Gate A preflight](night_shift_hyperv_preflight.md).
