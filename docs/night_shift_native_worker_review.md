# Native validation fixture and fixed worker — source review, NOT activation

## Checkpoint and limits

The audit-correlation checkpoint is committed as `8a83d8a`. The tree was clean
at resumption. Its normal eleven-file targeted suite was rerun with warnings as
errors: **641 passed, 2 skipped in 4.04 seconds**. Repository Ruff and Mypy across
**85 night-shift files**, plus tracked whitespace checks, pass. These are checks
of the committed baseline, excluding the new pending fixture/worker/tests.
The skips remain Linux-only descriptors and unavailable unelevated symlink
creation, not native successes. Gate A remains unrun.

The applied source batch adds:

- `bootstrap_native_fixture.py`: fixed inert ELF **bytes in memory only**;
- `guest/bootstrap_native_worker.py`: fixed opt-in worker source, with no CLI;
- synthetic tests substituting all worker native adapters and decoding the ELF
  as data, never executing it;
- this supervisor/worker protocol review and links from current design/status.

No candidate is added to the public support ZIP, recovery handoff, production
inspection bundle or protected helper. No native supervisor or activating boot
entry is implemented. Source application is NOT execution approval. No elevation,
policy loading, daemon/worker execution, media writing, VM operation, service or
network change, restart or new commit occurred in preparing this source batch.

## Initial applied verification — narrow typing repair pending

The normal new suite passes **89 tests in 0.21 seconds**, warnings as errors.
The combined twelve-file selection passes **730 with 2 skips in 4.15 seconds**,
INCLUDING those 89 and the earlier 641 checks, with no temporary source hooks.
Repository Ruff passes. Standard Mypy across **87 source files** reports **seven
Linux-ABI attribute errors** in the worker under Windows stubs: major/minor,
stat device ID, access-mode mask and three native open flags. This checkpoint is
therefore **not yet fully verified**; those errors are not native test failures.

A narrow proposed repair adds explicitly Linux-guarded stdlib Protocol/cast views
for those attributes, keeping the same flags, device checks and exact operations.
It adds no backend injection, Windows emulation, fallback or ignored type errors.
The proposed source passes preliminary **in-memory-only** Mypy (one source), Ruff,
strict compilation and Python 3.12 grammar checks; the applied file is unchanged
until approval. Added direct non-Linux guard/read-bound regressions are pending,
and the normal full post-application checks must be repeated after the repair.
Do not promote that preliminary source check to an applied Mypy/test result.

The current three new Python files and 11 packaged Python snapshots pass strict
in-memory compilation/Python 3.12 grammar. The 188-byte fixture digest is
confirmed in memory only, never written/executed. Canonical-LF production
launcher/policy pins are unchanged. The actual 31-entry inspection ZIP and
public support inventory exclude both new candidates. Existing tracked runtime,
script and night-shift test sources match HEAD; new untracked sources are checked
separately. All 22 checked local links, six-file final-newline/trailing-whitespace
checks and `git diff --check` pass. No actual-input media/seed building or external
staging-catalog rehash was repeated. No native worker, fixture, log read, policy,
daemon, VM or elevated operation occurred during these offline checks.

## Inert executable control — exact data, no build toolchain

The applied generator returns exactly **188 bytes**, SHA-256:

`20ca4e55db7e6a7010eca0fb65eca069aebeff95a8b8ad147ef46cbcd36d018d`

This snapshot was constructed and hashed **in memory only**, not written to an
executable file or run. It is ELF64 little-endian Linux x86-64 ET_EXEC at
`0x400000`, with entry `0x4000b0`. Two program headers describe one RX PT_LOAD
and an RW/non-executable GNU_STACK. No PT_INTERP, PT_DYNAMIC, section table,
relocation, import, shell or dynamic dependency exists.

The complete 12-byte body is:

```text
b8 3c 00 00 00    mov eax,60
bf 25 00 00 00    mov edi,37
0f 05             syscall             ; Linux exit(37)
```

No read, write, open, socket, mount, fork, signal or host/disk action exists in
the fixture body. This static decode is not a Linux exec/ABI result. The validator
accepts only the exact full-file digest, never an arbitrary otherwise-valid ELF.
A future supervisor must create it once as root-owned mode 0700 at the fixed
RAM path `/run/night-shift-bootstrap/denied-exec`, with no symlink, hardlink,
reuse or executable workstation/staging copy. It must verify bytes and metadata
before and after each observation. Unexpected positive-control failure stops;
do not replace the fixture with a shell, script, daemon copy or different ELF.

## Worker entry contract — no caller-selected commands or paths

A future trusted standalone entry must independently authenticate/pin the full
media and source, establish exact new VM identity and isolation, and drop all
capability sets/set NNP. For a negative worker it must perform the existing
fixed profile transition and enforced read-back **before evaluating this source**.
The worker does not establish those properties or try another transition.
Its repeat checks are consistency refusals, not bootstrap provenance.

`run_fixed_case` accepts only fixed case ID, `control`/`confined` mode, canonical
attempt/VM IDs, externally trusted support-ZIP digest and an absolute deadline.
A future bootstrap must bound serialized context to 4096 bytes before evaluation.
The worker checks exact Linux x86-64/kernel 6.8.0-139/Python 3.12 isolated/no-site/
no-bytecode operation, root UID/GID, empty supplementary groups, zero capability
sets, NNP, exact expected label and environment `{LANG: C, LC_ALL: C}` (no PATH).

Before importing a support module it reads/checks the entire fixed ZIP against
its external pin and refuses an existing `night_shifts` import. It reuses the
existing read-only mount/device checkers, then checks block read-only/backing,
private mount/net namespace observations, DOWN loopback, swap/VM identity,
root-owned RAM directories and absence of the daemon in the visible process
inventory. This is not proof that the guest has a full host-approved PID view;
the trusted launcher/host must still establish that. No mount or permission
repair, policy change, installation or service operation is provided.

The trusted entry must evaluate the worker as separately pinned standalone code,
not import it through an already-loaded support package. It is deliberately
absent from current media inventories. The old empty-runtime/public-probe
preflight remains unchanged and must **not** be used with validation fixtures.

## Fixed operation semantics

| Case | Positive worker (`unconfined`, zero caps/NNP) | Negative worker (exact enforced label) |
| --- | --- | --- |
| `runtime_write` | Validate root-owned mode-0600 single-link one-byte RAM sentinel `V`; open the fixed path O_WRONLY, no create/truncate/follow; write exactly `V` once, close | Attempt only the same open; return errno on error. An allowed open is closed immediately, with **no write**, and reported as unexpected. |
| `pool_sibling_write` | Same operation on the fixed `.kvp_pool_denied` RAM sentinel | Same open-only negative operation; pool noexec does not explain a write refusal. |
| `outside_exec` | Validate the exact 188-byte/root-owned mode-0700 fixture, then exec that fixed path with sole fixed argv and an empty environment | Attempt the same fixed exec. EACCES is reported locally; success replaces the worker and exits 37, which is an unexpected execution/failure for the negative case. |

Neither exec branch creates a grandchild: the supervisor-owned worker PID is
also the audit PID. There is no Popen, shell, arbitrary argv/path/ELF API or
network syscall in this candidate. A returned errno is not AppArmor attribution;
only the separate correlator plus trusted capture and controls can supply a local
correlation. No worker report asserts overall success, host receipt or cleanup.

A confined worker must **not read the denied fixture before probing**: the
policy does not allow that read, and its audit would contaminate the one-operation
window. Therefore the supervisor must hold/verify full fixture provenance,
metadata, backing and byte pins before and after every worker. The negative
worker cannot establish that trust itself. It inherits no fixture descriptors.

## Fixed pipe protocol and bounded release

A future supervisor must supply only these descriptors:

- 0/1/2: `/dev/null`, never raw stdout/stderr forwarded to the host;
- 3: root-owned nonblocking CLOEXEC report-pipe write end;
- 4: a **different** root-owned nonblocking CLOEXEC gate-pipe read end.

The worker checks the descriptor inventory (ignoring only a vanished transient
listdir descriptor), file types/identities, access directions and flags. No
kernel-log, directory, fixture or privileged descriptor may be inherited. The
trusted bootstrap must map/set descriptors before source evaluation; there is
no worker-side repair. Every pipe frame is a single non-retried write of at
most **256 bytes**. Partial writes, EAGAIN/errors or missing frames are UNKNOWN,
not a reason to extend the deadline or replay an operation.

1. After prerequisites, worker emits one newline-delimited JSON `ready` frame
   containing only phase, fixed case/mode and PID.
2. Supervisor strictly checks fields/framing against its **own unreaped child
   handle/PID**, not a PID supplied as authority by the worker. It establishes
   a fresh lossless kernel-log cursor/sequence after readiness, before release.
3. Supervisor writes exactly `G` once to that worker's gate and closes its gate
   end. Worker refuses EOF, wrong/extra bytes, timeout or failed label/capability
   recheck. No operation happens before this gate.
4. Worker performs one fixed operation, emits one bounded `result` frame, closes
   its two pipe ends and returns. Successful exec instead closes both CLOEXEC
   descriptors and exits 37 from the inert fixture; no result frame is expected
   **only for a valid positive exec control**. EOF alone proves nothing.

The absolute worker deadline allows at most **5 seconds**, without resetting it
after readiness. Checks/readiness/gate/native calls share that budget. A blocked
kernel syscall is not forcibly bounded by this Python check: the independent
protected host watchdog remains required. The supervisor must bound aggregate
bytes, frames, process creation and whole-guest lifetime separately.

## Supervisor design still to implement and review

For each fixed case, use **control-before, one negative worker, control-after**:
nine exact workers for these three cases, never overlapping or retried. Keep the
same verified fixtures/mounts/identity conditions across each triple; any changed
inode/device/owner/mode/content or broken control fails the observation.

For the negative worker, retain exact-child ownership and PID **unreaped** while
collecting the bounded audit window. Use an appropriate reviewed WNOWAIT/pidfd
lifetime strategy; normal `poll()`/`wait()` reaping before capture is not enough.
Drain the kernel stream within the fixed window and require contiguous records
plus one exact kernel-origin denial and EACCES. Missing/delayed/duplicate logs,
EPIPE/overflow/continuation, transport loss, cancellation or uncertain child
state is UNKNOWN. A negative open/exec success is a failed denial test even if
nothing persistent was changed. Stop/reap only exact owned children; never
signal by process name, reload policy or reset state for a second attempt.

The supervisor still needs a fixed bounded frame parser/evaluator, create-new
RAM fixture setup/read-back, reviewed child bootstrap/descriptor mapping,
positive controls for all five allowed pool read/write/record-lock operations,
actual log capture, exact-child stop/reap and bounded fixed-label summary.
None of those is implemented by this worker. No full validator pass can be
reported without them. The current network/capability deny-audit observability
question remains open; this batch does not alter the policy or add socket probes.

After that source checkpoint, complete immutable validation media and the
protected exact-owned diskless host runner/watchdog/evidence channel need their
own review and fresh explicit execution approval. Native layout/denials and
public KVP feasibility still are not Gate A: accepted image, real credentials,
authenticated serial transport and independent Gate A lifecycle/cleanup remain
open. Retained VMs/images, claims, frozen helpers and prior receipts are untouched.
