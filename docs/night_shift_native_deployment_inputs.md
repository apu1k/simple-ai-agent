# Fixed validator deployment-input bundle — unwired source candidate

## Status and runnable milestone

**Current checkpoint:** the [native provisioning body](night_shift_native_provisioning_body.md)
adds one fixed host source member and one explicitly allowed, still-unwired
consumer. That catalog/guard extension and its body/tests are **applied and
verified offline**, not installed or activated. All **52 new provisioning tests**
and the fresh twenty-seven-file related selection of **1,708 with two skips**
pass, warnings as errors. Ruff and Mypy across **104 source files**, Linux typing
of both changed sources, compilation/grammar, pins, payload exclusions, links
and whitespace pass. The current host inventory is **91 entries**. Fresh
independent code-tree/bundle review is mandatory; application is not provenance
or installation authority.

The input-bundle component's original **106 tests** are included in that related
selection. Its preceding checkpoint `8510310` passed **1,656 with two skips**;
the detailed record below is preserved as historical evidence, not a native
attempt. This remains the input-review/bundle component for a new protected
installation, following the [held media store](night_shift_native_media_store.md).
It is NOT an installer, protected worker, approval policy, tool, permanent claim,
VM-lifetime watchdog or evidence producer. The first approved native attempt and
Gate A remain outstanding. **Do not run checkout code elevated.**

The pre-draft committed focused eight-file baseline passed **370 tests with one
skip**, warnings as errors; repository Ruff and Mypy across **102 night-shift
source files** passed. Those are historical baseline results, not new-test or
native evidence. That earlier checkpoint passed repository Ruff and Mypy across
**103 source files**, plus Linux-targeted typing; the current extension passes
across **104 source files**. `git status --short` was empty
before drafting. An initial command
named a nonexistent support-seed test file and collected no tests; the corrected
selection above is the actual baseline result. The one skip is unavailable
unelevated symlink creation, not native success. Existing native primitive tests
use ordinary disposable non-secret marker fixtures, not the media-store anchor.

`bootstrap_native_deployment.py` is stdlib-only and deliberately unwired. It does
not import any snapshotted application module or codec. Merely carrying the native
media-store module and its dependency as archive DATA does not call their APIs
or exempt a new production importer from the existing isolation guard. Existing
inspection/helper/installer/claim paths and public/guest payload catalogs remain
unchanged. No existing installation or authorization is reused.

## What is fixed and what is independently pinned

The source reviewer returns a bounded ASCII JSON inventory of these exact trees:

- **29 code/policy entries**: 27 fixed source/policy files and two deliberately
  empty package initializers. This includes the public support/guest native
  catalogs, host media/store closure and this stdlib reviewer. No app/provider
  package initializer is copied.
- **20 codec entries**: the fixed pycdlib 1.21.0 package files, `py.typed`,
  `METADATA`, `WHEEL` and LGPL license. Installed launch scripts, RECORD paths,
  bytecode and optional surrounding environment files are not copied. No codec
  discovery through import/execution occurs. Version metadata is checked for one
  exact name/version, no Requires-Dist, and the pure-Python wheel tag. Located
  members must be actual absolute filesystem `Path` objects; generic metadata
  `SimplePath` providers, ZIP paths and relative/string substitutions refuse.
  Neither a version string nor this inventory authenticates the publisher.

Code is snapshotted as canonical UTF-8/LF, consistent with the existing seed and
handoff. Codec bytes/metadata are preserved exactly. Ordinary-process bounded
reads reject links/reparse points, nonregular/multilink/oversized leaves and
before/after leaf/ancestor/descriptor observation drift. These checks are not
Windows security-descriptor/held-handle protection, effective-token evidence or
protection against a privileged attacker. They do not make this checkout trusted.
Independent review of the exact resulting bytes and tree digests remains required.

The first applied real-source test exposed a Windows path/descriptor stat-provider
mismatch: the same unchanged file had distinct, individually stable `ctime`
observations. The repair bridges all OTHER fields, including added birth-time
checks, only for the Windows cross-provider comparison. Path observations still
compare exactly with later path observations; descriptor observations compare
exactly with later descriptor observations, including `ctime` in both. There is
no timestamp rounding/tolerance, retry, global `ctime` omission or POSIX exception.
Model regressions cover each retained cross-provider field, each provider's
independent drift and the Windows-only boundary. The real read-only snapshot
test now also actively refuses application/codec imports during acquisition.

The caller's immutable `ValidationDeploymentPins` must supply the independently
reviewed code/codec tree digests, runtime archive digest/length, and recovery ISO
digest/sector-aligned length. There are no source roots, output paths, commands,
custom filenames/catalogs, VM configuration, certificates or credential inputs.
A tree digest is SHA-256 of canonical sorted name/size/hash JSON, not concatenated
ambiguous file contents. Passing the hashes just returned by this reviewer as if
that were independent review is not provenance or authorization.

## Runtime and actual-input boundary

The isolated runtime profile is the **CPython 3.14 x64 embeddable ZIP**, needed for
the existing package extractor's stdlib `compression.zstd`. The complete original
archive must match its independent length/hash BEFORE ZIP parsing. Only its exact
37 regular leaf names are accepted; the exact disabled-site `python314._pth`
profile allows the runtime's own stdlib ZIP and `.` only. Site/path injection,
extra executables, system-Python/venv substitutions and alternate profiles refuse.
Binary members receive a bounded PE/AMD64 wrong-input check. No binary, DLL, pyd,
stdlib member, package hook or carried Python source is loaded or executed.

The existing retained `python-3.14.8-embed-amd64.zip` was read with the ordinary
host process only to inspect this profile's names, lengths and `_pth` data. That
read observed 12,601,679 bytes and SHA-256
`a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310`.
**This observation is not new publisher authentication, version certification,
installation approval or a decision to trust that runtime for this operation.**
No runtime is selected automatically or downloaded by the candidate. Separate
provenance/security review and independently supplied exact pins are mandatory.
The nested stdlib ZIP stays an opaque pinned runtime file; this component is not
a general stdlib auditor or Authenticode/catalog verifier.

The three fixed public inputs must match the preceding authenticated review's
complete length/hash before any runtime archive parsing:

- The one reviewed `linux-cloud-tools-6.8.0-139` Debian package, retained unchanged.
- Its fixed COPYING and GPL-2.0 license bytes.

Those pins deliberately appear here without importing application code. Tests
require them to match the existing asset/seed constants. The bundle does not
extract or run the ELF/package, omit the corresponding license, refresh metadata
freshness, authorize redistribution or establish native ABI/KVP compatibility.
Authenticated source/metadata evidence retained by the
[prior provenance review](night_shift_kvp_runtime_review.md) remains separate;
its preservation and fresh relevant-byte/provenance review are installer-policy
prerequisites, not booleans or attestations generated by this component.

**Recovery is a reference only.** This component does not open/hash/copy the real
ISO or claim to have acquired the complete native media set. The descriptor says
`verified_here: false`. Future protected provisioning must independently acquire,
verify and create-new copy it into the strict private anchor expected by the
media store; no permission repair or reuse of a retained failed attempt is allowed.

## Canonical input archive and inspection

The builder returns one ZIP_STORED archive IN MEMORY ONLY, with fixed timestamps,
regular mode-0444 metadata, sorted inventory and no directory/extra/comment entries.
Its **91 entries** are fixed (including the provisioning-body catalog extension):

- 49 `payload/` code/policy/codec files;
- 37 derived `runtime/` files;
- the three public `inputs/` files plus the complete original `inputs/runtime.zip`;
- a canonical `manifest.json` binding each file and the immutable input recipe.

The runtime's original ZIP is deliberately retained as data in addition to its
unpacked files, so inspection can independently require exact derivation rather
than trust a self-rehashed runtime-file manifest. There is no extractall or disk
output operation. Construction is bounded before serialization: 32 MiB original
runtime, 48 MiB runtime expansion, 64 MiB complete input bundle/expansion and
16 KiB local review. Entry bounds are checked before decompression; reads request
at most the declared bounded size plus one and require exact size/CRC. Unsupported
compression, encryption, data-descriptor flags, unsafe file types, duplicate names,
case aliases, traversal/missing/extra entries and changed metadata refuse.

Inspection checks the independently reviewed complete bundle digest BEFORE any
ZIP reader. It then requires the exact file inventory, canonical manifest and
WHOLE archive equality against its canonical reconstruction. Prefix/trailer bytes,
changed headers/timestamps/attributes, compression or merely reformatting the
manifest are not normalized into acceptance, even if a caller rehashes them.
It separately verifies the source/codec tree pins and empty initializers, the
public input pins, the original runtime archive pin/profile, and exact equality
of every derived runtime file with its pinned original member. It never imports
those files, reads the local checkout again or lets a manifest choose a file path.

The result is only a bounded ASCII `local_deployment_consistency_only` review:
bundle/manifest hashes, lengths/count and input recipe. It has no installation,
approval, native-pass, VM-absence or Gate-A acceptance field. Anyone able to call
Python can fabricate objects/bytes; the review is not a protected receipt.

There is intentionally no attempt/VM identity in this immutable deployment input
recipe. As required by the [media-binding design](night_shift_native_validation_media.md),
the future installed runner must first observe its fresh OFF Hyper-V VM's actual
GUID, then derive the public seed/CIDATA and dynamic review pins from the approved
immutable code/assets. A preselected UUID or untrusted caller's self-hash cannot
supply that binding or authority.

## Applied offline verification

The input-bundle tests mostly substitute source/codec trees, public-asset pins, inert
non-runnable PE/stdlib model bytes, metadata/filesystem observations and runtime
ZIPs constructed in memory. They cover pin-before-parse ordering, deterministic
fixed output, archive bounds/shapes, canonical refusal even after rehash, runtime
correspondence, codec metadata, source drift and static dependency closure. A
separate read-only test snapshots the real source/installed pinned codec if
available; an optional dependency skip is not successful review/deployment proof.
No installer, interpreter from the archive, package, ELF, DLL, guest, native
media-store acquisition, protected anchor, policy, log or VM operation is tested.

Reproduction commands:

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_deployment.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/bootstrap_native_deployment.py --follow-imports=silent --platform linux
git diff --check
```

### Preceding checkpoint's applied verification record (`8510310`)

- Initial new selection: **79 passed, one failed**. Initial twenty-six-file related
  selection: **1,629 passed, one failed, two skipped**. Both failures were the
  same real-source path/descriptor `ctime` comparison described above; repository
  Mypy also found one codec-locator `SimplePath` typing error. These are historical
  failures, not current results or native deployment observations.
- The source repair retains exact within-provider metadata checks and requires
  actual absolute filesystem codec locations instead of coercing generic provider
  objects. The repaired candidate passed the existing 80 new tests, Windows/Linux
  typing and lint in memory before application; those preliminary checks were not
  counted as applied-file results. Twenty-six additional regressions are now
  applied, including retained drift refusals and invalid codec locations.
- Fresh applied new selection: **106 passed in 0.76 seconds**, warnings as errors,
  no skips or exclusions. All runtime/public-asset/tree pins used to construct
  deployment archives are explicit synthetic substitutions. Carried PE/stdlib
  bytes are inert and non-runnable. The real source/installed-codec snapshot test
  only reads data and its import guard passes with pycdlib 1.21.0 available.
- Fresh applied twenty-six-file combined related selection: **1,656 passed, two
  skipped in 9.98 seconds**, warnings as errors, no exclusions. This includes all
  106 new tests. Counts overlap and must not be added; it is not a full-repository
  runtime run. Selection is every `test_bootstrap*.py`, plus
  `test_public_bootstrap_kvp.py`, `test_maintenance_credentials_prototype.py`,
  `test_protocol_bootstrap_main.py`, `test_protocol_test_bootstrap.py`,
  `test_linux_payload_newlines.py`, `test_maintenance_store_native_prototype.py`
  and `test_native_metadata_comparison.py`.
- The two skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation, not native successes. Existing primitive/metadata
  tests use ordinary disposable non-secret Windows marker fixtures, not a
  protected anchor, native media-store acquisition or deployment attempt.
- Repository Ruff and Windows-hosted Mypy across **103 night-shift source files**
  pass. Linux-targeted Mypy of the changed source passes.
- Both checkpoint Python files pass warning-as-error in-memory compilation and
  Python 3.12 grammar parsing. All four checkpoint files pass final-newline and
  trailing-whitespace checks; **five local document links** resolve; tracked
  `git diff --check` passes.
- Policy/worker canonical-LF hashes and the child's worker pin match. Public and
  native source catalogs remain **18/24 entries**. The new module stays excluded
  from both and from the actual **31-entry inspection ZIP**, built only in memory.
  Static regressions verify complete source closure and no production importer;
  carrying native modules as data does not relax their import/API isolation.
- At that checkpoint, the exact deployment inventory was **90 entries** (28 code/
  policy, 20 codec, 37 runtime, four input files and the manifest). Two actual source/installed-codec
  local reviews are identical in memory: **6,347 bytes, 48 entries**, within the
  16 KiB bound. This is local snapshot consistency, not provenance review or
  approval of those tree digests. No real-input deployment archive was assembled.
- `git status --short` contains only the four checkpoint files; existing tracked
  runtime, protected launcher/installer, policy and guest sources are unchanged.

The follow-up validation-record edits are **documentation-only**. Source snapshot
acquisition did require the narrow runtime correction described above; no policy,
media-store, child, confinement or native execution behavior was changed. These
results establish modeled archive/order/refusal behavior and ordinary read-only
snapshot consistency, not publisher authentication, privileged file acquisition,
protected installation, DLL/import confinement, native guest boot or VM absence.

## Next exit criteria toward the first native attempt and Gate A

The [provisioning-body candidate](night_shift_native_provisioning_body.md) supplies
create-new relative-handle installation copying, complete recovery hashing before
output creation, private descriptors at creation, writer/reader identity handoff,
full final verification and one-shot checked closure. It reuses only the native
primitive layer, not marker APIs, the media-store acquisition entry or an old
installer. **Applied and verified offline, still unwired:** all 52 new tests and
the explicit import-guard/catalog extensions pass within the **1,708-pass, two-
skip** related selection. No source/test repair was needed. New Windows calls
are modeled; actual source/codec inventory reviews are read-only consistency
checks, not protected runtime or installation evidence.

It does **not** supply its mandatory trusted pre-import bootstrap, permanent
install-attempt claim or process watchdog, so a protected installation is still
not runnable. None of the native exit criteria below has been satisfied by it.

1. Independently review the real code/codec/runtime/public/recovery inputs and
   retained provenance evidence; build/review the exact input archive ordinarily.
   This candidate does not itself establish that trust or provision anything.
2. Add a NEW, separately reviewed protected create-new installation/provisioning
   policy and fixed bootstrap. Verify the entire closed code/runtime/codec/input
   set before any candidate import; keep imports/DLL resolution confined to the
   reviewed installed runtime/system locations. Establish private root/anchor
   ownership/ACL/identities at creation, with no overwrite, repair, retry or reset
   of another installation/claim. Partial installation is retained and not reused.
3. Supply the distinct permanent execution claim, fixed diskless runner, bounded
   evidence channel and independent **VM-lifetime** watchdog. Keep exact media
   identities/read-sharing held throughout use and independently establish final
   exact-VM absence even after controller failure. No VM start before supervision.
4. Only after separate installation AND execution approval, perform one native
   attempt. Stop on native mount/transition/audit/path/cleanup failures for review;
   never weaken confinement, fix permissions or retry automatically.
5. Resolve image acceptance, KVP/credential bootstrap and authenticated real
   Hyper-V UART, then exercise and record Gate A's autonomous lifecycle cases.

No validation media or deployment archive was written, protected installer/helper
changed, input provisioned, elevation requested, guest executed, VM operated or
commit made during this checkpoint. **Gate A remains unrun.**
