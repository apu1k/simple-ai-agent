# Fixed validator child bootstrap and launch plan — source candidate only

## Milestone and boundary

This supplies the child-entry component of the diskless native-validation VM
milestone, following [held RAM fixture acquisition](night_shift_native_ram_fixtures.md).
It is not a spawned child, runnable supervisor, boot payload or protected runner.
There is no CLI, policy loading, capability repair, VM operation or new tool.
Source application is not native execution approval. The following
[exact-child owner candidate](night_shift_native_child_owner.md) supplies fixed
spawn, bounded pipe I/O and held pidfd/WNOWAIT lifetime as separate unwired
source. Its **118 offline model tests** and **1,196 combined related tests with
two skips** pass, with repository Ruff, Mypy across **96 source files** and
Linux-targeted owner typing passing. No source/test repair was needed. These
checks are not native spawning, waiting, signaling, cleanup or confinement
observations. Neither component is a complete native validator or execution
authorization.

Two candidates are deliberately absent from production/public media inventories:

- `bootstrap_native_child_plan.py` snapshots the two fixed local source files
  and renders an immutable **in-memory** launch plan. It never executes argv.
- `guest/bootstrap_native_child.py` is a standalone stdlib-only entry for a
  fresh interpreter. Its function would manipulate the new child's descriptors
  and, in confined mode, perform the fixed profile transition. It must never be
  called in the supervisor or imported as the live worker's package entry.

The installed protocol worker, AppArmor policy, production launcher, public
probe, inspection bundle and protected deployment remain unchanged.

## Exact launch shape, not an arbitrary command interface

The renderer accepts the existing three fixed denial cases in `control`/`confined`
mode and one fixed `allowed_pools` positive case in `confined` mode only, plus
a canonical attempt/VM binding, support-seed digest, original guest-monotonic
absolute deadline, and two distinct descriptor numbers. No caller can select
source, path, command, environment, profile or executable bytes.

The sole planned argv prefix is:

```text
/usr/bin/setpriv --bounding-set=-all --inh-caps=-all --ambient-caps=-all
  --no-new-privs --reuid=0 --regid=0 --clear-groups --
  /usr/bin/python3.12 -I -B -S -c <fixed reviewed bootstrap bytes>
```

The future owner must use `shell=False`, `close_fds=True`, only the two exact
`pass_fds`, all three standard streams set to DEVNULL, cwd `/`, and environment
exactly `LANG=C`, `LC_ALL=C`. There is no `preexec_fn`. Passing a plan does not
establish those spawn options, utility identity, immutable media or child/PID
ownership; the future native owner must enforce and check them.

Worker source is independently hard-pinned to canonical-LF SHA-256:

`2b6fc9a513525eb2d39a6a4c50ef050620228fc4ff596925c9a279fd86a9d3d2`

The [paired sequence and confined pool-control candidate](night_shift_native_paired_sequence.md)
extends the worker with that one positive tag and explicitly repins its source.
That follow-up is now applied and verified offline: **106 new pool/sequence
tests** and **1,412 combined related tests with two skips** pass after one legacy
test-matrix update. Repository Ruff, Mypy across **98 source files**, Linux-
targeted typing of seven changed components and the exact worker pin pass. No
runtime correction was needed. The earlier verification below describes the
preceding checkpoint; neither record is native execution or boot provenance.

It is carried in memory, not written to a new guest path or imported from the
supervisor's loaded support package. A changed worker refuses until separately
reviewed and repinned. The bootstrap's snapshot/hash is part of complete-media
review, not an independent trust anchor. An untrusted caller's digest, a
self-hashed archive or a guest UUID cannot authenticate the launch.

The serialized context is at most 4096 bytes with ASCII, unique JSON keys and
strict fields/types. Embedded source snapshots are at most 64 KiB each; the
single Python command is at most 100000 bytes, below Linux's per-argument limit.
The original at-most-five-second deadline includes rendering/startup/bootstrap
and the worker; no readiness or mapping step renews it. This is a guest-clock
plan, not a host-clock deadline that can be copied to an unrelated kernel.

## Child ordering

The fresh Python interpreter loads only the trusted standalone bootstrap and
stdlib. Before worker compilation or evaluation it:

1. Validates context and the exact worker source pin.
2. Requires Linux x86-64/kernel `6.8.0-139-generic`, isolated/no-site/no-bytecode
   Python 3.12, real/effective root UID/GID, no supplementary groups, the exact
   minimal environment, one task/thread and no existing `night_shifts` imports.
3. Reads status and requires all five capability sets zero and NNP=1. The initial
   label must be exactly unconfined. Missing/duplicate/wrong fields refuse before
   descriptor mapping or profile transition. It **checks** the fixed setpriv
   result; it does not call another helper or retain capabilities to fix it.
4. Verifies stdin/out/err are `/dev/null`, and the source report-write/gate-read
   pipes are distinct root-owned mode-0600 FIFOs with the correct access modes
   and nonblocking flags.
5. Stages both sources with `F_DUPFD_CLOEXEC` at descriptors >=5, then maps them
   to 3 and 4 with non-inheritable `dup2`. Staging both first handles a 3/4 swap,
   already occupied targets and original descriptors above 4 without clobbering
   a source. No numeric fd supplied by a worker becomes ownership authority.
6. Enumerates and closes every extra inherited descriptor once, including
   fixture/directory/kernel-log handles and staging copies. Any uncertain close
   is terminal; remaining extras are still attempted. There is no close retry
   on an uncertain fd number and no silent `closerange` fallback. Legitimate
   reuse of a number by a later fresh `open` is a different descriptor lifetime.
7. Rechecks the exact 0–4 inventory, distinct original pipe identities, access,
   nonblocking flags and CLOEXEC on 3/4. CLOEXEC alone would not protect a
   fork-and-evaluate worker; the explicit extra-fd closure is required here.
8. In confined mode only, writes the fixed `changeprofile` operation once.
   Then it rechecks zero capabilities/NNP, the exact enforced label, descriptor
   inventory and original deadline. A short write, refusal, close uncertainty or
   wrong/complain label stops. There is no earlier transition, alternate profile,
   libapparmor fallback or broadened policy. Control mode stays unconfined.
9. Only now compiles/evaluates the exact standalone worker snapshot and invokes
   its fixed `run_fixed_case` with just the six existing worker context fields.

The worker then performs its existing full support-ZIP pin, guest/layout checks,
readiness, one-byte gate and one operation. The supervisor's held fixture pins,
authentic audit capture and paired positive controls remain mandatory. The
bootstrap does not validate allowed-pool read/write/record-lock behavior.

The wrapper exits 125 on **any** bootstrap/worker exception without traceback or
raw reports, retries or reusing the partially transformed process. Report EOF or
exit 125 is not success. A successful inert positive exec replaces that same
worker/Python process and exits 37 under the existing supervision contract;
there is no new grandchild. Exact PID continuity and native setpriv/exec behavior
still need actual observation, not an argv assertion.

## Verification scope

`tests/night_shifts/test_bootstrap_native_child.py` substitutes all native child
adapters and the worker-evaluation function. It checks capability/NNP ordering,
alias-safe fd mapping, privileged-fd removal, terminal transition/close/deadline
failures, exact source/context pins and generated argv. Embedded code is decoded,
parsed and compiled **as data only**; no generated wrapper, setpriv command,
worker, profile transition or executable fixture is executed. The deployment
exclusion check builds the actual inspection ZIP in memory only.

Reproduce after application:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_child.py tests/night_shifts/test_bootstrap_native_ram.py tests/night_shifts/test_bootstrap_native_supervision.py tests/night_shifts/test_bootstrap_native_worker.py tests/night_shifts/test_bootstrap_native_denials.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/guest/bootstrap_native_child.py night_shifts/bootstrap_native_child_plan.py --follow-imports=silent --platform linux
git diff --check
```

The model is not an fd table/kernel emulator, native ABI proof or AppArmor
validation. In particular, the transition with NNP/zero capabilities may refuse
natively. That requires offline review and a separately approved new attempt,
not moving the transition earlier or weakening confinement during execution.
Cooperative deadline checks cannot bound every kernel call; cancellation and
forced stop remain exact-child/host-watchdog responsibilities.

## What remains before the diskless operation can run

- Integrate the offline-verified [exact-child owner candidate](night_shift_native_child_owner.md)
  with authentic audit capture and held fixtures: fixed spawn, bounded
  report/gate I/O, pidfd/WNOWAIT lifetime, exact stop/reap and uncertain-cleanup
  handling. Modeled tests cannot establish native ownership, ABI behavior or
  process absence; actual native behavior remains unverified.
- Fresh authentic lossless kernel-log capture and full paired nine-worker order,
  plus confined allowed-pool controls and unresolved network audit visibility.
- Reviewed complete immutable media, protected one-operation diskless runner,
  independent watchdog/evidence and independently verified exact-VM absence.

These candidates neither activate the installed protocol worker nor finish
credential bootstrap, authenticated Hyper-V UART communication or image
acceptance. See the [supervision core](night_shift_native_supervision_core.md)
and [worker review](night_shift_native_worker_review.md). **Gate A remains unrun.**
