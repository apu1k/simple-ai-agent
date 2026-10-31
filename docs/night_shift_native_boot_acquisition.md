# Validation-only boot/acquisition and NoCloud files — source candidate only

## Milestone and status

This supplies the guest boot/acquisition path for the [paired native sequence](night_shift_native_paired_sequence.md)
and a separate fixed NoCloud **in-memory file renderer**. It is not an ISO,
protected installation, VM start, native validation result or Gate A runner.
**Applied and verified offline; not deployed or executed natively.** All
**54 new boot/handoff tests** pass, and the wider twenty-one-file related
selection passes **1,466 with two skips**, warnings treated as errors. No source
or test repair was needed after application. Source application and rendering
executable data are not execution/deployment authorization.

Before drafting, the committed nineteen-file related baseline passed **1,412
with two skips**, warnings treated as errors. Repository Ruff and Mypy across
**98 night-shift source files** passed; the working tree was clean. The skips
remain Linux-only disposable-fd behavior and unavailable unelevated symlink
creation, not native successes.

New candidates, deliberately excluded from existing public/production inventories:

- `guest/bootstrap_native_boot.py`: standalone stdlib acquisition entry with
  fixed internal namespace/supervisor phases. **Its phase functions would mount
  filesystems, add the fixed policy, chroot/exec and invoke native workers.**
- `bootstrap_native_handoff.py`: returns five fixed NoCloud files and digests
  in memory only. No output path, ISO builder, download, key generation,
  protected-helper change, host/VM operation or execution API is provided.

Neither candidate may be invoked on the workstation, retained guest/image or
outside the separately reviewed fresh diskless validation-VM operation. The
publication launcher, installed protocol worker and public probe remain separate.

## Fixed files and complete-media trust boundary

The renderer first uses the existing complete public-seed validator against an
externally supplied support-seed pin. It copies that seed and its public source
bytes unchanged. It snapshots **eleven fixed native source components**, including
the bootstrap, from this checkout as canonical UTF-8/LF data. The separate
`validator.zip` has **24 fixed entries**: 21 source/policy files, two empty package
initializers and a canonical binding/size/hash manifest. The original
`support.zip` retains its **18-entry** inventory and 512 KiB bound.

Only these five files are returned:

```text
user-data
meta-data
network-config
support.zip
validator.zip
```

The source ZIP is at most **1 MiB**, each entry at most **128 KiB**, ZIP_STORED
with exact regular-file attributes, fixed timestamp and sorted inventory.
Duplicate/extra/traversal names, compression, comments/extra data, noncanonical
headers, prefix/trailer bytes, nonempty initializers and cross-archive public
source mismatches refuse. Whole-input SHA-256 is checked **before parsing that
archive**. The two internal manifests provide consistency, not provenance.

The policy has an independent fixed canonical-LF pin:

`05e702c364a532679456826e22d6d28e108222ea387df6a690141e60194a166a`

The worker snapshot must still match:

`2b6fc9a513525eb2d39a6a4c50ef050620228fc4ff596925c9a279fd86a9d3d2`

No weaker policy, replacement executable or caller-selected source/path/command
is accepted by the renderer. The bootstrap carried in user-data must exactly
match its source-ZIP copy before staging/execution. Public modules are identical
in both ZIPs, avoiding two conflicting package versions. Native code is imported
from a sealed regular-file tree rather than a ZIP so the existing child-plan
snapshotter can inspect the actual pinned standalone worker/entry paths.

**None of these self-computed digests authenticates untrusted media, a guest or
publisher.** Before execution the future protected author/runner must separately
review and pin/read-lock the complete NoCloud/validation/recovery media, enforce
exact new VM ownership/configuration and provide an independent watchdog and
evidence/absence channel. Parameters, DMI strings and guest summaries cannot
replace that authority. Real credentials are absent from this route.

## Root entry and bounded acquisition

The shell-free NoCloud command has a fixed minimal-environment prefix:

```text
/usr/bin/env -i LANG=C LC_ALL=C /usr/bin/python3.12 -I -B -S -c <fixed source wrapper>
```

No users, passwords, package updates/upgrades, package/storage/install hooks or
arbitrary write_files are added. The embedded wrapper is capped at 100,000 bytes,
user-data at 128 KiB. The renderer does not execute it or author an optical image.

A root entry establishes one original **90-second guest-monotonic deadline**
before acquisition. Internal phases carry that absolute deadline without renewal.
It requires the pinned x86-64/Linux kernel/Python runtime, isolated/no-site/
no-bytecode mode, root identity, minimal environment, unconfined label, one task,
original full guest PID-namespace view, only read-only optical/configured-loop
backing, no swap, no NIC and no visible KVP daemon. Missing tools/prerequisites
refuse; no installs, service/ACL/device/capability repair or retry is supplied.

Only a new `/run/night-shift-native-validation` stage on an exact root-owned RAM
`/run` is created. Existing stage objects/profile names are collisions, never
reused/deleted/replaced. The fixed CIDATA optical source must resolve to a
read-only sr block device; it is mounted iso9660 read-only/nodev/nosuid/noexec.
RAM staging directories and this read-only mount necessarily precede archive
reading. **No policy/source-file/fixture write occurs before complete input
hash/shape/cross-source/policy/worker-pin validation.**

The exact reviewed policy is staged create-new, parsed with `-Q -K`, checked
absent again, then added once with `-a -K` and required to appear enforced.
There is no --replace, cache/abstraction fallback, remove, permission repair or
relaxation. Initial guest policy changes are disposable-VM state, not host state;
no rollback or automatic guest policy cleanup is claimed.

All tool argv are fixed by trusted source, absolute, shell=False with stdin and
native stdout/stderr DEVNULL, minimal environment, cwd `/` and close_fds=True.
Non-phase commands have at most three seconds within the original deadline.
Mount uses `-n --internal-only`, not external mount helpers or mtab writes.
Direct-tool timeout/termination does **not** prove process-tree or VM absence.
Every native failure stops; the independent host watchdog remains mandatory.

## Private root and supervisor handoff

A fresh fixed unshare mount/net phase keeps the original complete guest PID
view. It rechecks input pins and policy state before preparing:

- a 16 MiB RAM root, then sealed readonly/nodev/nosuid/noexec;
- readonly `/usr`, `/etc`, `/proc` and `/dev` views;
- fresh readonly sysfs after the new network namespace, not an old-network /sys bind;
- executable 1 MiB runtime tmpfs and noexec 256 KiB pool tmpfs at the existing
  exact paths; no additional writable mount is added for a test;
- fixed seed/source archives, bootstrap entry and create-new source tree on the
  root, with root-owned single-link mode-0400 files.

After chroot, same-PID setpriv/fresh isolated Python clears supplementary groups
and enters only the fixed supervisor phase. **The trusted unconfined supervisor
intentionally retains root capabilities needed for /dev/kmsg. This is not a
worker capability exception.** Every worker still goes through the existing
all-capability-set drop, NNP, descriptor isolation and enforced-profile checks
before worker source evaluation. No earlier profile transition is introduced.

Before importing any night_shifts package, the supervisor rechecks runtime/
private namespace/empty-group requirements, the exact readonly/RAM mount view,
both global archive pins, source directories/metadata, every staged source byte
and bootstrap identity; an import collision refuses. Only then does it add the
fixed sealed source path. The existing full public-seed semantic/asset/codec
validator and mount checker run before fixtures or workers. They do not call
publication or execute the daemon.

The supervisor creates the existing held fixtures under at most five seconds,
runs the fixed sequence under at most sixty seconds (both clipped to the original
90-second deadline), and closes caller-owned fixture pins before producing a
summary. Sequence/fixture-close failure or a retained uncertain child prevents
summary acceptance. Stage artifacts, profiles and mounts are not removed/reused;
final cleanup is the future exact-owned VM operation's responsibility.

## Output, unknown states and outstanding native proof

Only the exact existing at-most-512-byte ASCII `local_consistency_only` summary
is allowed, emitted once without raw source/log/worker/tool output. Internal
phase failures use a fixed UNKNOWN frame/exit 125. A nested phase failure can
also cause its root wrapper to emit a second fixed UNKNOWN; extra/unknown output
is not success and must not be promoted to a host receipt. Cloud-init's own logs
are not a bounded authenticated evidence channel supplied by this component.

Descriptor closes are attempted once per owned lifetime, even after errors;
short writes and uncertain close are terminal, never retried. Cancellation and
hung kernel calls/stdout cannot be forcibly bounded by these cooperative guest
checks. Timeout, local process exit or a matching summary never establishes
exact VM/tree absence. No raw audit records are forwarded or accepted as native
evidence by an application API.

Native parser flags, unshare/chroot/mount/PID views, tool/stdlib binary identity,
capability/NNP/profile-transition feasibility, kernel-log clock/quiet-tail
behavior and genuine confinement remain unverified. In particular a finite
quiet interval is not a kernel audit flush proof. Network/capability audit
visibility and later actual daemon/KVP/credential integration remain open.

## Applied offline checks

The handoff tests use explicit synthetic public asset-pin substitutions, build
and validate canonical bytes only, and parse/compile generated wrappers **as
data**. The guest-phase tests replace OS/tool/import/fixture/sequence adapters
before invocation. No native mount, policy parse/load, chroot/exec, fixture write,
lock, child, log access or VM operation is exercised by those models.

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_handoff.py tests/night_shifts/test_bootstrap_native_boot.py tests/night_shifts/test_bootstrap_native_pools.py tests/night_shifts/test_bootstrap_native_sequence.py tests/night_shifts/test_bootstrap_native_capture.py tests/night_shifts/test_bootstrap_native_owner.py tests/night_shifts/test_bootstrap_native_child.py tests/night_shifts/test_bootstrap_native_ram.py tests/night_shifts/test_bootstrap_native_supervision.py tests/night_shifts/test_bootstrap_native_worker.py tests/night_shifts/test_bootstrap_native_denials.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/guest/bootstrap_native_boot.py night_shifts/bootstrap_native_handoff.py --follow-imports=silent --platform linux
git diff --check
```

### Applied verification record

- New boot/handoff selection: **54 passed in 1.05 seconds**, warnings as errors,
  no skips or exclusions. Asset pins are explicitly substituted in inherited
  synthetic public-seed fixtures. Generated source is parsed/compiled as data;
  phase functions use replaced native/import/fixture/sequence adapters only.
- Eleven-file boot/handoff/pools/sequence/capture/owner/child/RAM/core/worker/audit
  selection: **918 passed in 2.23 seconds**, warnings as errors, no skips or
  exclusions. This includes the 54 new tests and preceding 864 related passes.
- Wider twenty-one-file related selection: **1,466 passed, two skipped in
  6.17 seconds**, warnings as errors, no exclusions. Counts overlap and must not
  be added. The skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation; neither is native success. This is not a
  full-repository runtime run.
- Repository Ruff and Windows-hosted Mypy across **100 night-shift source files**
  pass. Linux-targeted Mypy of the two new source components also passes.
- All four new Python files pass warning-as-error in-memory compilation and
  Python 3.12 grammar parsing; all six checkpoint files pass final-newline and
  trailing-whitespace checks; **three local document links** resolve; tracked
  `git diff --check` passes.
- Policy and worker canonical-LF hashes match the independent bootstrap pins;
  the worker also matches its child-entry hard pin. Public source/entry
  inventories remain unchanged at **18 entries**, while the separate fixed
  validation-source catalog has **24 entries**. Tests check cross-archive source
  equality, static package-import closure and the real bounded NoCloud argv.
- Both new candidates remain excluded from the actual **31-entry inspection
  ZIP**, built only in memory, and the public support source list. The bootstrap
  has only stdlib imports before its guarded dynamic import phase. No existing
  production source imports the handoff; the only new bootstrap importer is
  that unwired renderer. Existing tracked runtime/launcher/policy/deployment
  sources match HEAD; the tracked change is paired-sequence documentation,
  alongside the five new checkpoint files.

No runtime or test repair was needed after application; the validation-record
follow-up is documentation-only. Passing these models/static checks does not
establish native parser/mount/namespace/exec/transition behavior, authentic
lossless capture, protected execution, boot provenance or VM/tree absence.

The [validation CIDATA media candidate](night_shift_native_validation_media.md)
now supplies a fixed data-only ISO builder/inspector in memory, with whole-image
canonical equality, exact ISO9660/Rock Ridge/Joliet files and a bounded local
review descriptor. All **39 media tests** executed with the real pinned codec
and **1,505 combined related tests with two skips** pass. Ruff, Mypy across
**101 source files**, Linux-targeted typing, pins and inventory exclusions pass;
no source/test repair was needed. This is offline format verification: no ISO
file or recovery boot image is written or authenticated. Actual reviewed
complete-media materialization/read-locking, protected runner installation/
execution, independent watchdog/evidence and exact-VM final absence are still needed before
a separately approved native attempt. Accepted image/real credential bootstrap/
authenticated Hyper-V UART and autonomous Gate A integration are later
prerequisites, not results here. No elevation, native execution, media write,
VM operation, deployment, reload or commit is part of this checkpoint.
**Gate A remains unrun.**
