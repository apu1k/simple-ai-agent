# Native validator RAM fixture acquisition — unwired source candidate

## Purpose and milestone

This is the fixture-acquisition part of the **one fixed, diskless validation VM
operation** milestone. It supplies native filesystem code for a future guest
supervisor, rather than another report parser. It does not yet supply that
supervisor, an activating boot entry, media or a protected host runner.

`night_shifts/bootstrap_native_ram.py` is deliberately excluded from the public
support inventory and inspection ZIP. Import only constructs the already-pinned
188-byte inert ELF in memory. Instantiating `NativeRamFixtures` would perform
native guest reads and writes; **source approval is not native execution approval**.
There is no CLI, caller-selected file/command API or production transport change.

## Fixed acquisition contract

Before the first fixture creation the candidate requires:

- Linux x86-64, kernel `6.8.0-139-generic`, isolated/no-site/no-bytecode Python
  3.12; real/effective UID/GID zero, no supplementary groups, and exactly the
  `LANG=C`, `LC_ALL=C` environment. The supervisor is unconfined; this does not
  establish the zero-capability/NNP conditions required of its future children.
- The expected guest VM UUID, distinct mount/net namespaces from PID 1, no
  target block disk or swap, only a DOWN loopback, read-only optical/active-loop
  backing and no visible `hv_kvp_daemon`. These are local refusal checks, **not
  host authentication, full-PID-view provenance or proof of diskless launch**.
- The existing read-only-root/fixed-RAM-mount contract without modifying it:
  executable runtime tmpfs, noexec pool tmpfs, nodev/nosuid and no nested redirects.
- Root-owned non-group/world-writable directories opened from `/` one component
  at a time with `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK`. All ancestor fds
  remain pinned; there is no `realpath`-then-open fallback.
- Exact initial inventories: runtime contains only `support.zip`, pools are
  empty. The seed must be a root-owned single-link regular file, mode 0400,
  at most 512 KiB, matching the full externally supplied SHA-256. That supplied
  pin still needs to come from the reviewed immutable launch/media boundary.
- Held mount IDs from `/proc/self/fdinfo` and devices must agree with the actual
  checked mountinfo entries. Missing/ambiguous metadata refuses.

Eight create-new files follow, with no caller-provided bytes or modes:

| Fixed path | Mode | Content |
| --- | --- | --- |
| `/run/night-shift-bootstrap/denied-write` | 0600 | `V` |
| `/run/night-shift-bootstrap/denied-exec` | 0700 | Exact pinned 188-byte inert ELF |
| `/var/lib/hyperv/.kvp_pool_denied` | 0600 | `V` |
| `/var/lib/hyperv/.kvp_pool_0` through `.kvp_pool_4` | 0600 | `V` in each |

Each creation uses `O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK`, checks empty
new-file metadata, performs a single positional write and reads back the exact
bytes. Short/error writes stop; there is no second write, truncation, deletion,
permission/owner repair or reset/reuse. A restrictive umask causing the wrong
mode refuses rather than being changed. Existing/colliding objects are retained.

The five allowed pools are disposable **validation sentinels**, not KVP records.
Preparing them does **not** demonstrate read/write/record-lock permission under
the confined profile or actual daemon/publication compatibility. Those controls
still need to run in an appropriately bootstrapped child. The normal public
probe's empty-runtime/empty-pool preflight is unchanged and must not be used
with these fixtures. This is not a data-migration or image-preparation API.

## Held identity and lifetime

The supervisor retains directory, seed and fixture descriptors (15 persistent
fds for the fixed catalog). `verify()` is intended immediately before and after
**every** exact-owned worker, not once per three-worker group. It rechecks the
live guest layout, identical mountinfo, directory path/descriptor identities,
exact inventories, file device/inode/type/owner/mode/link count/size, mount IDs
and full bytes. Rewriting the same `V` during a positive control may change
mtime/ctime between observations; those times must remain stable within each
individual read. Atime is deliberately not an invariant.

This is point-in-time consistency, not continuous integrity or hostile-root
attestation. Authentic immutable media, exclusive sequencing, unchanged mounts,
otherwise-identical child conditions and exact unreaped PID ownership remain
supervisor/host obligations. A worker result is never authority for these pins.

All acquired fds are non-inheritable, but **CLOEXEC is not sufficient for a
fork-and-evaluate child**. The future trusted child entry must close every pin,
kernel log fd and other privileged descriptor and prove the fixed 0–4 inventory
before evaluating the standalone worker. The fixture candidate supplies no such
entry itself; the separate [fixed child bootstrap candidate](night_shift_native_child_bootstrap.md)
now supplies source for that step, but remains unwired and not natively validated.

Construction failure closes all retained descriptors once and leaves even
partial fixtures in guest RAM. A failed `verify()` makes the object terminal;
the supervisor must still call `close()` in its failure/cleanup path. `close()`
never removes a file. An uncertain POSIX close is not retried on that integer,
all remaining owned fds are attempted, and later calls preserve the explicit
`descriptor_cleanup_unknown` result. Descriptor closure is not child, process
tree, fixture absence or VM-cleanup evidence.

Each construction/check has an explicit original absolute monotonic deadline
of at most five seconds and cooperative cancellation, including regression and
callback/type checks. No deadline is renewed inside a check. A new verification
budget is not permission to rerun a failed probe. Nonblocking flags/cooperative
checks cannot bound every kernel call; the independently protected VM watchdog
is still mandatory. Error labels never contain native paths, bytes or exceptions.

## Verification scope

`tests/night_shifts/test_bootstrap_native_ram.py` substitutes **all** native
adapters. Its fake objects are held in Python memory; even the ELF is never
written to a native file or executed. The tests cover the fixed worker-compatible
catalog, seed pinning, every ancestor, create races, replacements/metadata/content
changes, live mount/guest guards, control timestamp handling, cancellation and
uncertain-close ownership. The actual inspection ZIP is built only in memory to
check the exclusion boundary.

Reproduce after source application:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_ram.py tests/night_shifts/test_bootstrap_native_supervision.py tests/night_shifts/test_bootstrap_native_worker.py tests/night_shifts/test_bootstrap_native_denials.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/bootstrap_native_ram.py --follow-imports=silent --platform linux
git diff --check
```

Passing these models/static checks is **not native fixture validation**. Native
filesystem/ABI behavior must be observed in the separately approved isolated
validation VM, not tested by invoking this constructor on the workstation or a
retained image. Nothing in this checkpoint authorizes policy load, media write,
VM operation, deployment, credential access or a Gate A attempt.

## Remaining work toward the runnable milestone

1. Apply, verify and integrate the [fixed child bootstrap candidate](night_shift_native_child_bootstrap.md):
   descriptor mapping and capability/NNP/profile ordering before worker evaluation.
   Actual confined allowed-pool controls remain a separate missing operation.
2. Native bounded report/gate I/O and exact-child pidfd/WNOWAIT ownership through
   audit collection, followed by exact stop/reap with uncertain exits explicit.
3. Fresh authentic lossless kernel-log acquisition and ordered nine-worker
   sequencing using the existing [supervision core](night_shift_native_supervision_core.md).
4. Pinned immutable media, one protected diskless-VM operation, independent
   watchdog, bounded evidence and independently verified exact-resource cleanup.

Network/capability audit observability also remains open. Even a successful
native validator is not Gate A: real credential bootstrap, authenticated guest
communication, accepted protocol image and the Gate A lifecycle runner remain
separate prerequisites. See the [validator design](night_shift_native_validator_design.md)
and [worker contract](night_shift_native_worker_review.md). **Gate A remains unrun.**
