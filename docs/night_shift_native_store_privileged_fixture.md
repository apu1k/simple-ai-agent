# Non-secret privileged host-store profile fixture — failed attempt retained

## Approved execution — 2026-10-19, FAILED; no retry

Exactly one approved request, `2fb426b96a7b4cc99b3df8db3e9bf4a3`, ran under a
requested **120-second** enforced worker limit. The launcher returned `failed`,
exit **1**, with untruncated output. Start-receipt creation to finish was about
**0.889 seconds**; this was a normal failure, NOT a timeout.

Independent ordinary read-back verified the start/result receipts, exact approved
JSON digest, installed helper binding, approved embedded source digest and saved
payload equality. No creation retry was made. A separately approved existing-object
diagnostic is recorded below; it did not rerun the fixture.

- Approved request SHA-256:
  `e00927ca2446621d5ec4da0b2a3a35665f55a05f911593636daf59113d3b474b`
- Complete embedded script SHA-256:
  `41aaea7abbd0f08720e224b67e1fbdb42f25e4f115db07f0a426a1f0761df02d`
- Result-file SHA-256:
  `1a03367dfb4f058d863f1fa8d7051d57e8b87d45a3a4e9334c2de4293fc6271a`
- Receipt:
  `C:\Program Files\AiAgentElevatedCommands\receipts\2fb426b96a7b4cc99b3df8db3e9bf4a3.result.json`

The protected worker reported successful actual Administrators ownership/group,
exact private DACL creation, marker write/read-back, data-sharing refusal with
the metadata-only exception, and enabled-Administrator reading after producer
closure. These are worker observations, not a new independent post-run ACL/hash
attestation of the protected marker.

It then stopped at `filtered_operator_access_after_producer_close` with
`unexpected_access_error`. The failing open was invalid, not an observed access
grant; however, its error did not match the required native 5. The checker uses
`Need(...)`, which discards both the observed native error and requested access
mask on failure. The reported `win32_error=0`/`nt_status=0` are generic checker
fields, NOT evidence that the failed native open returned error zero. We cannot
identify the failing mask/error or claim all six linked-token checks passed.

Collision preservation, held-directory rename, reparse, hard-link and final
preservation checks were NOT reached. SYSTEM/real VM-token tests and the
production Python probe were NOT performed. `production_ready` and
`strict_python_ancestor_policy_passes` remain false.

Independent ordinary-process probes afterward confirmed the retained root exists
(directory attributes 16, one link) and that marker stat plus all six requested
marker access modes were refused with Windows **5**. No data was read/written,
no impersonation was used, and no handle was granted in those probes. They are
NOT a replacement for the failed in-worker UAC-linked-token check. The ordinary
process could not inspect the marker's current bytes/security.

Only the new fixture directory/marker and normal launcher/compiler/audit files
were created by the reached stages. No real credential, VM operation, existing
permission repair, helper installation or cleanup occurred. Objects and all four
request artifacts remain retained. The original script/source/hash bindings are
preserved; do not invoke its `Run()` again or reuse/reset the fixed directory.

Before this execution, the corrected applied review suite passed **6 tests**;
a combined native/related runtime selection passed **167 with 3 symlink skips**.
Repository Ruff, Mypy across **77 source files**, whitespace and bundle exclusion
checks passed. These are pre-execution review results. Several review tests have
an absent-fixture precondition and will now refuse this retained host state; they
must not be represented as a new post-run green suite.

The separately approved existing-object diagnostic below supersedes the earlier
plan for token/error collection. The original creation failure remains failed;
no fix, recreation or claim reset is authorized by either outcome record.
Gate A remains unrun.

## Existing-object diagnostic — 2026-10-19, completed with truncated evidence

Approved request `75de7de500ff4979b85aed4c60538f4b` executed a self-contained,
OPEN_EXISTING-only token/error diagnostic with a **120-second** enforced limit.
It exited **0**; start-receipt to finish was about **0.774 seconds**, not a timeout.
Independent read-back verified approved request bytes, helper binding, saved
payload equality, exit status and the original failed receipt's unchanged hash.
This was a new read-only diagnostic, NOT a creation retry or fixture acceptance.

- Approved request SHA-256:
  `57d1068aebd1e21a8c91b82aa06311ac218814a9663c5183e2ac1a2f84ceb1c6`
- Complete diagnostic script SHA-256:
  `1a9e811620cee0ebaebd2d21a6e87acb3e1fa3f2ae0ed7d1090e7e0ddbb17380`
- Result-file SHA-256:
  `0ad1a3a739c060c94d463c0af5dd8a37dec59ec768e91331ab4a5e160204db9b`
- Receipt:
  `C:\Program Files\AiAgentElevatedCommands\receipts\75de7de500ff4979b85aed4c60538f4b.result.json`

**Evidence limitation:** the existing launcher retains at most 4,000 characters
per stdout/stderr capture. `output_truncated=true`; the saved JSON stops within
`linked_token`, before its probe rows, actual thread token, reversion and final
metadata fields. The full report cannot be recovered from this receipt. Successful
script exit supports completion of its guarded control flow but is not retention
of the missing observations. Do not reconstruct/claim the missing error rows or
final snapshot values. The launcher policy/code was not changed.

Complete prefix sections independently parsed from the saved stdout establish:

- Before-probe directory volume serial `980143452`, file index
  `26740122787629130`, one link, directory attributes 16, and protected DACL
  `O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)`.
- Before-probe marker on that same volume, file index `21392098230126897`, size
  **49**, one link, attributes 32, and protected DACL
  `O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)`.
- The actual elevated process is a full primary Administrator token. All twelve
  Administrator probes (six masks through SafeFileHandle and IntPtr declarations)
  granted handles; no data was read/written. Raw-handle closes reported success.
- The visible part of the linked-token section identifies a type-2 impersonation
  token, limited elevation, medium integrity, restricted status, Administrator
  deny-only attributes 16 and native impersonation level **1**:
  `SecurityIdentification`, NOT `SecurityImpersonation` (native level 2).

That is a concrete validation-method flaw: identity inspection is not authority
to act as the user for file access. Do not fix the test by widening the DACL,
enabling privileges, trying to upgrade the identification token or accepting
arbitrary failure codes as successful ACL checks.

An independent UNELEVATED reproduction duplicated only the ordinary process's
OWN existing filtered token at native levels 1 and 2, without acquiring an
Administrator/SYSTEM/VM token or enabling privileges. It verified the same user
and disabled Administrator membership in both contexts, queried the actual
thread level, and reverted after each case. On the retained marker:

| Local reproduction context | Six masks, both API declarations | Result |
| --- | --- | --- |
| Native level 1: SecurityIdentification | 12 refused opens | **1346**: bad impersonation level |
| Native level 2: SecurityImpersonation | 12 refused opens | **5**: access denied |

This isolates the mechanism under a controlled same-user ordinary-token test;
it is NOT the missing original worker error record and must not be used to
backfill that original error as an observed 1346. No file-data reads/writes, ACL
changes, fixture creations, VM operations or privileged diagnostic retry occurred.
The ordinary tokens were only duplicated to compare levels, not mislabeled as
real VM/capability tokens. The failed fixture and both request artifact sets remain
retained. No real credentials, deployment or Gate A run resulted.

Next source/test work should use an actual ordinary-process access check or an
explicitly verified suitable same-user context, reject identification-only token
use as an unsupported test context, and preserve each native error/mask. Keep
critical evidence first and the complete JSON under the 4,000-character limit;
a larger create-new audit artifact would require its own reviewed scope. No
further privileged action is authorized by this record. Native collision/rename/
reparse/hard-link coverage, SYSTEM/real VM tokens, protected runtime, production
ancestor policy, credential factory and live channel integration remain open.

## Corrected ordinary-process validation — applied and verified

Source `scripts/validate_retained_store_ordinary_access.ps1` and regressions
`tests/runtime/test_retained_store_ordinary_access.py` were applied and verified
without another privileged request, creation attempt or change to V1. The two
validator/review suites passed **41 with 3 intentional retained-V1 execution
skips**. A combined prototype/runtime rerun passed **351 with 6 skips**, including
those 41 tests: three retained-V1 skips and three unavailable symlink cases.
Repository Ruff, Mypy across **78 files**, whitespace/links, production-caller
isolation and actual in-memory inspection-bundle exclusions passed. These are
targeted runs, not a full-repository test result or Gate A validation.

The actual standalone ordinary-process run returned `all_12_denied_error5`.
Its full JSON was captured and parsed: **939 characters / 939 UTF-8 bytes**,
not truncated. All twelve unique mask/API pairs were invalid handles with native
error **5**, so no target handle was granted and no target data was read/written.
The measured actual context before/after was a type-1 primary token, limited UAC
elevation type 3, elevation flag zero, Administrator deny-only attributes 16 and
no thread token (native 1008); the operator SID matched the pinned original
receipt. Context remained stable. Error 5 does not distinguish which ancestor
or leaf security check denied the request; this is an observed access matrix,
not a new privileged target-identity or individual-DACL attestation.

- New script normalized UTF-8/LF SHA-256:
  `0ee3ff7a44ba726acee46267f3bcfc664a3b1f491bd31283ebcd01fd680b5b67`
- New script actual host-file SHA-256:
  `183adbafd512a10a23c460f29faa2f1049a6f58f0f0f1aad5117278602481567`
- Complete normalized JSON value SHA-256 (outer whitespace removed):
  `d23a71ca04a292134d8210e1d2ad0b80a9f48e97d0ae76cdc05c6d89dc7ce2c5`

This ordinary stdout value is NOT a new protected-launcher receipt. Its explicit
`ready`, `recreated`, `data_io` and `target_identity_attested` fields are false;
`original` remains `failed`, and `prior_output` remains `truncated`. Independent
byte-hash read-back before/after confirmed both prior result receipts and the
original V1 source were unchanged. The original V1 embedded digest remains
frozen; no original entry point was invoked. This closes the corrected
ordinary-operator access/reporting check only, not the unrun portions of the
privileged fixture or the production key-store/channel gates.

The new standalone Windows PowerShell/.NET script is UNELEVATED ONLY. It verifies
both exact prior receipt byte hashes, binds the operator SID to the original
failed record, and opens only the fixed retained `probe.bin` with OPEN_EXISTING.
It independently queries the actual process token and rejects any thread token,
unknown thread-query state, non-primary process token, enabled/elevated
Administrator, non-limited UAC context, missing deny-only Administrator group or
wrong operator SID BEFORE target probes. There is no linked-token retrieval,
impersonation, token duplication/upgrade, privilege enabling or broker/service.
The pure context model accepts supplied test facts only for regression testing;
actual validation obtains native facts itself, not from caller-provided booleans.

All six requested access masks are tested through both SafeFileHandle and raw
IntPtr declarations. Each row preserves mask, API, handle-granted flag and exact
native error. Any granted handle is closed WITHOUT reading/writing marker data;
raw close results are retained, including ownership transfer from SafeFileHandle
to avoid double close. Only all twelve INVALID opens with exact error 5 and stable
supported token facts yield `all_12_denied_error5`. Error 1346, sharing violations,
missing files and unknown errors are not accepted as equivalent ACL denials.
The original creation result remains failed, prior output remains truncated and
`ready`, `recreated`, `data_io` and `target_identity_attested` remain false.
An unprivileged denial cannot attest the target's current file identity/security;
the previous privileged before-probe snapshot is separate evidence, not a new
identity assertion by this validator.

The full report uses explicit compact column names/rows and is refused before
output if it exceeds **3,000 characters OR 3,000 UTF-8 bytes**, leaving margin
under the launcher capture's 4,000-character bound. An over-limit result emits
only a fixed bounded failure envelope, not truncated success JSON. Regression
models require complete schema, every unique mask/API pair, exact errors, correct
native context facts and no credential/fixture-acceptance overclaim. They are
report/context tests, not privileged key-store attestation.

Native regression checks compile the full C# and examine process facts without
target access. The retained-host check runs the actual ordinary-process probe
only where both pinned receipts exist and match; otherwise it SKIPS, never creates
fixtures. On this host that check PASSED, rather than skipped, and the standalone
run above separately confirmed its complete output. It makes no marker-data/ACL/
ownership changes and rechecks prior receipt bytes. No elevation/UAC is needed
or allowed for this ordinary validation.

The OLD review tests are also revised to SKIP original direct/embedded execution
when V1 is retained. Pure descriptor/ABI compilation remains runnable, but never
calls the V1 native Run method. This preserves the failed attempt and removes
its host-state-dependent unit-test failures without weakening production guards
or pretending skipped creation cases passed. Original script bytes, receipt
bytes, installed helpers/policy, actual fixture permissions and all claims remain
untouched. The narrow new Git ignore exception includes only the new validator.

## Original purpose and exact scope

This is a separately reviewed fixture following native marker commit `3c786f5`,
not key provisioning, an installer or permission to run Gate A. Source:
`scripts/validate_native_store_privileged_fixture.ps1`; review/refusal tests:
`tests/runtime/test_native_store_privileged_fixture.py`.

The draft uses stock native x64 Windows PowerShell/.NET and embedded, reviewable
C# P/Invoke code. It invokes no Python, application imports, downloaded packages,
services, registry authoring, external jobs or Hyper-V operations. No key,
certificate, password, source/working VHDX, recovery media, saved inspection
claim, original receipt or retained VM is opened or changed. It never edits an
existing ACL, changes ownership, enables a privilege or borrows another process's
token. It writes only the existing prototype's fixed NON-SECRET marker.

**This is a native profile fixture, NOT execution/validation of the Python
prototype's production path. No successful outcome makes credentials or the
inspection channel ready. SYSTEM and real VM/capability-token access remain
unvalidated.**

## Read-only preflight observations

An ordinary, read-only native inventory before drafting found:

- `C:\` is TrustedInstaller-owned. The committed Python prototype deliberately
  accepts only SYSTEM/Administrators ancestor owners and refuses this root.
- `D:\` is SYSTEM-owned but has Authenticated Users access beyond the committed
  prototype's allowed ancestor rights; the prototype refuses that root too.
- The base interpreter is Python 3.14.3 at
  `C:\Users\jul20\AppData\Local\Python\pythoncore-3.14-64\python.exe`.
  Its directory and executable are operator-owned. Neither it nor the repository
  virtual environment is an approved protected privileged runtime.

These observations are not permission to repair either drive root, silently
change the Python policy, or elevate operator-writable Python/dependencies.
The prototype, its ancestor policy and installed helpers remain untouched.

The self-contained fixture uses a separately stated ancestor trust profile:
SYSTEM, Administrators and Windows TrustedInstaller ownership; no untrusted
mutation rights; all ancestors held without delete sharing. TrustedInstaller is
accepted on EXISTING ancestors only, consistent with the installed general
launcher's trusted-Windows boundary, not as an extra private-store reader.
New fixture objects still require exactly Administrators ownership/group and
protected SYSTEM/Administrators-only FullControl DACLs. This policy difference
is explicit and does not replace or attest the Python acquisition policy.
The receipt reports `strict_python_ancestor_policy_passes` separately and always
sets `production_python_probe_executed`, `operator_python_executed` and
`production_ready` to false. Even if the fixture succeeds, the Python path/runtime
blocker must be resolved by later review, not an automatic fallback.

## Fixed new-object boundary

Only this NEW directory and its reviewed children may be created:

```text
C:\Program Files\AiAgentElevatedCommands\receipts\
  native-store-fixture-22bf6d3069d64b7fbc8bd09771dcae6f\
    probe.bin
    held-directory\
    reparse-target\
    reparse-link -> reparse-target (only inside this exact fixture)
    probe-alias.bin (hard link to this exact probe.bin)
```

The rename-refusal test may attempt the additional child name
`renamed-held-directory`; no replace/overwrite flag is used. Unexpected rename
success is a fixture failure, with the new objects retained. Existing-root/name
collisions refuse; no prior attempt is reopened, reset, retried or cleaned up.
There is no recursive deletion or broad enumeration. Parent ancestors are only
queried/held, never repaired. Native compiler/request/receipt artifacts generated
by the separately installed launcher are also retained under its existing policy.

The directory and files are created with owner/DACL in the initial native
`NtCreateFile(FILE_CREATE)` object attributes, not permissively then repaired.
Security, filesystem identity, regular/single-link shape and the ancestor chain
are read back before even the marker is written. The class uses relative child
opens, reparse refusal and sharing rules comparable to the marker prototype,
but is independently implemented and has not yet been validated as applied.

## Intended native observations

1. Actual Administrators-owned directory/file creation, exact protected DACL,
   metadata/identity read-back, marker write/flush/bounded read-back and drift
   refusal. No arbitrary payload interface exists.
2. While the producer file handle is exclusive, real data read/write/read-write
   opens must fail with Win32 **32**, while a metadata-only handle can succeed.
   Sharing is not confidentiality or a replacement for DACL validation.
3. After the producer handle closes, the actual enabled Administrator token
   must open/read the marker and retain its identity/security.
4. Obtain ONLY the current operator's UAC-linked token from its own process token.
   If available, impersonate it briefly on the fixture thread, verify the same
   user SID and disabled Administrator membership, then attempt six new full-path
   opens: data read, data write, delete, READ_CONTROL, WRITE_DAC and WRITE_OWNER.
   All must fail with native **5**, not a sharing violation. No privileged parent
   handle is passed to these access attempts. Always revert; a failed revert
   exits the fixture process immediately with code 70 rather than continuing.
5. Re-create the existing marker with FILE_CREATE: require exact collision status
   `0xC0000035`, then verify the original marker bytes are intact.
6. Attempt to rename only a held, newly created fixture directory: require native
   sharing violation **32**. No overwrite or cleanup is attempted.
7. Create a directory symlink solely to the fixture's own target; require either
   native `STATUS_REPARSE_POINT_ENCOUNTERED` (`0xC000050B`) or successful opening
   of the LINK object followed by shape refusal, never opening the target as if
   it were the link. If symlink creation is unavailable, record it as unvalidated.
8. Add only the exact fixture hard-link alias; require native link count two and
   shape refusal. The two names remain retained; no unlink-to-restore workaround.
9. Recheck held ancestor/store identities and security, close the fixture handles
   and emit bounded non-secret JSON to the launcher's durable stdout receipt.

An unavailable linked token or symlink capability produces an explicit PARTIAL
outcome and failure exit, not a passed access/reparse check. A native error in
any mandatory test is a failure. Partial/failure objects remain retained; no
retry is authorized. Raw guest content, arbitrary exception text, credentials
and unrelated host records are not included in the fixture report.

The report ALWAYS identifies SYSTEM and real VM/capability-token tests as
`not_performed`. It neither obtains those tokens nor constructs synthetic tokens
and mislabels them real. Do not claim SYSTEM/VM effective access from a DACL
shape, a current-user result or this fixture's completion status.

## Original review and execution sequence (historical, not permission to rerun)

**The single execution above failed. Preserve it; do not run manually or retry.**

1. Apply the source, tests and this record. Then run unelevated parsing, full C#
   compilation, descriptor/ABI and refusal checks. Tests must not run elevated;
   native creation/access cases are not exercised by these compile checks.
2. Review the applied source, size and SHA-256. The approved request embeds the
   ENTIRE source verbatim inside `& { ... }` with the explicit
   `AuthorizeNonSecretNativeStoreFixtureV1` switch. The combined request remains
   below 32,768 UTF-8 bytes. The existing launcher hash-binds, snapshots and
   executes that complete request; there is no separate mutable script-path
   load, external application/Python import or compressed/opaque code loader.
   Verify the exact embedded wrapper's parse/refusal checks before requesting
   execution. Keep the source visible in Git via its narrow ignore exception.
3. Separately enable elevation, review/accept the general-launcher request and
   approve UAC. Proposed enforced worker limit: **120 seconds**, covering native
   compilation and all checks. No helper installation or policy edit is needed.
4. Read back the protected launcher receipt and classify completed/partial/failed/
   UNKNOWN. The fixture is process-local, but a watchdog timeout still requires
   independent new-object evidence; it does not prove all intended checks ran,
   what bytes were written or that a receipt was emitted. No automatic retry.

## Earlier applied review checkpoint — before privileged execution

The initial applied review run passed four checks; the C# compile check could
not launch because full-source UTF-16/base64 expansion exceeded Windows'
command-line limit (error 206). Moving only the UNELEVATED test transport to
stdin allowed C# compilation and exposed a PowerShell `Marshal.SizeOf` overload
selection issue in the ABI test, not in the fixture. Testing boxed value-type
instances fixes that assertion. An in-memory corrected harness then passed the
five original checks, including 11 descriptor cases, four ABI layouts and native
ordinary-token refusal, without creating the protected fixture. These are not
results for the still-pending applied harness correction.

The pending test revision uses bounded stdin and adds an ordinary-token refusal
check of the exact full-source embedded execution wrapper. A narrow `.gitignore`
exception is also pending: the initial script was hidden by `/scripts/*` and
must not be accidentally omitted from the source batch. The applied script is
25,727 bytes at this checkpoint. C# compilation is not positive native access,
reparse or ownership evidence; the actual fixture remains unrun. Ruff applies
to the Python tests, while PowerShell parsing applies to the `.ps1` source.

The historical pending harness/ignore revisions described above were applied
before the six-test pre-execution verification and the single failed execution.
They are not current pending actions. The privileged result above supersedes the
earlier statement that the fixture was unrun.

The fixed directory is NOT a real secret store or an inspection claim. It is
never reused as either. A successful fixture addresses only the reported native
profile observations; the approved protected runtime, production Python policy,
SYSTEM/real-VM tokens, credential factory/loading lifecycle, Linux RAM keys, KVP,
serial integration and live image inspection remain separate gates. Gates A/B
remain unrun. No restart is needed to review this source draft.
