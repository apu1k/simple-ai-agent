# Fixed guest-only native validator — design and first source component

## Current checkpoint and authority

The operator is back at the local desktop. The Flex checkpoint is committed as
`a7c717c`; recovery handoff/confinement preparation is committed as `fad3832`.
The working tree was clean at the start of this checkpoint. Earlier documents'
remote/no-commit restrictions describe that historical session, not a current
requirement to remain remote. Local access/elevation availability does **not**
authorize policy loading, protected deployment, media authoring or a VM start.
Gate A remains unrun. The applied audit-correlation checkpoint below is now
committed as `8a83d8a`. The next [fixed fixture/worker source review](night_shift_native_worker_review.md)
proposes an inert in-memory ELF, an unwired guest-only worker and a concrete
supervisor/pipe protocol. Those new proposals require post-application checks;
they do not activate a guest or supply a runnable native supervisor.

Before application, the committed ten-file targeted baseline passed **548 with
2 skips in 5.00 seconds**. The new component is now applied and verified offline:
**93 format tests pass in 0.35 seconds**. The combined eleven-file related selection
passes **641 with 2 skips in 4.58 seconds**, INCLUDING those 93 and the earlier
548 checks, warnings as errors and without temporary hooks/source substitution.
Repository Ruff and Mypy across **85 night-shift source files** pass. The skips
remain Linux-only file descriptors and unavailable unelevated symlink creation.
These are targeted offline checks, not the full suite or native evidence.

This checkpoint adds `night_shifts/bootstrap_native_denials.py` and synthetic
format tests. The module has no native I/O, CLI, boot function, command executor,
policy loader, media writer or runtime evidence acceptance API. It is not added
to the public support ZIP or production inspection bundle. It does not make a
runnable native validator. The separately proposed fixture/worker candidates
are reviewed in the linked next checkpoint; complete supervisor, activating
media, protected host watchdog and independent evidence channel remain open.

## Fixed validation boundary

The validator is a **separate validation-only boot**, not a flag added to the
public publication probe. The probe requires an otherwise-empty runtime/pool;
negative fixtures must never weaken that check or appear in its support seed.
No target VHDX, NIC, shared folder, serial pipe, real credential or publication
is needed for denial validation. No KVP daemon is started for the denial cases.
Actual daemon compatibility/publication remains a separate positive integration
step; these denials cannot substitute for it.

A future fixed runner must independently establish exact new VM ownership,
complete externally pinned/read-locked media, intended Secure Boot, disabled
checkpoints/GSI controls and exclusive host activity. Only that newly owned VM
may be stopped/removed. Retained images, claims, VMs and helpers are untouched.
Guest DMI strings, profile names and internal manifests are consistency checks,
not provenance. Host timeout, cancellation or transport loss means UNKNOWN until
exact-VM final absence is independently confirmed.

## Planned guest order — not yet implemented or authorized

1. Establish the same reviewed Linux/kernel/Python/tool prerequisites and disk,
   swap, PID, network and RAM isolation as the handoff candidate. Refuse missing
   prerequisites; no installs, upgrades, device/service/ACL repair or fallback.
2. Verify the complete source/fixture/policy media before use. Parse the exact
   policy bytes without load, check name absence, then add only. No replacement,
   cache, abstraction, dynamic rule or persistent policy installation.
3. Establish the same private mount/net layout and chroot. Prepare only the
   fixed RAM fixtures below, as new root-owned single-link regular files. Pin
   their bytes, owner/mode, mount and path resolution before use. Do not add a
   writable mount or grant a policy permission merely to make a test possible.
4. Run harmless **unconfined positive controls**, with the same UID/GID, zero
   capability sets, NNP, filesystem views and relevant syscall arguments. For
   filesystem tests the only meaningful difference is the AppArmor label.
   Check the exact executable tmpfs versus noexec pool and otherwise-valid DAC
   before and after controls. A missing, denied or uncertain control stops.
5. For each case, create one exact child with an empty/minimal environment,
   isolated/no-site Python, no inherited privileged descriptor and no arbitrary
   argv/path/payload interface. Drop all capability sets, set NNP, perform the
   fixed profile transition and require the exact enforced read-back **before**
   importing any support code. Do not move the transition earlier or retain
   capabilities if the existing ordering fails natively.
6. The unconfined supervisor captures a bounded fresh kernel-log interval and
   releases just one fixed operation. Require syscall EACCES **and** matching
   kernel-origin AppArmor denial for attribution. Keep the exact worker PID
   unreaped through collection to prevent PID reuse. Unexpected success is a
   failed confinement test, not permission to retry or broaden policy.
7. Stop/reap only the exact owned children under the independent host lifetime
   bound. Emit only bounded fixed-label local summaries; raw audit records and
   arbitrary child output must not reach the chat/host receipt. Guest summary,
   direct-child exit and audit correlation do not prove VM/tree absence.

The committed audit source supplies only the pure correlation step within
item 6. The separately proposed [fixed fixture/worker candidates](night_shift_native_worker_review.md)
add no supervisor, policy transition, fixture setup, boot activation or execution
authority. Their synthetic tests are still pending post-application verification.

## Fixed harmless cases and controls

| Case | Planned otherwise-valid RAM fixture/control | Confined observation and limits |
| --- | --- | --- |
| `runtime_write` | `/run/night-shift-bootstrap/denied-write`, root-owned mode 0600, fixed sentinel bytes; unconfined zero-cap/NNP control opens O_WRONLY without O_TRUNC and writes one fixed byte | Same fixed open must return EACCES and audit `open`, exact path, requested/denied `w`, root fsuid/ouid. Unexpected allowed open must be closed immediately; any test write can affect only this disposable RAM sentinel. |
| `pool_sibling_write` | `/var/lib/hyperv/.kvp_pool_denied`, same sentinel/control, on the existing pool tmpfs | Same EACCES/audit requirements. The pool's noexec flag does not invalidate a write control. Also require legitimate read/write/record-lock controls for all five exact allowed pool files; a broken positive path is not a successful policy. |
| `outside_exec` | `/run/night-shift-bootstrap/denied-exec`, root-owned mode 0700, on the executable runtime tmpfs; a separately reviewed/pinned inert x86-64 fixture that only exits with a fixed status | Unconfined zero-cap/NNP exec must actually exit with that status; confined exec must return EACCES and audit `exec`, exact path, requested/denied `x`. No shell, script interpreter, daemon copy, dynamic helper or arbitrary ELF is a substitute. The separately proposed 188-byte inert fixture is reviewed in the next source checkpoint; it has not been executed or validated natively. |

The two write controls do not create arbitrary paths or truncate real files.
The executable control must not have a shell/interpreter, network, mount, signal
or disk action. No negative operation is to be executed on the workstation,
retained VM/image or target disk. The fixed case catalog is not execution
permission and cannot be extended by caller-provided paths or command strings.

## Audit capture contract and attribution limits

The future guest supervisor must open `/dev/kmsg` read-only/nonblocking outside
the confined worker, establish a fresh cursor/last sequence, and collect whole
records without raw forwarding. It must not pass the log descriptor to workers.
No new audit daemon/service or permission repair is allowed. If the kernel/log
source or format is unavailable, stop rather than substitute journal text,
`dmesg` output, guest-supplied JSON or an exception string.

The pure checker requires:

- At most **64 records**, **8192 bytes per record**, **65536 bytes total**, over
  at most **5 seconds** of kernel-monotonic microseconds. These are per-case
  parsing/capture bounds, **not** the external VM lifetime watchdog.
- Exact `/dev/kmsg` headers, contiguous sequences after the recorded baseline,
  nondecreasing in-window timestamps, no continuation or multiline records.
  Read overflow/EPIPE/truncation/rate limiting/missing or delayed attribution
  must fail closed; the parser cannot prove the caller supplied the full stream.
- Kernel facility zero on candidate audit records; a userspace `/dev/kmsg` line
  imitating `apparmor="DENIED"` is not accepted. This is meaningful only for an
  authentic directly captured kernel stream, never caller-fabricated bytes.
- One exact type-1400 denial for the still-owned PID, exact enforced profile,
  operation, fixed path, requested/denied mask and root fsuid/ouid; no missing or
  duplicate fields, escaped/hex paths or ambiguous extra same-worker events.
  Optional class/error fields must agree. Unsupported native syntax stops for
  offline review, not a permissive parser fallback.
- EACCES from the exact operation. ENOENT, EROFS, EPERM, a missing audit event or
  unconfined/complain-mode event does not establish AppArmor attribution.

The result is deliberately named `LocalDenialCorrelation`. It contains only
case ID, PID, kernel sequence and audit serial: no overall success, authentic
boot, host receipt or cleanup assertion. Synthetic inputs can produce a local
correlation and therefore must never be accepted as deployment evidence. The
format fixtures are not claimed to be captures from the actual target kernel.

## Explicitly unresolved denial/positive coverage

- **Network:** creation-only AF_INET/SOCK_STREAM and AF_INET6/SOCK_DGRAM probes
  can be harmless if they never bind/connect/send and every returned descriptor
  is closed. However the current explicit `deny network,` may suppress audit.
  No network case is accepted by this checker. Decide offline whether to add
  explicit deny auditing to the **same reviewed production policy** and repin
  all affected source/seed/media, or establish another independently trustworthy
  attribution method. A different permissive test policy cannot validate the
  production one; failure/no route in a private netns is not LSM evidence.
- **Capabilities:** zero sets/NNP and a harmless fixed privileged-operation
  refusal are defense-in-depth observations, not proof of AppArmor's capability
  rule. No mount, ACL, disk or service mutation is an acceptable control. The
  explicit capability deny has the same audit-observability question.
- **Signals/ptrace:** exact-child stop is required. Self-peer signaling does not
  cover unrelated profiles; do not claim universal cross-profile isolation or
  signal arbitrary processes. The policy allows receiving unconfined signals.
- **Positive runtime:** actual ZIP imports, Python/shared objects, exact daemon
  execution/device use, fresh pool locking and public record publication still
  need their own isolated native integration observation and independent exact-VM
  host receipt. This component executes none of them.

## Applied offline verification and next checkpoints

The normal combined command was:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_denials.py tests/night_shifts/test_bootstrap_confinement_contract.py tests/night_shifts/test_bootstrap_recovery_handoff.py tests/night_shifts/test_bootstrap_recovery_native_policy.py tests/night_shifts/test_bootstrap_public_probe.py tests/night_shifts/test_bootstrap_daemon_asset.py tests/night_shifts/test_public_bootstrap_kvp.py tests/night_shifts/test_maintenance_credentials_prototype.py tests/night_shifts/test_maintenance_tls_prototype.py tests/night_shifts/test_maintenance_failure_diagnostics.py tests/night_shifts/test_maintenance_store_native_prototype.py -rs
```

Result: **641 passed, 2 skipped in 4.58 seconds**. No runtime source repair was
needed. The actual in-memory **31-entry inspection ZIP** excludes the new module;
the public support inventory also excludes it. Strict warning-as-error in-memory
compilation and Python 3.12 grammar parsing pass for the **two new Python files**
and **11 packaged Python snapshots**. This does not execute Linux/Python 3.12,
imports, native syscalls or ABI validation. Canonical-LF launcher/policy snapshot
hashes remain unchanged. Existing tracked runtime/script/night-shift test sources
match HEAD; the two untracked Python files are checked separately. All **24 local
document links** resolve and **six current Python/document files** pass final-
newline/trailing-whitespace checks; `git diff --check` passes.

Actual-input seed/media building and the external staging-catalog rehash were
not repeated for this pure correlator/test/document checkpoint. No native log
was read, no policy/daemon/worker was executed, and no elevation, media writing,
VM/service/network operation, protected deployment, restart or new commit took
place. Synthetic correlations remain local consistency observations, never host
receipts, boot provenance, successful native denials or VM cleanup evidence.

The next fixture/worker source checkpoint and detailed supervisor protocol are
linked above. After verifying those proposals, implement/review the bounded
supervisor frame parser, paired positive controls, fixture setup, exact-child
lifetime and audit-capture handling. Resolve the network audit question before
claiming complete denial coverage. Then review
complete deterministic media and the protected exact-owned host runner/watchdog
and bounded evidence channel. A local separately approved native attempt can
follow only when those prerequisites exist. Even that success is **not Gate A**:
accepted image preparation, real credential provisioning, authenticated serial
transport and Gate A's independent lifecycle/cleanup boundary remain open.
