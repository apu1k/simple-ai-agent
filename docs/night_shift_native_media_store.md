# Validation media materialization and held-file binding — unwired candidate

## Status and runnable milestone

**Applied and verified offline; unwired, not deployed or executed natively.**
All **62 new tests** pass. The fresh twenty-five-file related selection passes
**1,550 tests with two skips**, warnings treated as errors. This is the host-file
component of the fixed diskless validation-VM milestone, not its protected
installer, launcher, VM-lifetime watchdog or evidence producer. The preceding
[two-media format component](night_shift_native_validation_media.md) is unchanged.

The pre-draft twelve-file related baseline passed **957 tests**, warnings as
errors; repository Ruff and Mypy across **101 night-shift source files** passed,
and `git status --short` was empty. Those are historical baseline results, not
new-test or native evidence. The applied checkpoint passes repository Ruff and
Mypy across **102 source files** plus Linux-targeted typing.

`bootstrap_native_media_store.py` is deliberately unwired, with no CLI, tool,
production importer or guest/public source-catalog entry. **Do not run checkout
code elevated.** A future separately reviewed protected installation must pin
all code/runtime/codec files before import, establish input provenance, constrain
plan/binding derivation and the approval window, and authorize exactly one
execution. Passing hashes or constructing a Python object cannot supply that
authority. As explained in the preceding media document, the new VM GUID must
come from the future protected runner's observed fresh OFF VM, not an arbitrary
preselected UUID. Attempt-bound media/review hashes may then be derived from the
independently reviewed immutable recipe; they are not preapproved static hashes
of an as-yet-unknown VM GUID. This component does not create that VM.

## Fixed storage contract, not an arbitrary file writer

The caller's reviewed plan binds the attempt/VM IDs, anchor volume/file identity,
public support ZIP hash, complete canonical CIDATA hash, and recovery ISO hash
and sector-aligned length (40 KiB through 8 GiB). The separately supplied review
hash must match the complete, canonical at-most-8192-byte ASCII descriptor.
That descriptor nests the prior CIDATA review and adds the recovery input,
anchor identity and fixed roles. Both descriptors explicitly remain local-only;
no approval, native-pass, cleanup or Gate-A acceptance is produced.

The existing anchor must be a strict **Administrators/SYSTEM-only** protected
NTFS directory. It must already contain the separately authenticated, private,
single-link `recovery.iso`. This code does **not** copy, discover, download,
repair or provision that ISO or its parent. Establishing that complete real
input set under the future installer's policy remains outstanding.

The only new directory is `validation-media-<attempt_id>`, directly beneath
that held anchor. The only new files are `cidata.iso` and `review.json` inside
it. Files/directories are created with their private security descriptor at
creation, not made private after writing. There is no output-path/file-catalog/
command override, overwrite/truncation, parent creation, permission repair,
delete, rollback, old-directory reuse or automatic retry. A partial directory
is retained as a consumed materialization identity. The future installation's
permanent execution claim remains a separate requirement: an early refusal
before directory creation is not permission for an autonomous retry.

## Acquisition and read-sharing-only lifetime

The candidate reuses the existing native store prototype's **handle, NTFS,
relative-open, metadata, owner/DACL and close primitives**. It does not invoke
or modify its marker writer/probe, relax its private profile, or promote any
old prototype observation into production evidence. The new specialized leaf
adapter is separately reviewed here; the complete dependency closure must be
pinned by the future protected deployment.

The initial dependency regression found that the older isolation guard forbade
all imports of the prototype, including this explicitly proposed primitive
reuse. The applied test-only adjustment permits exactly this candidate's
`from night_shifts import maintenance_store_native_prototype as native`, rejects
other importers/direct marker-API imports/star imports/aliases, forbids marker-
API attribute use here, and requires this new candidate itself to remain without
any night-shift source importer. It does not wire a production caller, change
the native primitive implementation or relax its security policy. The revised
guard passes in the fresh combined selection; no runtime repair was needed.

Ordering:

1. Validate path/plan/deadline, rebuild the canonical CIDATA from the fully
   validated seed, and compare independent image/review pins **before native
   writes**. Rendering is memory-only and reuses the pinned codec, not an
   untrusted descriptor as authority.
2. Require an enabled administrator token; open a fixed local NTFS volume and
   every ancestor relative to held directory handles. Refuse reparse/unsafe
   shapes and untrusted ancestor mutation/replacement permissions; require
   the anchor's exact reviewed identity and private security.
3. Open `recovery.iso` with read access and **FILE_SHARE_READ only**, establish
   its same-volume identity/security/length, stream its complete SHA-256 and
   require exact EOF. This precedes the new directory claim or output write.
4. Create the new private attempt directory and each fixed output with
   create-new semantics, using an exclusive writer. Check the held directory
   chain and empty/new-file metadata before each write. Each file uses one
   bounded write and a checked flush. Short/failed writes are terminal.
5. Close each writer once, then reopen its fixed name **relative to the held
   private parent**, with read access and FILE_SHARE_READ only. Require the
   same identity, owner/DACL, shape and exact canonical bytes before returning
   any usable paths. The archive-bit/expected-size write delta is narrowly
   permitted; arbitrary metadata changes are not.
6. Recheck all directories/files, stream-hash recovery again and compare both
   outputs exactly, recheck metadata/paths, then check the original deadline.
   `checked_paths()` repeats verification; there is no cached-success bypass.

There is a deliberate **writer-close → reader-open handoff**, not an assertion
of an uninterrupted writer/read lock. The held parent cannot be renamed through
ordinary delete-sharing, its verified private ACL authorizes no untrusted
writer, and replacement/security/content drift refuses on reacquisition. No
attachment/use happens in that interval. Administrators/SYSTEM are trusted;
this is not protection from a hostile privileged actor or kernel.

The final three leaf handles permit compatible readers, but deny data-writing
and delete-sharing opens. Directory handles also deny delete-sharing. Metadata-
only opens are not all prevented by Windows sharing rules: owner/DACL policy
and repeated metadata checks are separate requirements. Existing incompatible
opens refuse, never trigger a less restrictive mode.

Returned paths use the acquired **volume GUID**, not a newly resolved drive
letter. Native Hyper-V acceptance of these exact paths and VMMS read behavior
remain to be demonstrated; the runner must not silently convert paths, grant
new rights or relax sharing if they fail. Held identity/path checks exclude
substitution; local objects themselves remain forgeable Python data.

## Deadline, failure and lifetime boundaries

The one cooperative monotonic budget is at most **900 seconds** and is never
refreshed by a write, hash, verify or path request. Recovery hashing is streamed
in 64 KiB buffers; the CIDATA retains its 2 MiB bound, the descriptor 8 KiB.
Successful short reads may form multiple chunks, but failed calls, short writes
and uncertain closes are not retried. Each handle is disarmed before its one
close attempt; all remaining handles are attempted even after another close
fails. Close uncertainty is UNKNOWN, not successful materialization or rollback.

Any held-set verification failure permanently disables that set and attempts
all closes. No partial path set is returned. Artifacts remain for review.
Repeated `close()` never retries an uncertain OS handle. There is no finalizer,
background retry, broad cleanup or filesystem deletion.

The future runner must keep a valid held set for its complete use and integrate
terminal failure with exact-owned VM shutdown/removal. **These file handles do
not supervise a VM.** A failed verification may close them; controller death
also releases them. Blocking native calls and codec work are not forcibly
bounded by Python deadline checks. The protected process watchdog and an
**independent watchdog covering the VM lifetime** are still required. Neither
a process timeout nor releasing locks establishes final exact-VM absence.

## Applied offline verification

All 62 new tests replace Windows acquisition/I/O methods, token checks and
filesystem observations. They use the real pinned ISO codec only in memory with
explicit synthetic public-asset pin substitutions. ABI models capture native
flags/dispositions through Python stand-ins; they never call the Windows APIs.
They cover fixed outputs, pin/plan/deadline refusal, private/ancestor/shape
faults, collisions, writer-reader replacement, byte/ACL drift, streaming bounds,
EOF, short writes, flush/read/seek failure and one-shot close uncertainty.
**They are not native file-lock, effective-token, media or VM evidence.**

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_media_store.py -rs
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_media_store.py tests/night_shifts/test_bootstrap_native_media.py tests/night_shifts/test_maintenance_store_native_prototype.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/bootstrap_native_media_store.py --follow-imports=silent --platform linux
git diff --check
```

### Applied verification record

- Initial new media-store selection: **62 passed in 1.93 seconds**, warnings as
  errors, no skips or exclusions. All Windows calls are replaced. The actual
  pinned ISO codec operates in memory with synthetic public-asset substitutions.
- Fresh twenty-five-file combined related selection: **1,550 passed, two skipped
  in 8.49 seconds**, warnings as errors, no exclusions. This contains all 62 new
  tests and the applied dependency-guard adjustment. Counts overlap with the
  individual selections and must not be added. The selected file set differs
  from earlier checkpoint selections; this is not a full-repository runtime run.
- The combined selection includes every `test_bootstrap*.py` module, plus
  `test_public_bootstrap_kvp.py`, `test_maintenance_credentials_prototype.py`,
  `test_protocol_bootstrap_main.py`, `test_protocol_test_bootstrap.py`,
  `test_linux_payload_newlines.py`, `test_maintenance_store_native_prototype.py`
  and `test_native_metadata_comparison.py`.
- Skips remain Linux-only disposable-fd behavior and unavailable unelevated
  symlink creation, not native successes. Existing primitive/metadata regressions
  use ordinary disposable Windows marker fixtures with substituted ownership;
  these are not native media-store, private-anchor, effective-token or VM proof.
- Repository Ruff and Windows-hosted Mypy across **102 night-shift source files**
  pass. Linux-targeted Mypy of the media-store source passes.
- All three checkpoint Python files pass warning-as-error in-memory compilation
  and Python 3.12 grammar parsing. All five checkpoint files pass final-newline/
  trailing-whitespace checks; **three local document links** resolve; tracked
  `git diff --check` passes.
- Canonical-LF policy and worker hashes match the boot pins; the child's worker
  pin matches. Public/validation catalogs remain **18/24 entries**. The new store
  stays outside both catalogs and the actual **31-entry inspection ZIP**, built
  only in memory. The applied guard checks that no night-shift source imports
  the candidate or invokes its dependency's marker APIs through it.

The only repair was the narrowly scoped dependency-boundary test adjustment
explained above. No runtime correction was required. This record follow-up is
**documentation-only**. The results establish modeled ordering/refusal and local
format consistency, not native file-sharing, real-input provenance, protected
execution, Hyper-V path acceptance, guest boot or exact-VM absence.

No actual-input seed/media publication, external asset-catalog rehash, native
media-store acquisition, protected anchor provisioning, elevation, protected
installation, guest execution, VM operation or commit occurred. Existing ordinary
non-secret temporary marker tests are explicitly distinguished above.

## Next exit criteria toward Gate A

1. Review actual seed/recovery/code/codec/runtime inputs under a new fixed
   protected deployment policy. Provision its exact private anchor without
   repairing/reusing retained failed attempts.
2. Integrate the fresh diskless exact-owned VM operation, distinct permanent
   execution claim, bounded evidence producer, and independent VM watchdog.
   Require independently established final exact-VM absence on every outcome.
3. Only after separate install/execution approval, perform one native validation
   attempt. Establish real guest boot, eleven-worker behavior, audit visibility,
   media/read-sharing and cleanup, or stop with a precise blocker.
4. Complete trusted image acceptance, KVP/credential bootstrap, authenticated
   Hyper-V UART, and then the autonomous Gate A lifecycle cases.

This checkpoint is not the first native attempt or Gate A. **Gate A remains
unrun.**
