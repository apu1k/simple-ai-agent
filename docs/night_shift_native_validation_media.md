# Validation CIDATA media bytes and review descriptor — source candidate only

## Milestone and status

This completes the **CIDATA data-image construction/inspection component** for
the [validation-only boot/handoff candidate](night_shift_native_boot_acquisition.md).
It does not create the recovery boot ISO, write an ISO file, install a protected
helper, attach media, start a VM or supply authenticated native evidence.
**Applied and verified offline; not mounted, booted or deployed.** All **39 new
media tests** pass using the real pinned codec in memory. The wider twenty-two-
file related selection passes **1,505 with two skips**, warnings treated as
errors. No source/test repair was needed. Application is not execution,
protected-media publication or Gate A authorization.

Before drafting, the committed twenty-one-file related baseline passed **1,466
with two skips**, warnings treated as errors. Repository Ruff and Mypy across
**100 night-shift source files** passed; the working tree was clean. The skips
remain Linux-only disposable-fd behavior and unavailable unelevated symlink
creation, not native successes. The already-pinned optional development codec,
**pycdlib 1.21.0**, is available; no dependency was installed or downloaded.

`bootstrap_native_media.py` is intentionally unwired and excluded from existing
public/production inventories. Its public builder/inspector take only binding,
public seed bytes and exact expected hashes; no output path, custom file catalog,
command, VM configuration or source override is accepted. They operate in memory
and return image bytes plus a bounded local review descriptor, not a receipt.

## Fixed secondary image, not a bootable installer

The builder rerenders the existing fixed handoff after its full public-seed pin
and semantic validation. It includes exactly these five root files:

| Linux/Rock Ridge/Joliet name | ISO9660 alias |
| --- | --- |
| meta-data | METADATA.;1 |
| network-config | NETCFG.;1 |
| support.zip | SUPPORT.ZIP;1 |
| user-data | USERDATA.;1 |
| validator.zip | VALIDATR.ZIP;1 |

The ISO is **CIDATA, ISO9660 + Rock Ridge 1.09 + Joliet level 3**, with no UDF,
El Torito boot catalog, installer, extra directory, symlink or associated file.
Files have root-owned read-only regular-file Rock Ridge metadata. All three
namespace views must contain precisely those files and their exact current
handoff bytes. The original 18-entry support ZIP and separate 24-entry source
ZIP remain unchanged; the guest bootstrap/policy/worker are not modified here.

Image/output buffers are bounded to **2 MiB**, with 2048-byte sectors. Known
primary/supplementary/terminator descriptors, CIDATA label, volume-size endian
copies, logical block size and an empty system area are checked. Source data
buffers stay alive through serialization; no temporary output file or library
file-writing API is used.

This is a **nonbootable secondary data volume**. A separately reviewed and
hash-pinned recovery boot ISO is still required. This checkpoint cannot claim
that the complete two-media set is authenticated, bootable or read-locked.

## Reproducibility without process-global clock changes

The codec is required to be exactly **1.21.0**. Missing/mismatched dependency
refuses with no installation, fallback codec or Windows COM author. The narrow
metadata adapter is tied to that version and must be reviewed again for an
upgrade; a version string alone is not provenance for its installed package.
A future protected deployment must also pin the complete codec/runtime files.

The author freezes directory and Rock Ridge timestamps to UTC 2000-01-01 via
explicit date objects, after layout consistency. The codec's volume-descriptor
serializer independently writes a new modification time; consequently the
builder explicitly freezes the four known PVD/SVD date fields **on its own newly
authored bytes**. Expiration is unspecified rather than an expired date. It does
not monkeypatch a process-global clock, TZ, environment or library function.

Initial memory-only codec design probes established the timestamp behavior and
fixed-field layout before application. The applied builder/inspector tests now
also verify reproducibility under changed codec-local clocks/timezone views,
without changing process-global clocks. These are in-memory format checks with
synthetic seed assets, not media files, native mounts or boots.

## Strict verification, no repair of incoming media

The public inspector:

1. Checks binding/digest types, complete image size bound and independently
   supplied full-image SHA-256 before source rendering or ISO parsing.
2. Rerenders the current fixed handoff from the pinned public seed and current
   reviewed source snapshots, then reconstructs the canonical image.
3. Requires **byte-for-byte equality of the entire incoming image** with that
   canonical image, including metadata, unused/system areas and padding.
4. Only then invokes the codec reader and checks the exact regular-file names,
   lengths and contents in all three namespace views, plus the data-only profile.

A stale or altered image is not normalized, rewritten, salvaged or accepted
merely because its self-hash/manifest was recomputed. Prefix/trailing data,
changed metadata/content/padding or alternate file trees all refuse. Untrusted
image bytes cannot reach the third-party reader through this public API unless
they match the exact known canonical snapshot. Codec/build/close errors stop;
an uncertain close never returns a verified media object or implies VM cleanup.

Whole-image canonical equality is stronger than accepting only the five visible
files: it prevents hidden unrelated bytes from riding in an otherwise matching
file tree. It does **not** authenticate an untrusted expected hash, source tree,
public seed, publisher, recovery ISO or guest. Those remain external review
boundaries, not properties established by Python consistency checks.

## Local descriptor, not protected acceptance

The frozen local object returns the immutable image bytes, full-image hash/size,
binding, input seed/source/bootstrap/policy digests and five file metadata rows.
Its at-most-**4096-byte ASCII JSON** descriptor explicitly says
`local_media_consistency_only` and identifies a nonbootable CIDATA data volume.
No source/image bytes, arbitrary path, approval, native-pass, Gate-A-pass,
cleanup/absence claim or host-receipt acceptance field is emitted. Descriptor
construction checks bounded/coherent local fields but cannot confer authority;
ordinary Python callers can fabricate objects and descriptors.

The future protected author/runner must independently compare exact file bytes
and operator-approved digests under held file identities/read locks, alongside
recovery ISO provenance, installed code/runtime pins, exact VM ownership and
one-attempt/lifetime policy. It must never treat this descriptor or a guest
summary as evidence of those host facts. No existing inspection helper, permanent
claim or retained image/VM is reused or changed by this candidate.

## Applied offline verification

The tests use the actual pinned ISO codec on **in-memory** images and explicit
synthetic public asset-pin fixtures. They inspect all namespaces, deterministic
output under changed codec-local time/TZ views, whole-image corruption/staleness,
input/version bounds, descriptor limits and codec close failures. Global clocks
remain unchanged. Generated NoCloud/guest source is data only; it is never run.
Some format-auditor tests construct deliberately inconsistent images in memory,
not media files. Missing optional codec may explicitly skip positive codec
fixtures; a skip is not format/native success. In the current environment all
39 new tests executed with **pycdlib 1.21.0**, with no skips or exclusions.

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_media.py tests/night_shifts/test_bootstrap_native_handoff.py tests/night_shifts/test_bootstrap_native_boot.py tests/night_shifts/test_bootstrap_native_pools.py tests/night_shifts/test_bootstrap_native_sequence.py tests/night_shifts/test_bootstrap_native_capture.py tests/night_shifts/test_bootstrap_native_owner.py tests/night_shifts/test_bootstrap_native_child.py tests/night_shifts/test_bootstrap_native_ram.py tests/night_shifts/test_bootstrap_native_supervision.py tests/night_shifts/test_bootstrap_native_worker.py tests/night_shifts/test_bootstrap_native_denials.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/bootstrap_native_media.py --follow-imports=silent --platform linux
git diff --check
```

### Applied verification record

- New media selection: **39 passed in 0.90 seconds**, warnings as errors, no
  skips or exclusions. The real pinned codec authors/parses only in-memory
  images; public asset pins are explicitly substituted in synthetic fixtures.
  Generated NoCloud/guest code is never executed or written as a media file.
- Twelve-file media/handoff/boot/pools/sequence/capture/owner/child/RAM/core/
  worker/audit selection: **957 passed in 2.97 seconds**, warnings as errors,
  no skips or exclusions. This includes the 39 new and prior 918 related passes.
- Wider twenty-two-file related selection: **1,505 passed, two skipped in
  6.86 seconds**, warnings as errors, no exclusions. Counts overlap and must not
  be added. Skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation, not native/format successes. This is not a full-
  repository runtime run.
- Repository Ruff and Windows-hosted Mypy across **101 night-shift source files**
  pass. Linux-targeted Mypy of the new media source also passes.
- Both new Python files pass warning-as-error in-memory compilation and Python
  3.12 grammar parsing. All four checkpoint files pass final-newline/trailing-
  whitespace checks; **three local document links** resolve; tracked
  `git diff --check` passes.
- Policy/worker canonical-LF hashes and the child's worker pin match; the
  original public catalog remains **18 entries** and validation-source catalog
  **24 entries**. Neither is modified by the media component.
- The media candidate remains excluded from the public support inventory and
  actual **31-entry inspection ZIP**, built only in memory. No existing
  night-shift source imports it. Existing tracked runtime/guest/policy/launcher/
  protected-deployment sources match HEAD; the tracked change is boot-acquisition
  documentation, alongside the three new checkpoint files.

No runtime or test repair was needed after application. The record follow-up is
only documentation. These checks establish exact local in-memory image format,
reproducibility and refusal behavior, not source/publisher/boot provenance,
native Linux/NoCloud acceptance, protected media identity/read locks, trusted
host execution or VM/tree absence. No actual-input seed/media publishing or
external artifact-catalog rehash occurred.

## Next runnable-milestone boundary

Next supply protected create-new materialization and read-locked binding of the
complete recovery+CIDATA set, then the separately reviewed fixed diskless runner
with independent watchdog/evidence and independently verified exact-VM absence.
The watchdog must cover the Hyper-V VM lifetime, not merely terminate its Python
controller. A timeout is UNKNOWN until exact-VM final absence is established.

Actual Linux/NoCloud/parser/mount/transition/audit feasibility and unresolved
network/capability audit visibility remain native work. Accepted image
preparation, trusted real credential bootstrap, authenticated Hyper-V UART and
autonomous Gate A integration remain later prerequisites. No elevation, native
worker/guest code, file/media write, VM operation, protected deployment or commit
is part of this checkpoint. **Gate A remains unrun.**
