# Fresh non-secret native guard checks — four case rows passed; final preservation failed

This follows commit `5c1eaa2` and the [retained fixture record](night_shift_native_store_privileged_fixture.md).
It scopes only the native collision, rename, reparse and hard-link checks that
were not reached in the failed V1 attempt. It is NOT resuming or retrying that
attempt, a credential factory, production-store approval, helper deployment,
image inspection or Gate A.

## Approved execution — 2026-10-19, overall FAILED; no retry

One approved request `b87e24c68c914dbeb46a2c72d946f953` ran under a requested
**120-second** enforced limit and exited **1**. Start-receipt to finish was about
**0.838 seconds**, not a timeout. The saved stdout is **810 characters**, complete
JSON with `output_truncated=false`. The worker reported all FOUR native case
rows passed, then failed at `preservation` with guard code
`identity_security_drift`. Overall `ok=false` remains authoritative; this is NOT
a passed complete fixture.

Independent ordinary read-back verified the start/result receipts, approved
request-byte hash, installed helper binding, exact embedded source hash and
saved payload equality. Both old result receipt hashes and the original V1 source
bytes still match. There was no second elevated request or creation retry.

- Approved request SHA-256:
  `f0886162b837ca31910e51ac97e20e0f8e4bc5493bd9ceb9789f6b9d77539648`
- Complete embedded script SHA-256:
  `9f25e268d29fabc5103a053e9fc1904f5825b66c0347ed895aac545bca8c9bfb`
- Actual source-file SHA-256:
  `b5c963868ec9a6e9c77c5f410f6134b509a991c0d9700cbdd384b45bca09bbc0`
- Result-file SHA-256:
  `ab24c065f4922eb7e9169f4792e9b45cba8c7c341f7cb03d66e316f1671a7ced`
- Receipt:
  `C:\Program Files\AiAgentElevatedCommands\receipts\b87e24c68c914dbeb46a2c72d946f953.result.json`

### Recorded native cases (worker observations)

| Case | Recorded outcome |
| --- | --- |
| Collision | Exact `0xC0000035`, Windows **183**; same file index `007a000000087556`, ACL and marker bytes retained |
| Held-directory rename | Windows **32**; unchanged source index `007500000008755a`, exact destination absence `0xC0000034` |
| Reparse | Tag `0xA000000C`; exact own target validated; guard opened/refused the LINK shape, link index `0078000000087562` distinct from target `007a00000008755c`; NOT a native-status refusal in this run |
| Multiple links | Both names identify index `009b000000087564`, each reports two links; single-link guard refused both, ACL and marker checks passed |

The final failure has `kind=guard`; native error/status/access fields are null,
NOT Windows error zero. This version's `Same(...)` compares directory size as
well as identity, attributes, ACL and link count but does NOT emit the differing
object/field/before-after values. Final ACL/identity preservation therefore cannot
be declared independently passed from its failure report.

An ordinary metadata-only read afterward observed the retained new root at the
same file index `007b000000087550`, attributes **16**, link count **1**, directory
size **4096**. It did not expose protected child bytes or current ACLs.

An UNELEVATED disposable-directory reproduction then used the SAME native
GetFileInformationByHandle/GetSecurityInfo observation path. Adding only new
fixed non-secret entries changed directory size **0 -> 4096**, while native file
identity, owner/DACL, protected flag, attributes and link count remained equal.
An earlier metadata sample also showed no archive-attribute change. This proves
the comparator can reject normal directory growth unrelated to security; it
strongly explains this fixture failure but does not establish the sole differing
field in the unrecorded protected before/after comparison. No protected fixture
object was changed by the reproduction; only ordinary disposable test files were
created/removed. Do not backfill the missing preservation evidence or mark the
old attempt successful.

All newly created fixture objects remain retained, including the symlink and two
hard-link names. No cleanup, ACL/ownership repair, manual privilege enabling,
credential generation, original-marker access, helper update or VM operation
occurred. V1 was neither selected nor reused, and its result remains failed.
`ready=false` and `system_vm_tested=false` remain explicit. Gate A remains unrun.

### Applied review and next work

The corrected applied review suite passed **27 tests without warnings**, with
full PowerShell parsing, C# compilation, descriptor/shape/reparse-data models,
ABI layouts and ordinary authorization/native-entry refusal. The initial review
had two Python path-escape warnings; raw strings and a canonical-path assertion
were applied and strictly rechecked before execution. Repository Ruff, Mypy
across **77 files**, whitespace, links, launcher policy and source/bundle isolation
checks passed during preparation. These review/model checks are not additional
positive native cases or a full-repository run.

Preserve this source/payload/result at their recorded hashes. The next source
review must distinguish directory allocation length from regular-file content
length, retain strict identity/type/reparse/link/attribute/owner/DACL checks, and
record the exact mismatching object/fields within the bounded report. Regular
file size/bytes must not be relaxed to make the directory case pass. Any revised
preservation reader or future fixture needs separate review/approval; no current
namespace reuse, reset or new privileged action is authorized by this record.

## Offline comparator follow-up — verified, no new privileged action

The isolated Python native-store prototype now has an applied metadata-only
comparison correction and new regressions, documented in its
[comparison boundary](night_shift_maintenance_store_native_prototype.md). It
separates directory allocation length from regular-file size and emits bounded,
object/field-specific differences with before/after public metadata. Identity,
kind/reparse, links, attributes, owner/DACL and protection checks remain strict;
only an explicit empty regular-file marker write permits its expected length
and ARCHIVE transition. Reports are comparison-only, not private-store approval.

This does NOT alter the PowerShell source used for the failed run, execute any
old native Run method, access the retained fixture as a test target, create a
replacement namespace, repair permissions or reset a claim. Frozen-source
regressions pin both executed fixture scripts. Native reproduction uses only
current-user temporary files; schema/ACL models are not privileged attestation.
Applied comparison/native-store checks passed **158 with 1 symlink skip**;
combined prototype/runtime checks passed **448 with 6 skips**, including those
158. The native ordinary temporary-directory growth check ran and passed. A
separate ordinary native observation recorded directory **0 -> 4096** as storage
only, while regular-file **27 -> 28** was refused with exact object/field/before/
after diagnostics. All complete reports still have `acceptance=false`.

Ruff, Mypy across **76 night-shift source files**, whitespace/links and bundle/
caller isolation passed. Three saved result-file hashes and both executed-script
source-byte hashes remain unchanged. These are isolated targeted checks, not a
new privileged execution, overall pass of this fixture or production approval.
In particular, no after-the-fact comparison turns this original missing
preservation evidence into a pass.

## Exact separate object boundary

The standalone script is `scripts/validate_native_store_guard_checks.ps1`, with
review/model tests in `tests/runtime/test_native_store_guard_checks.py`.
The only new fixture directory is:

```text
C:\Program Files\AiAgentElevatedCommands\receipts\
  native-store-guards-97aa76c6db034b4ea87c747a38ce60a0\
    collision.bin
    held-directory\
    reparse-target\
    reparse-link -> this same fixture's reparse-target
    links.bin
    links-alias.bin (hard link to this same fixture's links.bin)
```

Only a failed rename experiment may additionally leave the exact child name
`renamed-held-directory`. No overwrite flag is used. Every object remains retained,
including both hard-link names and the symlink. No cleanup/unlink-to-restore step
is included. The new root uses atomic FILE_CREATE and refuses any existing name;
no old or partly created attempt is reopened. An in-process attempted flag is
additional refusal, not a replacement for the persistent create-new boundary.

The ordinary preflight observed the new path absent and both previous result
receipt hashes matching. It created no objects. Native FILE_CREATE, not an
ordinary existence check, is the authoritative collision refusal at execution.

The old V1 root/marker are NEVER selected, opened, changed, linked or renamed by
this script. Only the two old public result receipts are read, hash-bound before
and after. Old source code is neither loaded nor invoked. V1 remains failed and
its consumed resources remain preserved. The previously truncated diagnostic is
not promoted to a complete report or a fixture pass.

## Intended four native checks

1. **Collision:** atomically create a protected new `collision.bin`, verify its
   empty shape/owner/DACL, write/flush/read only the fixed NON-SECRET marker and
   close the producer. A second FILE_CREATE must fail with exact native
   `0xC0000035`; preserve its mapped Windows error. Reopen read-only, verify same
   volume/index, size, attributes, owner/group/DACL and exact bounded marker bytes.
   Any other failure or unexpected handle grant is NOT accepted as collision proof.
2. **Held-directory rename:** create only `held-directory`, verify private shape
   and hold it without delete sharing. MoveFileEx with flags zero may attempt
   only its reviewed sibling name. Require Windows **32**, unchanged held/source
   identity/security and exact native destination-name absence `0xC0000034`.
   Unexpected rename success fails the fixture; retain any resulting child.
3. **Reparse refusal:** create/hold a private target directory and create only the
   reviewed symlink to it. Open the LINK itself without following it and deny
   concurrent write/delete sharing on that link handle. Read its metadata with
   FSCTL_GET_REPARSE_POINT (`0x000900A8`), bound the buffer to 16 KiB, validate
   symlink tag `0xA000000C`, absolute flags, offsets/lengths and exact substitute
   target `\??\` plus the fixed new target path. A print name, if present, must
   match too. A relative, outside, malformed or differently tagged link refuses.
   The relative acquisition guard must then either return exact native
   `0xC000050B`, or open the LINK object and reject its reparse shape. In the latter
   case its volume/index must be the link, not the target. Verify link/target
   metadata remain stable. Access denied or an unrelated native error is NOT
   reparse proof. No symlink privilege is explicitly enabled by the script; an
   unavailable capability makes the case fail, never silently pass or retry.
4. **Multiple-link refusal:** create a separate new private `links.bin` with the
   fixed marker, close its producer and add only `links-alias.bin`. Open both
   read-only; require same original volume/index, unchanged size/attributes/
   owner/group/DACL, exactly two links and exact marker bytes. Require the
   single-link shape guard's specific `multiple_links` refusal for both names.
   Do not delete an alias to make the leaf appear eligible again.

The report records one explicit row per completed case, including native status,
Windows error and proof details/identities. Every mandatory case must complete.
An omitted row is unrun, not passed. Error/guard paths retain stage, reason and
native status/error separately: a guard assertion has null native-error fields,
not fabricated Windows zero. Native relative failures retain requested access.

## Native/private boundary

Use stock native x64 Windows PowerShell/.NET with embedded C#, not operator-owned
Python or a repository import executed as Administrator. Explicit authorization
and actual enabled Administrator membership are checked before compilation.
The native entry point also checks the original pinned operator SID and rejects
any preexisting or unqueryable thread token. There is NO linked-token access test,
impersonation, token duplication/upgrade, privilege enabling or external process
token borrowing. Ordinary-operator denial remains the separate already validated
ordinary-process check, not a reason to use an identification-only token here.
SYSTEM and real VM/capability tokens are not tested.

Existing ancestors use the separately reviewed fixture/launcher boundary:
SYSTEM, Administrators and Windows TrustedInstaller ownership, no untrusted
replacement/ACL/owner/write-EA/attribute mutation rights, no reparse/unsupported
shape and retained no-delete-sharing handles. This does not silently change the
Python prototype's stricter ancestor policy. Require a fixed local NTFS volume
and actual volume-GUID root; use single-component relative NtCreateFile opens
with OBJ_DONT_REPARSE/FILE_OPEN_REPARSE_POINT and fixed child names.

The NEW root, ordinary directories and data files receive Administrators owner/
group and a protected SYSTEM/Administrators-only FullControl DACL at atomic
creation, read back before marker writes. Directory ACEs inherit; marker leaf
ACEs are explicit. The intentionally created symlink inherits the private new
parent's security; it is a rejection fixture, not a private-key leaf. No existing
ACL or ownership is repaired. The intentionally multi-linked file is likewise
ineligible for a secret store and never reused as one.

Only the two new marker files' constant bytes and the new symlink's bounded
metadata are read/written. No arbitrary payload, key, certificate, password,
VHDX, ISO, original marker data or guest-selected path participates. No VM,
service, registry, scheduled task, helper installation, process launch, networking,
source disk operation or consumed-claim reset is included. Normal launcher/native
compiler/audit artifacts are the only allowed additions outside the new fixture.

At completion, recheck all held ancestor and new-root metadata/security against
their baselines; close held handles. This does not promise safety against a
malicious trusted Administrator or a secure erasure guarantee. All fixture data
and failed artifacts stay retained. No background operation or automatic retry.

## Bounded output and validation

The complete JSON is capped at **3,000 characters AND UTF-8 bytes**, below the
known 4,000-character capture limit. Over-limit output emits only a fixed bounded
failure envelope and failure exit. Do not enlarge/change the installed launcher
or save unreviewed extra evidence files as an automatic workaround. Successful
fixture rows still have `ready=false`, `original=failed`, `v1_reused=false` and
`system_vm_tested=false`; they are not production key-store/image acceptance.

Proposed regression checks cover full PS parsing/C# compilation, authorization/
ordinary-token refusal, descriptor and shape models, bounded reparse-data models,
native ABI layouts, complete/missing/wrong native proof rows and report bounds.
They do NOT run the positive privileged fixture. The ordinary native entry-point
check must fail BEFORE root acquisition or creation. Tests skip rather than run
with elevation. A synthetic report or reparse buffer is not real filesystem
behavior. No positive native result is claimed until separately approved execution.

## Original review and execution sequence (historical; do not rerun)

**The fixed namespace is now occupied and retained. The single run above failed
its final preservation guard. No retry, source replacement or cleanup is approved.**

1. Apply this source/test/documentation batch. Verify applied parsing/compilation,
   refusal/model/report checks, typing/lint, exact size and source digest. Confirm
   prior source/receipt preservation and that no production bundle imports it.
2. Review the exact new resource boundary, including symlink/hard-link creation
   and possible retained rename destination. No elevation is needed for review.
3. After successful verification, separately enable elevation and approve the
   full source embedded verbatim in the general launcher's request, not a mutable
   script path or opaque loader. Proposed worker ceiling: **120 seconds**, including
   compilation, creation and all checks. No protected installer update is needed.
4. Independently read back the protected request/payload/result, require complete
   untruncated JSON and classify every row. No creation retry on failure/collision.
   A timeout is UNKNOWN until separately reviewed state evidence establishes what
   happened; it does not prove all handles/resources stopped or any checks passed.

No restart is needed. V1 remains preserved whatever this separate fixture does.
The production runtime/ancestor policy, key factory/loading, Linux RAM-key/KVP
bootstrap, serial adapters, live inspection/image acceptance and Gate A remain
separate unresolved work. No real credentials or live model work are authorized.
