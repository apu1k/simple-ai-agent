# Native host-store marker prototype — not a credential store deployment

This is the next isolated source/test draft after credential-model commit
`fbc4669`. It follows the [credential/bootstrap design](night_shift_maintenance_credentials_design.md).
It does not authorize elevation, protected anchor creation, permission repair,
real credentials, deployment, a VM operation, inspection or Gate A. Retained
V1/V2 objects, claims, media, receipts and plaintext rejection remain unchanged.

## Implemented draft boundary

`night_shifts/maintenance_store_native_prototype.py` exposes only
`probe_new_store(anchor_path, attempt_id)`. There is no private-key or arbitrary
payload parameter and no key factory. The only writable bytes are a fixed
`NON-SECRET` marker. There is no CLI, production caller or bundle integration.
The public function is intentionally not run as part of ordinary positive tests.

The proposed native flow is:

1. Validate a bounded ASCII local drive path before normalization. Reject UNC,
   device/extended paths, alternate streams, separators inside components, dot
   traversal, reserved device names and trailing dots/spaces. Require a lowercase
   32-hex probe identity. This identity is NOT an inspection claim/authorization.
2. Require enabled Administrators membership. This is a refusal guard, not an
   effective-access attestation or a sandbox against an administrator.
3. Open the fixed local NTFS volume root, deny delete sharing, and check that the
   handle resolves to an actual volume GUID root, not a substituted subdirectory.
4. Walk existing ancestors with single-component `NtCreateFile` operations
   relative to retained directory handles, with `OBJ_DONT_REPARSE` and
   `FILE_OPEN_REPARSE_POINT`. Never resolve a child by reopening its full path.
   Hold every directory without delete sharing for the entire probe.
5. Check native handle metadata and owner/DACL. Refuse reparse, sparse,
   compressed, encrypted/offline, non-disk, unexpected-kind or multi-link objects.
   Ancestor owners must be SYSTEM/Administrators. Ancestor untrusted ACEs cannot
   grant delete-child/delete, ACL/owner changes, generic write/all or write-EA/
   attributes. Read/execute and unrelated sibling creation can be allowed there.
   The existing anchor itself must meet the strict private-directory profile.
6. Atomically create a NEW `native-probe-<identity>` directory and `probe.bin`
   using `FILE_CREATE`, with an owner/protected DACL supplied in the initial
   native object attributes. Request Administrators ownership and exactly SYSTEM
   plus Administrators FullControl; directory ACEs inherit, leaf ACEs are explicit.
   Never create permissively and repair afterward. Existing objects refuse.
7. Re-read security and identity from the new handles before writing anything.
   The leaf uses share mode zero (no read/write/delete sharing for data/delete
   access). Windows can still allow metadata-only handles: sharing is not a
   substitute for a protected DACL or an effective-token confidentiality test.
   Revalidate the held ancestor chain and both new objects, write the fixed
   marker once, flush and
   read it back with a bounded read, then recheck identity/security/shape/size.
8. Close handles. Return only non-secret identities and marker length. A failure
   retains newly created objects, does not retry, does not relax sharing and does
   not delete evidence. Close failure is a failure, not confirmed successful
   cleanup. Only disposable pytest-owned objects receive normal fixture cleanup.

The directory profile is the existing strict ACL model applied to native
observations. The new creation descriptor requests Administrators ownership;
read-back accepts only the model's SYSTEM/Administrators ownership boundary.
Unsupported ACE types or unusual filesystem behavior refuse rather than guess.
Even directory-size drift is conservatively refused. The only ignored metadata
change is the non-security ARCHIVE bit. This prototype does not promise to work
on every existing Windows installation or choose a usable protected anchor.
In particular, an ancestor owned by an ordinary operator or TrustedInstaller
is not silently accepted, and no ACL/ownership repair is offered.

## Validation boundary

The corrected applied native-store suite passed **88 tests with 1 skip**.
A combined rerun with the TLS/credential suites passed **237 with 1 skip**;
this total includes the 88 native-store tests, not an additional 237 tests.
The native reparse fixture skipped because unelevated symlink creation was
unavailable; that native case remains unvalidated.

The initial run's **84 passed, 1 failed, 1 skipped** exposed a fixture mistake:
the alleged second reader requested metadata, which Windows permits despite
share mode zero. The applied correction tests native data read, write and
read/write opens (all blocked with error **32**) separately from allowed
metadata-only opens, always closing unexpected successful handles. Four earlier
disposable checks independently confirmed those semantics. Python's CRT-backed
`open` did not retain the numeric Win32 error in an exploratory check; the final
regression uses native `CreateFileW`. No runtime access policy was relaxed.

Other separate targeted runs passed: maintenance/guest/control/bundle suites
**122 with 1 skip**; runtime/pipe-security suites **81 with 2 skips**. Repository
Ruff and Mypy across **76 night-shift source files** passed after the correction,
as did whitespace/local-link, narrow marker-only API, source-import isolation
and actual in-memory inspection-bundle exclusion checks. These are targeted
results, not a full-repository suite; skips do not validate their cases. The
source/test batch is validated only within the fixture boundary below, not for
credential use or deployment. No bundle was written or installed and no
privileged helper/VM operation occurred.

The regression suite separates:

- Pure input/profile/metadata tests: expected strict security, dangerous ancestor
  grants, unexpected file type/links, identity/security/size drift and narrow
  marker-only API. These remain policy tests, not effective-token evidence.
- Mocked flow tests: success, changed anchor/store/leaf, unexpected nonempty
  leaf, broad DACL, collision and write error. These test sequencing and refusal,
  not Windows behavior, kernel cancellation or power-failure recovery.
- Disposable unelevated Windows fixtures: explicitly substitute current-user
  owner/DACL and private-profile verification; acquire a pytest-owned temporary
  parent directly, not through production ancestor acquisition. Exercise native
  relative create-new, supplied descriptor/read-back, marker write/read, collision
  preservation, data-access sharing refusal, metadata-only sharing semantics and
  multi-link refusal. A reparse fixture skips if ordinary symlink creation is
  unavailable. No VM token is acquired.
- An ordinary-token refusal test of the unchanged public entry point before it
  opens an anchor or creates objects; and a source-import isolation check.

A current-user fixture is **not** a positive test of Administrators ownership,
production anchor acquisition, SYSTEM access, filtered operator denial, exact-VM
or `VmWorkerProcess` restricted tokens, or a capability access result. Seeing a
named SID in a DACL is not native effective-token testing. No positive call to the
production public writer, protected path provisioning, impersonation, token
creation or privileged fixture is authorized by this source batch.

The module has no timing/cancellation adapter yet. Synchronous local filesystem
calls and cooperative checks do not establish a wall-clock ceiling. Any future
privileged validation or live worker must use the protected native watchdog;
a timeout does not establish that all host/VM resources stopped or secrets were
destroyed. Do not invoke this prototype through the elevated launcher yet.

## Key factory/runtime disposition

No host key-generation implementation is selected or enabled in this batch.
Python's `ssl` TLS APIs are not a certificate/key factory. The development-only
`cryptography==49.0.0` used by synthetic tests is not an approved deployed worker
runtime; this draft does not add it to production requirements or a bundle.
There is no automatic `pip`, download, OpenSSL executable discovery, certificate
store/container use, or hand-built low-level crypto wrapper fallback.

A later fixed factory must be reviewed with its exact implementation, certificate
profile/algorithms, full dependency and native-library provenance, protected import
paths, key lifecycle and error/logging behavior. It must consume the attested
new-file handle without a permissive temporary-key export, key in a command
argument, or model/tool-visible key output. Credential storage/loading and timeout
failure retention/destruction semantics need review together; do not add a key
bytes parameter to turn this marker probe into a live writer by implication.
Guest RAM-only generation and the public-only seed/KVP boundary remain separate.

## Remaining gates

Before generating any real host credential:

- Independently review and validate the native ABI, root/ancestor acquisition,
  collision, sharing and substitution/race refusal on disposable objects.
- Separately approve fresh protected anchor provisioning and trusted path/identity
  pinning. No existing workspace, general receipts or media path is a shortcut.
- Demonstrate actual production-owner creation and relevant effective-token access
  results in a separately approved, non-secret privileged fixture. Preserve the
  distinction between ordinary local tokens and restricted/capability VM tokens.
- Finish the pinned credential factory/runtime and handle-based loading lifecycle.
- Review administrator/hypervisor trust, crash/paging exposure, watchdog failure
  handling, audit receipts and retained-object/secret destruction policy. ACLs
  do not contain a malicious trusted administrator or prove memory erasure.

Then implement/review the Linux RAM-key publisher, independently exact-VM-bound
KVP acquisition/freshness and deadline/cancellation-safe serial adapters. None is
provided by this marker prototype. No plaintext downgrade, capability allowlist
expansion, permission repair or consumed-claim reset is proposed. A fresh approved
inspection, copy-only finalization, accepted image publication and the real Gate A
lifecycle/cleanup remain separate gates. Gate A/B remain blocked.
