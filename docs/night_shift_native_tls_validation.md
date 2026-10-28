# Native Windows authenticated TLS validation checkpoint

## State

**Applied and verified on this Windows host.**
`tests/night_shifts/test_bounded_tls_pipe_windows.py` is a test-only follow-on to
commit `0907c0d` (bounded authenticated TLS pipe adapter). Its **nine native cases
pass**, and the combined six-file selection passes **202 tests with no skips or
exclusions**, warnings treated as errors. Repository Ruff and Mypy across
**89 source files** pass. No test or runtime source repair was needed.

The earlier committed baseline passed 193 tests; the new nine-case native suite
is covered by the separate and combined applied runs recorded below.

The immediate question is whether the actual host adapter can complete pinned
mutual TLS and bound message exchange over real Windows named-pipe I/O, rather
than only against a deterministic byte-peer model. No runtime, guest, production
connector, deployment bundle, trust policy or protected installation changes.

## Validated cases

All nine native Windows cases pass:

1. Small authenticated two-message exchange.
2. The same exchange with server ciphertext fragmented into 97-byte writes.
3. A 30,000-byte body spanning TLS records, followed by a second message under
   the same connection/budget.
4. Wrong expected client leaf pin at the peer, despite a valid CA chain.
5. Wrong expected server leaf pin at the controller, despite a valid CA chain.
6. Valid mutual TLS but a mismatched VM binding: no application delivery.
7. An incomplete application frame sent in a valid TLS record, followed by
   disconnect: no partial application payload is returned. This is not a claim
   that every queued ciphertext byte survives a server close.
8. An authenticated but silent peer: the original session deadline still applies.
9. Cancellation after an actual native read submission on an authenticated pipe.

The tests call the actual `BoundedTlsPipe` constructor and connector; no fake
connector, synchronous-file fallback, ACL relaxation or certificate bypass is
introduced. The cancellation case instruments only the exact native client's
submission method and sets a trusted cancellation flag after submission.

## Peer process and evidence boundaries

A separate Python **spawn-process** owns the native server pipe, TLS endpoint,
OVERLAPPED requests and buffers. It serves only fixed synthetic test scenarios;
it is not a production Linux adapter, guest supervisor or command dispatcher.
The pipe name is freshly random and first-instance-only. Its DACL explicitly
allows the current user, the handle is non-inheritable, and remote clients are
refused. These fixtures do not establish Hyper-V's actual pipe DACL or identity.

The existing fixture generates temporary synthetic CA/client/server credentials.
The child loads only those fixture certificate/key paths. Neither certificate
stores nor production credential paths are discovered or accessed. Temporary
key deletion is not secure erasure or evidence of production key confinement.
Synthetic payloads also travel through trusted process bootstrap configuration;
the confidentiality assertion applies to captured **TLS data-pipe ciphertext**,
not every local process/bootstrap channel.

The child uses a ten-second I/O budget, overlapped accept/read/write and the
existing exact-request cancellation drain. Its bounded receipts report fixed
failure labels, local authentication, validated-message count, owned-resource
release, peer-observed native EOF, ciphertext fragment count and a plaintext
canary visibility flag. Receipts never include keys, payloads or ciphertext.
The controller receives length-bounded JSON bytes, not deserialized peer pickle.
Spawn configuration itself is trusted local test input.

Successful exchanges require client handle/request release, native EOF observed
by the server, server handle/request release, and confirmed normal child exit.
The fixture joins the **exact spawned process**. If necessary, it terminates that
process once and observes exit; requiring termination fails the fixture rather
than counting as successful graceful cleanup. An unconfirmed exit is explicitly
`fixture_peer_cleanup_unknown`, never a pass. There is no process-name search,
broad cleanup, background reader thread or reusable shared server.

These are test-harness bounds and observations, not a protected live watchdog.
A provider/runtime call can still hang, a parent crash is not made safe by a
Python `finally`, and a shell/test timeout does not prove the peer exited.
Nothing in this checkpoint can stop or clean up a VM. Native non-Windows skips
must not be reported as passes.

## Reproducible validation

The new suite was run first with warnings treated as errors:

```text
python -W error -m pytest -q tests/night_shifts/test_bounded_tls_pipe_windows.py
```

Then the full related selection:

```text
python -W error -m pytest -q tests/night_shifts/test_bounded_tls_pipe_windows.py tests/night_shifts/test_bounded_tls_pipe.py tests/night_shifts/test_serial_pipe_io.py tests/night_shifts/test_serial_pipe_io_windows.py tests/night_shifts/test_hyperv_serial_transport.py tests/night_shifts/test_maintenance_tls_prototype.py
ruff check .
mypy night_shifts --follow-imports=silent
git diff --check
```

### Applied verification record

- New native Windows suite: **9 passed in 5.45 seconds**; no skips or exclusions.
- Combined six-file serial/TLS selection: **202 passed in 7.63 seconds**, warnings
  treated as errors, no skips/exclusions. This includes **20 native Windows
  cases**: the new nine and the prior eleven. The remaining cases are existing
  deterministic model, framing, TLS and protocol regressions.
- Each tested peer exited normally and was reaped; forced termination would
  fail fixture teardown. Successful exchanges also checked native peer EOF and
  exact client/server handle and pending-operation release. These observations
  are limited to the fixed test processes/resources, not VM cleanup.
- Repository Ruff and Mypy across **89 night-shift source files** pass.
- Strict in-memory compilation, Python 3.12 grammar and whitespace checks pass
  for the new test file. This is not execution on Python 3.12 or Linux.
- Fourteen local links across the three checkpoint documents and documentation
  whitespace pass; tracked `git diff --check` passes.
- The existing actual-inspection-ZIP exclusion test passes in the combined
  selection; the ZIP is constructed in memory only. Tracked `night_shifts`,
  `runtime` and `scripts` production assets are unchanged from HEAD.

No source repair was required after application. These are targeted suites, not
an all-repository test run or protected deployment validation.

## What passing establishes and what remains

This closes the **local native authenticated round-trip checkpoint** for the
controller adapter and fixed test peer on this host. It does not establish Linux
`/dev/ttyS0` behavior, deployed TLS availability, trusted credential bootstrap,
image acceptance, Hyper-V pipe security, guest confinement or VM cleanup.

The follow-on [guest bounded serial/TLS candidate](night_shift_guest_serial_candidate.md)
is now applied and verified as a separate unwired source/model checkpoint. It
supplies fixed Linux ttyS0 byte I/O and the inspection-only TLS-server adapter,
not a service, live bootstrap or deployed guest dispatcher. Its **52 new
model/MemoryBIO tests pass**; the combined eight-file transport selection passes
**254 tests**, including the existing **20 native Windows cases**, with no
skips/exclusions and warnings treated as errors. Repository Ruff, Mypy across
**91 source files**, and Linux-targeted typing of the two guest modules pass.
No source repair was needed. Native Linux device/configuration and authenticated
real host/guest interoperability remain unverified; none of the new model tests
is a native Linux pass.

Per-attempt credential/bootstrap prerequisites are not bypassed. The protected
exact-owned runner and independent watchdog remain necessary for an autonomous
Gate A operation. Gate A itself remains unrun.

No elevation, Hyper-V/VM, service/network change, media authoring, production
credential access, deployment, application reload or commit is part of this
source/test batch.

Related: [controller adapter](night_shift_bounded_tls_pipe.md),
[bounded native I/O](night_shift_bounded_serial_io.md),
[pipe security review](night_shift_pipe_security_review.md),
[Gate A preflight](night_shift_hyperv_preflight.md).
