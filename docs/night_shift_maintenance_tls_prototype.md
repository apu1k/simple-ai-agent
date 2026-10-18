# Offline maintenance TLS prototype — NOT a live inspection channel

This standalone prototype follows the [pipe security review](night_shift_pipe_security_review.md).
It does not change the plaintext allowlist, repair any ACL, provision live keys,
create media, connect a pipe/socket, start a VM, install code or consume/reset a
claim. There is no CLI or production integration. Gate A remains unrun.

## Scope and interface

`night_shifts/maintenance_tls_prototype.py` uses only the Python standard library
and OpenSSL through `ssl.SSLObject`/`MemoryBIO`. The caller explicitly moves
ciphertext between memory endpoints. It accepts trusted, already configured
`SSLContext` objects and explicit expected peer-certificate SHA-256 pins; it does
not discover files, load certificates from paths, establish their provenance or
attest their private-key protection.

`AttemptBinding` requires one canonical lowercase 32-hex attempt ID and one
canonical nonzero VM GUID. The operation is fixed to `inspect_image_copy`.
The guest role is the TLS server; the controller is the TLS client. The TLS server
name is the fixed non-network fixture name `night-shift-maintenance.invalid`.
SNI/hostname verification does not cause a network or DNS connection.

Each endpoint:

- Requires TLS 1.3, `CERT_REQUIRED`, strict X.509 validation, expected context
  role, controller hostname checking and an exact peer-leaf pin after handshake.
  Pinning does not replace CA/hostname validation.
- Rejects deferred client authentication, TLS ticket issuance/configuration,
  observed resumed sessions, known TLS key-log configuration and custom SNI
  callbacks. Contexts remain trusted inputs and must not be shared/mutated
  concurrently; this is not a sandbox against arbitrary Python/context code.
- Exposes `step`, `feed_ciphertext`, `take_ciphertext`, `queue_message` and
  `receive_message`, not any host/guest command dispatcher. Application messages
  cannot be queued or delivered before local authentication completes.
- Uses length-prefixed JSON envelopes with version, attempt ID, VM GUID, fixed
  operation, sender role, sequence and a JSON-object payload. Wrong identities,
  extra/missing fields, duplicate keys, non-finite numbers, invalid types and
  per-session replay/out-of-order sequences refuse the session.
- Has fixed 32 KiB serialized frame, 128 KiB pending ciphertext and cumulative
  handshake-input bounds, a 1,024-message per-direction limit, bounded JSON
  depth/node/aggregate-scalar work, and a single pending application write.
  JSON escaping is also checked against the final serialized frame-size limit.
- Treats malformed traffic, TLS errors, EOF/disconnect, cancellation, deadline
  expiry and security-setting changes as terminal. Fixed failure labels never
  include peer frames, IDs, certificate paths or provider exception strings.
  Once failed/closed, it cannot be reset/reconnected or drain partial output.

The payload is deliberately only a bounded JSON object in this prototype.
Acceptance of one authenticated payload is **not** image audit success, unmount,
VM cleanup, publication or job completion. A live implementation still needs the
full receipt schema and exact host/guest state transitions reviewed separately.

## Deadline boundary: checks are not preemption

A caller selects a cooperative budget in `(0, 900]` seconds with a trusted
monotonic clock and cancellation predicate. Checks surround provider operations,
serialization and frame delivery so a late return is not accepted as success.
`authenticated` is cached handshake/pin status, not a promise an operation's
remaining budget is positive; actual operations always check their budget.

OpenSSL calls execute synchronously in-process. The prototype cannot preempt a
hung provider or guarantee its process was killed by the deadline. It must never
be advertised as a replacement for the installed native watchdog or a hard VM
lifetime bound. Any later I/O adapter must propagate the same remaining budget,
be interruptible, and run beneath the separately reviewed protected watchdog.
Timeout/uncertain cleanup must still report VM outcome UNKNOWN.

## Replay and credentials remain separate prerequisites

TLS record replay and duplicate per-session envelope sequences are rejected.
This does **not** enforce global one-shot authorization across separately created
sessions. Fresh per-attempt credentials, permanent claims, exact deployment/code
bindings and explicit authorization must prevent cross-attempt/session reuse.
No permanent claim or protected policy is touched by this module.

The [offline credential/bootstrap candidate](night_shift_maintenance_credentials_design.md)
proposes private-key-free media and VM-bound public KVP metadata. Its codec and
ACL model are not native provenance, private-file creation or authorization, and
the Linux publisher/trusted host acquisition are not implemented.

Credential provisioning and effective ACLs are not solved here. Before a live
prototype can be considered, review who can read/replace the private key, recovery
media and trust pins, including `VmWorkerProcess` capability access and the host
administration trust boundary. If that secrecy/binding cannot be established,
stop: TLS over exposed credentials is not a private authenticated channel. There
is no TOFU, certificate-validation bypass, HMAC-only confidentiality claim,
plaintext downgrade, automatic ACL repair or transport fallback.

## Reproducible offline tests

`tests/night_shifts/test_maintenance_tls_prototype.py` generates fresh synthetic
EC certificates with the explicitly pinned **development-only**
`cryptography==49.0.0` dependency. The prototype module itself does not import that
package. No production dependency or installed helper bundle is changed.

Fixture CA/leaf private keys are written only into a temporary fixture directory
because `SSLContext.load_cert_chain` consumes files. They are generated at test
time, never committed, never used for a VM/production trust decision, and removed
at fixture teardown. Filesystem deletion is not secure erasure; these fixtures
are not evidence of Windows credential-ACL confinement. No certificate store,
real key, persistent production credential or provider API key is used.

The proposed tests cover real in-memory mutual TLS with fragmented encrypted
traffic; incorrect CA/hostname/expiry/role/pin; observation/tampering/TLS-record
replay; frame binding/schema/sequence rejection; bounded buffers/JSON; EOF;
backpressure; cooperative expiry/cancellation; late provider results; and insecure
context/key-logging refusal. Test-only raw SSL access models a malformed
*authenticated* peer; it does not add a raw-frame production API.

Run only the offline file after applying/reviewing the source and dependencies:

```text
python -m pytest -q tests/night_shifts/test_maintenance_tls_prototype.py
```

Before this source batch, a throwaway in-memory feasibility experiment passed
12 checks with OpenSSL TLS 1.3, CA/hostname checks and mutual leaf pins. Those
results are not results for this new module: the applied module/test file must
be run and checked separately. No Linux guest, Windows pipe adapter, Schannel
interoperability, credential provisioning, protected deployment or real VM
lifecycle evidence is claimed by either experiment.

### Applied prototype validation checkpoint

The applied prototype at commit `54ca6a9` passed its own **78 tests**, plus separate
related runtime/native **82 passed** and maintenance/guest/bundle **78 passed,
1 skipped**. Repository-wide Ruff and Mypy across 74 night-shift files passed.
Isolation checks found no existing production caller, and the actual generated
inspection bundle excluded both prototype and test-only crypto. The bundle was
constructed in memory, not installed or published. These are targeted offline
checks, not a full-repository run or any of the live guarantees listed below.
New credential/bootstrap source changes require their own validation.

## Remaining live boundary

The existing maintenance runner, guest payload, PowerShell scripts, bundle
allowlist, protected installations, grants and tools do not import or use this
prototype. Do not add it to a deployment bundle as a shortcut.

Before live use, separately review credential/media protection, deployed Linux
TLS availability, host/guest serial adapters, standard-library interoperability,
bounded cancellation/teardown and receipt semantics; explicitly disable/read back
automatic checkpoints on a fresh VM; package/install the pinned implementation
with a deployed 900-second protected execution policy; and obtain a fresh
inspection-only authorization/workspace/claim. Preserve V1/V2 and every retained
diagnostic resource. Successful inspection, copy-only finalization, accepted
publication and Gate A lifecycle/cleanup remain separate steps.
