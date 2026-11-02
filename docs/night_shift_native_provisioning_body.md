# Create-new native validator provisioning body — unwired candidate

## Status and boundary

**Applied and verified offline; unwired, not installed or executed natively.**
All **52 new provisioning tests** pass. The fresh twenty-seven-file related
selection passes **1,708 with two skips**, warnings as errors. This is
`bootstrap_native_provision.py`, the one-shot Windows file-provisioning BODY
following the [deployment-input bundle](night_shift_native_deployment_inputs.md).
It is NOT a trusted bootstrap, independently installed executable, PowerShell
installer, protected tool, execution-policy/claim writer, VM runner or watchdog.
**Never run checkout code elevated.** Application/commit of these sources is not
permission to provision inputs or activate the installed code.

The clean committed baseline was `8510310`. Before drafting, the twenty-six-file
related selection passed **1,656 with two skips**, warnings as errors; repository
Ruff and Mypy across **103 night-shift source files** passed. Those are historical
baseline results, not provisioning or native evidence. The applied checkpoint
passes repository Ruff and Mypy across **104 source files**, plus Linux-targeted
typing of both changed source components. The skips remain Linux-only disposable-fd behavior
and unavailable unelevated symlink creation. Existing primitive tests use ordinary
disposable non-secret Windows markers, not protected installation/media fixtures.

### Mandatory trust BEFORE import

A separately reviewed protected bootstrap must authenticate and confine the
entire runtime/stdlib/DLL/code/import closure BEFORE importing this body, the
native primitives or the bundle reviewer. That bootstrap must also bind the
operator-reviewed paths, directory identities, exact bundle/input pins, approval
window and permanent install-attempt claim, and supply an independent protected
process watchdog. This body cannot establish its own import provenance or make
an untrusted interpreter safe by checking itself later. No such bootstrap or
claim is implemented, installed, reused or invoked here.

Consequently this candidate does not yet make a protected installation runnable.
Its result/record are consistency data, not bootstrap authorization or a new tool
operation. The older inspection/command/evidence installations, claims and
receipts remain untouched. No elevation is requested by the candidate.

## Fixed storage contract

The immutable plan binds:

- A 32-character lowercase-hex **installation ID**, not a VM GUID or run grant.
- Independently reviewed source-directory and output-parent NTFS identities.
- The exact deployment bundle hash/length and existing source/codec/runtime/
  recovery pins.

The constructor accepts only the two reviewed canonical local directory paths,
that plan and one original monotonic deadline. It performs no native access.
Only `run()` may touch Windows files; it disarms the object before its first
native call, including an early token/input refusal. A second call never retries.
Python objects remain forgeable; this is not permanent cross-process authority.
A fresh object/new ID is NOT permission to retry a failed operation. Permanent
install-attempt authorization must come from the future protected bootstrap.

Fixed inputs beneath the source directory:

```text
validator-inputs.zip
recovery.iso
```

Only `parent/native-validator-<installation_id>` may be newly created. Beneath
it, the exact reviewed bundle inventory is copied without path extraction;
`deployment.zip` retains the original archive; `media/recovery.iso` is the new
private recovery copy; `installation.json` is the last local consistency record.
There is no caller file catalog, filename override, arbitrary writer, command,
source-code argument, parent creation, overwrite, truncation, permission repair,
delete, rollback, old-directory reuse, automatic retry or VM operation.

The reviewed output parent and its existing ancestry must satisfy the native
primitive's existing strict BA/SYSTEM-owned ancestor policy, excluding untrusted
replacement/mutation permissions. **TrustedInstaller is not silently added.**
An incompatible Program Files/ancestor profile refuses; it does not trigger an
ACL adjustment or fallback to the older installers' broader policy. The new root,
all new directories and all new files receive the existing exact protected
Administrators/SYSTEM-only descriptor at CREATE time. Ordinary operator read
access is not added after writing.

Input staging need not be private or owned by Administrators. It is read-only
input, not trusted imported code: whole-input pins authenticate the bytes for
this operation. Source directory/file metadata and same-volume shape are still
checked; all traversal is no-reparse, relative to held no-delete directory
handles. Reparse/multilink/unsafe shapes or identity/security/path drift refuse.
New leaves cannot alias already held directory/input/output identities.

## Acquisition, copy and verification order

1. Require the enabled administrator token, fixed local NTFS roots and both
   reviewed final-directory identities. Acquire every ancestor relative to held
   no-delete handles and retain the complete chains.
2. Open the fixed input bundle READ-only with **FILE_SHARE_READ only**. Check
   exact size, read it within the 64 MiB bound and require its independent hash
   before any archive parser. Run the full existing canonical inspector, including
   source/codec/public pins, original runtime pin/profile and derived-file
   correspondence. Read only the fixed catalog; never `extractall` or use a
   manifest-selected output path.
3. Open the source recovery ISO under the same read-sharing-only contract and
   stream its COMPLETE independently pinned hash/length/exact EOF **before the
   first output-directory creation**. The body does not infer publisher provenance,
   bootability or safety from that hash or accept an unreviewed source image.
4. Create-new the exact private installation root and fixed private directories.
   Recheck the held directory chains before each creation/write. Empty package
   initializers remain zero-length new files, not existing files to truncate.
5. For each fixed bundle output, use an exclusive create-new writer, a bounded
   one-shot write and checked flush. Recovery uses 64 KiB streaming reads and
   one write per successful chunk, with an independent copied-byte hash and exact
   extent. Successful short source reads are ordinary progress, not failure
   retries; failed reads, failed/short writes and uncertain closes are terminal.
6. Check the writer's same identity/security/controlled size/archive-bit delta,
   close it once, then reopen its fixed name relative to the held private parent
   with READ access and FILE_SHARE_READ only. Require the SAME identity/security
   and complete exact bytes or streamed hash before accepting that output locally.
   No import, launch or other output use occurs during the writer-reader gap.
7. Reverify all source/output bytes and every held identity/security/path before
   the record. Write the bounded record last, verify all files/chains again,
   attempt all closes, then check the original deadline again before returning.
   A record may remain after a late failure or uncertain close; it is NOT proof
   of successful bootstrap acceptance or installation completion.

There is deliberately no assertion of an uninterrupted writer/read lock. During
handoff the held private parent denies ordinary replacement and its fixed DACL
authorizes no untrusted writer; identity/security/byte drift refuses on reopen.
Administrators/SYSTEM and the kernel are trusted. This is not protection against
a hostile privileged actor. Metadata-only Windows opens are not all excluded by
sharing rules; DACL policy and repeated metadata checks are separate requirements.

All final leaf readers remain held through the final checks. They are closed
before the local result returns: **no locks are promised across a later launch**.
A future installed bootstrap/runner must freshly verify and hold the complete
installed/import/media closure for its own use, enumerate/reject unexpected import
files and control DLL/search paths before loading any carried code. It must not
trust this record or a once-observed volume-GUID string as that protection.

## Data layout and explicit catalog extension

The host deployment catalog gains exactly one code member,
`night_shifts/bootstrap_native_provision.py`. Its applied frozen profile is:

- **29** code/policy entries (27 sources/policy plus two empty initializers);
- **20** codec entries;
- **37** runtime entries;
- **4** input entries and **1** canonical manifest;
- **91** bundle entries total.

The body copies those 91 entries and adds the original `deployment.zip`, the
private recovery copy and the local record: **94 fixed output files**. No guest
public/native catalog changes: those stay 18/24 entries, and the inspection bundle
still excludes the provisioning body and remains at 31 entries, checked from
the actual inspection ZIP built only in memory. This
changes the host code-tree/bundle digest and requires fresh independent review;
it does not repin the worker, alter AppArmor policy or extend the guest payload.

Two narrowly scoped isolation guards are updated WITH this candidate:

- The existing native primitive guard permits only the media-store candidate and
  this provisioning body to use the exact `native` import alias. It still rejects
  marker API use, star/direct-marker imports, other aliases and other importers.
  Native primitive/ACL policy source itself is unchanged.
- The stdlib bundle reviewer permits exactly this body's `deployment` import;
  other application importers remain forbidden. The provisioning body itself must
  remain without any application importer, CLI or tool/production wiring.

The `installation.json` record is at most 32 KiB of canonical ASCII JSON. It
identifies `local_provisioning_consistency_only`, says the bootstrap is NOT
supplied, and binds the installation ID, original bundle hash, immutable recipe,
root/media identities and fixed output sizes/hashes/identities. Its file list
excludes its own recursive digest. The recipe's original recovery-reference flag
remains unchanged; the verified private copy is separately present in its output
file list. No installed/approved/accepted/native-pass/Gate-A/VM-absence grant is
emitted. Its existence after failure does not release a claim or authorize reuse.

## Deadline and terminal uncertainty

One cooperative budget is at most **900 seconds**, never renewed by a write,
copy, verify, reopen or record. Recovery is bounded to 8 GiB, read in 64 KiB
chunks; the bundle retains its 64 MiB bound and all existing expanded/member
bounds. Complete recovery verification causes multiple streamed passes. Real
performance, file-sharing behavior, Windows token/ACL behavior and path acceptance
must be established in a separately approved experiment, not inferred from models.

The resource list disarms before closure; each OS handle is disarmed before its
one close attempt. Failure attempts all remaining closes even after another
close fails. Close uncertainty is UNKNOWN and overrides an otherwise complete
record. No finalizer, background retry, broad cleanup or deletion is provided.
Blocking kernel/codec operations are not forcibly bounded by Python deadline
checks. A protected process watchdog remains mandatory for provisioning. Future
VM execution additionally needs its independent **VM-lifetime** watchdog and
independently established exact-VM absence; a controller timeout cannot supply it.

## Applied offline verification

The new tests use the actual canonical stdlib archive codec with explicitly
synthetic source/public/runtime pins and inert non-runnable PE/stdlib models.
All Windows token/metadata/open/read/write/flush/close calls are replaced. They
cover fixed ordering/layout, source hash before output creation, collisions,
replacement/ACL/byte/identity drift, bounded streaming, late expiry, uncertain
close and one-shot refusal. ABI models inspect flags/counts through Python
stand-ins, not Windows APIs. Dependency/catalog regressions are part of the batch.
No new test provisions actual inputs or creates a protected/private installation.

```text
python -W error -m pytest -q tests/night_shifts/test_bootstrap_native_provision.py -rs
ruff check .
mypy night_shifts --follow-imports=silent
mypy night_shifts/bootstrap_native_provision.py night_shifts/bootstrap_native_deployment.py --follow-imports=silent --platform linux
git diff --check
```

### Applied verification record

- Initial applied new selection: **52 passed in 0.92 seconds**, warnings as errors,
  no skips or exclusions. Every new native/token/I/O observation is replaced.
  Synthetic source/public/runtime pins and inert PE/stdlib models are explicit;
  no archive-carried program or actual provisioning entry is executed natively.
- Fresh twenty-seven-file related selection: **1,708 passed, two skipped in
  10.00 seconds**, warnings as errors, no exclusions. This includes all 52 new
  tests and both applied dependency-guard extensions. Counts overlap and must
  not be added; this is not a full-repository runtime run. The selection is every
  `test_bootstrap*.py` module, plus `test_public_bootstrap_kvp.py`,
  `test_maintenance_credentials_prototype.py`, `test_protocol_bootstrap_main.py`,
  `test_protocol_test_bootstrap.py`, `test_linux_payload_newlines.py`,
  `test_maintenance_store_native_prototype.py` and
  `test_native_metadata_comparison.py`.
- The two skips remain Linux-only disposable-fd behavior and unavailable
  unelevated symlink creation, not native successes. Existing native primitive/
  metadata regressions use ordinary disposable non-secret marker fixtures with
  substituted ownership, not this body, a protected anchor or installed runtime.
- Repository Ruff and Windows-hosted Mypy across **104 night-shift source files**
  pass. Linux-targeted Mypy of the provisioning and deployment sources passes.
- All five checkpoint Python files pass warning-as-error in-memory compilation
  and Python 3.12 grammar parsing. All seven checkpoint files pass final-newline/
  trailing-whitespace checks; **six local document links** resolve; tracked
  `git diff --check` passes.
- Canonical-LF policy and worker hashes match the boot/child pins. Public/native
  catalogs remain **18/24 entries**. Both host-only candidates stay excluded from
  the actual **31-entry inspection ZIP**, built only in memory.
- The host catalog has **91 entries** (29 code/policy, 20 codec, 37 runtime,
  four input files and the manifest). Static parent-order/layout checks cover
  **94 fixed output files and ten new directories** including the root. These
  are expected/model layouts, not enumerated native installation objects.
- Two real source/installed-codec local reviews reproduce identically in memory:
  **6,484 bytes, 49 entries**, within the 16 KiB review bound. The real snapshot
  test's application/codec import guard passes. These are ordinary read-only
  snapshots, not publisher/protected-runtime authentication or approval of those
  tree digests. No real-input deployment archive was assembled or written.
- Only the seven checkpoint files appear in `git status --short`. Native primitive
  policy/implementation, media-store, guest, protected launcher/installer and
  runtime sources remain unchanged. The one-line host catalog addition and two
  exact dependency-guard extensions are deliberate parts of this checkpoint.

No source or test repair was needed after application. This validation-record
follow-up is **documentation-only**. Passing these models/static checks does not
establish native sharing, effective-token/private-ACL protection, protected
installation/import/DLL confinement, boot compatibility, process/VM watchdog
behavior or final VM absence. The mandatory bootstrap trust boundary remains
unimplemented and this body remains unwired.

## Next actual runnable boundary

1. Review/build the real immutable inputs and code/runtime/codec/bootstrap byte
   snapshots under new installation approval. Preserve provenance/source evidence.
2. Supply the independent fixed protected bootstrap, pre-import verification,
   permanent install claim and process watchdog. Only then may this body be
   considered for a separately approved provisioning attempt. No old inspection
   deployment/claim/root is reused or repaired.
3. Complete the execution-policy/claim channel, diskless exact-owned runner,
   held installed/media identities, independent VM watchdog and bounded evidence.
4. Perform one separately approved native validation attempt or stop with its
   precise blocker. Trusted image/KVP/credential/authenticated-UART integration
   and autonomous Gate A lifecycle observations remain after that prerequisite.

No actual input bundle or ISO was written/copied, protected anchor provisioned,
installation activated, elevation requested, guest executed, VM operated or commit
made during this checkpoint. **Gate A remains unrun.**
