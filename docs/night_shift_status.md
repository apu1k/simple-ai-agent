# Night-shift implementation status and validation gates

## Current Gate A channel review — 2026-10-18 (Gate A unrun)

The [COM1 security review and proposed channel boundary](night_shift_pipe_security_review.md)
records the retained V2 diagnostic requests, native identity review and remaining
trust requirements. The general Administrator launcher has its deployed/tested
900-second maximum; the fixed inspection/evidence helpers have not received the
new timeout deployment. V2's inspection claim remains consumed. No accepted base
image, successful automated guest inspection or Gate A/B completion is claimed.

Separately approved diagnostic `7223f9c08a7d4295bf28f78cfdf438e1` preserved ten
backups and captured the actual pipe ACL without guest data transfer or handshake.
It completed in 507 seconds under a requested 900-second worker ceiling. The
observed broad grants include Everyone pipe-data read, Hyper-V Administrators
full control and a capability SID now exactly identified by the Windows native
API as `VmWorkerProcess`. That name binding is not a VM-specific identity or
permission to trust the capability. The local Hyper-V Administrators group had
zero direct members at review; this is not a permanent membership guarantee.

Fresh read-only post-run inventory `251a7132d6ea4fd7ba89ade6772d5cb1` observed the
exact retained VM and source-referencing VM Off, both VHDXs unattached/parentless,
zero checkpoints and no network adapters. `AutomaticCheckpointsEnabled` was true
alongside `CheckpointType=Disabled`; future fresh-VM setup needs explicit
read-back of both controls. No retained configuration was repaired. Protected
final hashing reported source/copy matching the reviewed source digest; all ten
backups were independently rehashed and protected-path checked.

The plaintext ACL check remains correctly fail-closed. Disposable unelevated
pipe experiments reproduced that late DACL tightening does not revoke an already
granted read handle, even with maximum/current instance counts both one. Do not
blindly widen the allowlist or add an automatic pipe-permission repair. Next is
a reviewed offline authenticated/encrypted-channel prototype, including credential
provisioning/effective-ACL review and bounded failure tests, or a separately
reviewed creation-time-private/VM-bound transport if its prerequisites cannot be
established. This design work does not authorize another VM start, inspection,
protected deployment, claim reset, finalization, publication or Gate A run.

### Standalone offline TLS prototype (not wired to inspection)

The [memory-only prototype boundary](night_shift_maintenance_tls_prototype.md)
describes a standard-library TLS 1.3/mutual-certificate/peer-pin endpoint and
synthetic certificate fixtures. This is a standalone source/test batch, not a
protected deployment or an enabled serial transport. It does not relax the
plaintext ACL check or modify the existing runner, guest payload, bundle list,
claims or tools. Its cooperative deadline checks are not the native watchdog.
Commit `54ca6a9` records the applied prototype. Its own suite passed **78 tests**;
separate related runtime/native checks passed **82 tests**, and maintenance/guest/
bundle checks passed **78 with 1 existing skip**. Repository Ruff, Mypy across
74 night-shift source files and isolation checks passed. These are targeted
offline results, not live channel validation. The real inspection bundle excludes
the prototype and test-only crypto dependency. Credential/media ACLs, host/guest
adapters, real cancellation and live inspection remain unvalidated. Do not restart,
enable elevation or run an installer for this prototype. Gates A/B remain blocked.

### Offline credential boundary and public bootstrap candidate

The [credential/bootstrap design](night_shift_maintenance_credentials_design.md)
records a read-only ACL review: retained VM media/workspace have `VmWorkerProcess`
read/full-control grants, so key secrecy there is not established. The proposed
separation keeps controller private keys in a new protected host-only store and
guest private keys in guest RAM; no private key goes on media or through KVP.
A VM-bound guest-originated KVP public-certificate record is a candidate only.
Its actual Linux publisher, trusted exact-VM WMI acquisition, production host
key-store provisioning/effective-token validation and host/guest adapters remain
unimplemented. Commit `fbc4669` records the offline ACL model/public-record
codec/latch; they have no native acquisition, credential generation or
authorization power.
No live credential, protected directory, media, service, registry setting, claim
or retained ACL was created/repaired by the review. Synthetic feasibility keys
were used only in test-process memory. Gates A/B remain blocked.

### Isolated native host-store marker prototype (not credential provisioning)

The [native marker prototype boundary](night_shift_maintenance_store_native_prototype.md)
proposes Windows relative-handle create-new with an initial protected owner/DACL,
strict ancestor/anchor checks, no delete sharing, exclusive leaf sharing and
repeated native identity/security/shape read-back. It writes only a fixed
NON-SECRET marker, accepts no private-key bytes and has no production caller,
CLI, protected deployment or inspection-bundle integration. It never repairs
permissions, reopens an old store, retries or deletes retained evidence.

The corrected applied policy/mocked/native suite passed **88 with 1 skip**.
The combined TLS/credential/marker rerun passed **237 with 1 skip**, including
those 88 tests. The initial run's **84 passed, 1 failed, 1 skipped** exposed a
sharing-fixture mistake: it requested metadata rather than file data. The applied
regression now separately verifies data read/write/read-write refusal with native
error 32 and allowed metadata-only access; unexpected handles are closed. Four
earlier independent disposable checks confirmed these semantics. No runtime
access policy was relaxed. Sharing is not DACL/effective-token protection.

Separate related runs passed: maintenance/guest/control/bundle tests **122 with
1 skip**; runtime/pipe-security tests **81 with 2 skips**. Repository Ruff and
Mypy across **76 source files** passed after correction, along with whitespace,
local links, marker-only API, source-import isolation and actual in-memory
bundle exclusions. This validates the isolated source/test batch within the
stated fixture limits, not credential provisioning/deployment or a full-repository
suite. No inspection bundle was written.

Native positive fixtures explicitly substitute current-user ownership and acquire
only disposable test-owned parents; they do not validate production ancestor
acquisition, Administrators-owner creation or VM/capability restricted-token
access. The reparse fixture skipped because unelevated symlink creation was
unavailable. No positive production probe, protected anchor or real credential
was created. A pinned credential factory/runtime is still unselected; development
crypto is not a deployed dependency. Synchronous native calls do not supply
watchdog/cancellation enforcement. No restart, elevation, protected installation,
VM operation or claim reset occurred. Gates A/B remain blocked.

### Non-secret privileged profile fixture — 2026-10-19, failed/retained

The [fixture execution record](night_shift_native_store_privileged_fixture.md)
records approved request `2fb426b96a7b4cc99b3df8db3e9bf4a3`, which exited **1**
under its requested **120-second** native ceiling. Start-receipt to finish was
about **0.889 seconds**, not a timeout. Independent read-back verified the
approved bytes, complete embedded-source digest, payload and protected receipt.
Creation was not retried. A separate existing-object diagnostic is recorded below.

The protected worker reported actual Administrators owner/group, exact private
DACL creation, marker write/read-back, data-sharing/metadata behavior and enabled
Administrator reading. It then failed at the UAC-linked filtered-token check with
`unexpected_access_error`. Its checker discarded the actual native error and
requested access mask, leaving generic zero error fields. These do NOT mean the
native call returned error zero. The failing open was invalid, not a reported
access grant; full linked-token access validation remains unresolved. Later
collision/rename/reparse/hard-link/final-preservation tests were not reached.

Separate ordinary-process no-mutation probes confirmed the new directory exists
and all six requested marker access modes fail with native error **5**. These
are not substitutes for the failed in-worker linked-token check or independent
current marker ACL/byte evidence. The new directory/marker and request artifacts
remain retained; no permissions, claim or VM was repaired/reset/operated. SYSTEM
and actual VM/capability tokens were not tested. The Python runtime and ancestor
policy blockers remain. No real credentials or deployment were produced.

Pre-execution applied review passed **6 tests**; combined native/runtime checks
passed **167 with 3 symlink skips**; Ruff, Mypy across **77 files**, whitespace
and bundle isolation passed. Review tests with an absent-fixture precondition now
refuse this retained host state. Gate A remains unrun.

Separately approved existing-object diagnostic `75de7de500ff4979b85aed4c60538f4b`
exited **0** under a **120-second** ceiling (about **0.774 seconds** start-receipt
to finish). Its verified saved stdout is truncated at **4,000 characters**, before
the linked-token probe results/thread/reversion/final snapshot fields. Do not
claim the missing observations or treat exit 0 as a passed creation fixture.
The complete retained prefix includes before-probe exact protected DACLs and
file identities, twelve granted Administrator handle probes without data I/O,
and a restricted/limited linked token at native **SecurityIdentification level
1**, not SecurityImpersonation level 2. This identifies a test-context flaw;
permission broadening is not the remedy.

A separate unelevated same-user reproduction duplicated only its own ordinary
filtered token at levels 1 and 2. All six masks through both API declarations
were refused: **12 error-1346 results at level 1**, versus **12 error-5 results at
level 2**, with identity checks and reversion. This demonstrates the mechanism,
not the unretained original worker error values. Both original attempts and
objects remain preserved; no fixture retry, ACL/ownership repair, privilege
enabling, VM operation or credential generation occurred. Next is corrected
validation context plus compact complete error/evidence reporting, not another
unreviewed creation attempt. SYSTEM/real-VM tests and all live gates stay open.

The separate UNELEVATED ordinary-access validator and regressions are now applied
and verified. The validator binds both pinned receipts/operator SID, queries the
actual limited primary process token with no thread impersonation, and preserves
all twelve native mask/API/error rows. Both the retained-host test and a standalone
run passed: **all 12 opens denied with exact error 5**. The actual context remained
primary type 1, limited elevation type 3, elevation zero, Administrator deny-only
attributes 16 and no thread token (1008). The complete JSON is **939 characters /
939 UTF-8 bytes**, well below its 3,000-character/byte cap and the launcher limit.

The two validator/review suites passed **41 with 3 intentional retained-V1 skips**.
Combined prototype/runtime checks passed **351 with 6 skips**, including those
41 tests; the other three skips concern unavailable symlink cases. Repository
Ruff, Mypy across **78 files**, whitespace/links and actual bundle isolation
passed. These are targeted results, not a full-repository test run.

No linked-token retrieval/upgrade, marker-data I/O, object creation, permission
change, privileged request, deployment or Gate A run occurred in this corrected
check. It explicitly does NOT attest current target identity or production
readiness. Both old result receipt hashes and original V1 source bytes remain
unchanged. V1 execution tests skip against retained state while descriptor/ABI
checks run without invoking V1. The ordinary-operator access/reporting check is
now established for this retained marker, not the still-unrun privileged-fixture
cases or the production runtime/key-store/inspection channel. Gate A remains
unrun.

### Separate fresh native guard-check fixture — four cases passed; final guard failed

The [new guard-check scope](night_shift_native_store_guard_checks.md) isolates the
four unreached cases: exact create-new collision preservation, held-directory
rename refusal, a verified self-contained symlink/reparse refusal and two-link
rejection. It selects only the NEW fixed namespace
`native-store-guards-97aa76c6db034b4ea87c747a38ce60a0` under protected receipts.
V1 source/objects are not selected, resumed, reset or retried. Old result receipts
are read/hash-checked only; no old marker data is used. All new non-secret objects,
including the symlink and both hard-link names, remain retained.

Approved request `b87e24c68c914dbeb46a2c72d946f953` ran under a **120-second**
ceiling and exited **1** after about **0.838 seconds** start-receipt to finish,
not a timeout. Its **810-character** stdout is complete, untruncated JSON. Native
case rows all passed: collision `0xC0000035`/183 with identity/ACL/bytes preserved;
rename refusal 32 with destination absence; verified own-target symlink acquired
as the LINK and refused by shape; and matching two-link identities refused by
the single-link guard. These are worker observations, not an overall fixture pass.

The final `preservation` guard failed with `identity_security_drift`. It compared
directory size exactly but did not emit the differing object/field snapshots.
An independent ordinary native reproduction observed directory size **0 -> 4096**
from adding entries, with identity, ACL, protection, attributes and link count
stable. The retained root now reports the same recorded index, attributes 16,
one link and size 4096. This demonstrates a directory-size comparison bug and
strongly explains the failure, but the missing protected fieldwise comparison
cannot be backfilled as a pass. Overall `ok=false` remains unchanged.

Independent read-back verified the approved bytes, payload/script hash and receipt.
Both old result receipts and V1 source bytes remain unchanged. All new objects
are retained; no retry, cleanup, existing ACL/ownership repair, manual privilege
enabling, real credentials, helper update, VM operation or production integration
occurred. SYSTEM/real-VM tests and production readiness remain false.

Before execution, corrected applied review passed **27 without warnings**; Ruff,
Mypy across **77 files**, whitespace/links, exact source/policy and bundle isolation
passed. These are targeted review/model checks, not another native pass or a
full-repository suite. Next is type-aware directory-versus-file preservation and
bounded fieldwise failure evidence, while preserving the failed run and keeping
regular-file size/bytes and all security/identity checks strict. No revised reader
or future creation attempt is authorized by this outcome record. Gate A remains
unrun.

The OFFLINE-only comparator correction is now applied in the isolated native
marker prototype, with schema/report and disposable native regressions. Directory
storage-length changes are recorded rather than treated as regular-file content;
file lengths stay strict, as do identity, kind/reparse, links, attributes,
owner/ordered ACL and protection. Only the fixed empty regular-file marker-write
context may expect a new length/ARCHIVE transition. Bounded 3,000-character/byte
comparison-only reports name each object and exact changed fields, with scalar
before/after values and ACL fingerprints rather than raw SDDL.

Applied comparison/native-store suites passed **158 with 1 symlink skip**. Combined
prototype/runtime checks passed **448 with 6 skips**, including those 158 tests:
three retained-V1 skips and three unavailable symlink cases. The actual ordinary
native directory-growth test passed. A separate native observation recorded
storage **0 -> 4096** without metadata drift and refused regular-file **27 -> 28**
with exact `temp_file`/`file_size` diagnostics; both complete reports explicitly
retain `acceptance=false`. This does not validate directory contents or acquire
production key-store authority.

Repository Ruff, Mypy across **76 night-shift source files**, whitespace/links and
actual bundle/caller isolation passed. Independent read-back confirmed all three
result receipt hashes and both executed PowerShell source hashes unchanged. The
launcher was verified, not modified. Only ordinary disposable test data was
created/changed; no protected fixture data, ACL, claim, deployment or VM was
modified and no new privileged request was made. Neither failed execution is
rewritten or reclassified as passed. These are targeted isolated checks, not a
full repository suite, accepted image, live inspection or Gate A result.

## Historical V2 preparation — 2026-10-17 (Gate A unrun)

The general Administrator launcher and multiline pending-review UI are live-tested.
This removes the elevation workflow blocker, not the guest-image or Gate A gates.
The [protected inspection record](privileged_image_inspection.md) now consolidates
the retained October 13 CHANNEL failure and fresh October 17 read-only evidence.

Fresh approved inventory observed the exact retained inspection VM
`51434da9-9168-428a-8624-72a246ccc18d` Off with matching identity/configuration,
fixed 2 GiB RAM, 2 CPUs, no network adapters/checkpoints and GSI disabled. The
source's referencing VM was also Off. Source and failed-inspection copy were
unattached, parentless dynamic 20 GiB VHDX files. Fixed evidence collection
rehashed source and ISO: both match their reviewed bindings. The occupied private
V1 workspace correctly reports `workspace_not_empty`; about 253 GiB was free.
These snapshots do not attest guest contents, pipe ACLs or launch permissions.

The first inspection installation still has its consumed claim and expired
approval. Its 69 pinned files match and no extra payload/runtime files were found;
it has not received the later channel diagnostics. Repository preparation now
selects only a fixed side-by-side V2 installation and requires explicit new-attempt
authorization at setup. It does not install V2, extend V1, reset claims or approve
a VM launch. Preserve V1 and all failed resources at their original paths.

Next: review/test/commit the V2 preparation; separately authorize its fresh private
workspace and protected deployment; obtain inspection-only evidence with current
diagnostics. Then separately review copy-only finalization, filesystem/security
audit, accepted publication and the actual serial/pipe policy before Gate A.
No clean accepted base exists, no successful automated inspection is claimed,
and Gates A/B and live model work remain **BLOCKED**. No VM lifecycle action,
mount, permission repair, source change or claim reset occurred in this inventory.

## Historical image-preparation handoff — 2026-10-09 (Gate A unrun)

The detailed [image diagnostic record](night_shift_image_diagnostic_record.md)
separates saved host receipts, operator-console observations and pending work.
Three earlier failed installer candidates remain retained. A fourth identity,
built from commit `48343aa`, passed both native `/target` audits and manual review
release; saved logs show curtin/post-install success and automatic power-off.
An unmasked installed boot then failed in the serial bootstrap with an I/O error
before cloud-init finalization. No protocol task/result exchange was captured.

A separate isolated recovery VM inspected a post-boot copy, then booted that copy
after approved offline service masking and temporary root tty9 preparation.
The operator observed ext4 installed root, worker `masked`/`inactive`, completed
cloud-init `DataSourceNone` with all stages finished and no errors/recoverable
errors, and the intended root-owned disable marker. Root/worker passwords remained
locked; worker identity/groups/home/shell matched policy; no UID 1000–65533 account
appeared and OpenSSH server was not installed. Root authorized_keys was empty;
generated SSH host keys still existed and require hygiene. The operator reports
the diagnostic copy VM OFF after orderly shutdown. Original disks, backups, media,
claims and the original `018` lock remain retained; no fresh agent-side OFF
inventory is implied by that console report.

**No cleaned/frozen accepted base or final digest exists.** Temporary root access,
worker mask, guest-generated keys and machine/log/cache state must be removed or
restored in a reviewed offline copy-only procedure. Normal COM1/pipe behavior and
permissions, protocol responses and real lifecycle/cleanup remain unvalidated.
Gates A/B and live model jobs remain **BLOCKED**. This initialized diagnostic
copy is not a successful Gate A run or acceptance of the original source disk.

Code-review disposition: earlier repository fixes addressed LF packaging, the
seed-unmount cwd and bounded review workflow. Later state/ACL/firmware/ejection
errors were external one-shot operator-helper defects; first-boot masking is an
explicit preparation prerequisite, not a reason to remove failure power-off or
blindly add cloud-init ordering to the generic worker. The exact observed serial
I/O operation/hardware cause is still unknown. Offline `main()` regressions cover
open/read EIO, early EOF, channel closure, success and both unit power-off actions;
no guest runtime asset changes are needed for this documentation/test batch.

Pre-proposal focused validation of the new tests in temporary fixtures plus the
existing bootstrap/bundle tests: **11 passed, 1 skipped**, with real Hyper-V opt-in
explicitly disabled; Ruff on the new test file passed. The skip is the Windows
symlink fixture, not successful native serial/termios validation. No full-suite
rerun or new VM, mount, media/ACL change, WSL use, paid call or guest execution is
claimed for this documentation/code-review step. Historical commit results below
retain their original scope and are not current-state image attestations.

Next: preserve completed diagnostic evidence; approve offline hygiene and
restoration, audit/export a fresh read-only/private hash-pinned base, then review
the actual serial binding/pipe policy before separately authorizing Gate A.
Documentation/tests will advance the Git commit, not the payload bytes; future
host procedures must bind the new reviewed clean commit without rewriting old
receipts or rerunning their permanent claims.

## Commit 01 observed baseline

- Checkout HEAD when inspected: `6ea7f75` (`feat(settings): add max OpenAI reasoning effort`); prior commits `3a04eb0`, `ad9b864`. `git status --short` returned no changes. The handoff's previously modified `config/knowledge.yaml` and `tools/knowledge/config.py` were clean when checked; do not bundle unrelated future changes.
- `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py`: **109 passed, 1 skipped** (non-real-host tests only; one skip inside selected tests).
- `python -m ruff check .`: **All checks passed!**
- `python -m mypy night_shifts`: **Success: no issues found in 37 source files**.
- `git diff --check`: exit 0, no output on the initial clean tree.
- No real VM, real-host validation, image inspection, model call, host reconfiguration, or paid inference was run. These results do **not** establish isolation or an end-to-end coding result.

## Commit 02 offline preparation

The [Gate A preflight and resource-enforcement matrix](night_shift_hyperv_preflight.md) records what must be reviewed and observed on an approved real host. The opt-in suite is extended to check rejected-objective failure, deliberate disconnect after the guest sleep event, host-observed VM absence, differencing-disk removal, and exact-ID reconciliation. No VM/image has been launched or inspected as part of this preparation. The test file remains opt-in; local/fake tests do not complete Gate A. Post-edit offline checks: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **109 passed, 1 skipped**; `python -c "import os, pytest; os.environ.pop('NIGHT_SHIFT_HYPERV_INTEGRATION', None); raise SystemExit(pytest.main(['-q', 'tests/night_shifts']))"` — **109 passed, 2 skipped** (the opt-in module was skipped); `python -m ruff check .` — **All checks passed!**; `python -m mypy night_shifts` — **Success: no issues found in 37 source files**; `git diff --check` — exit 0. The opt-in file was AST-parsed, not exercised against Hyper-V. Record any real-host outcomes in a later status update; do not replace **BLOCKED** with PASS without operator-authorized evidence.

## Commit 03 offline contract (locally validated; real gates blocked)

The [tool-session protocol contract](night_shift_tool_session.md) and fake-transport tests define a host-managed, job/sandbox/session-bound model tool facade separate from the old whole-task channel. There is no real serial tool adapter or guest responder yet. Do not infer VM confinement or real transport timeout behavior from fake-transport tests. Post-edit checks: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **138 passed, 1 skipped**; `python -m ruff check .` — **All checks passed!**; `python -m mypy night_shifts` — **Success: no issues found in 38 source files**; `git diff --check` — exit 0. These are offline tests only; Gates A and B remain **BLOCKED**.

## Commit 04 offline implementation (validated locally; real gates blocked)

The [fixture snapshot transfer design and limits](night_shift_snapshot_transfer.md) describe exact approved Git-object export without checkout, bounded and hashed text snapshots, a fake-serial guest load/fixed check/output/report and exact-ID cleanup attempt on failure. The Linux `openat` installer success case is **not executed on this Windows host**; two Linux-only tests are skipped. No VM, reviewed guest image, real named-pipe tool adapter, image build, real-host data transfer, live inference or durable review bundle was run. Gate A and Gate B remain **BLOCKED**.

Observed post-edit commands: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **156 passed, 3 skipped**; `python -m ruff check .` — **All checks passed!**; `python -m mypy night_shifts` — **Success: no issues found in 41 source files**; `git diff --check` — exit 0. The opt-in real-host file was explicitly excluded. A full `python -m pytest -q tests --ignore=tests/night_shifts/test_hyperv_real_host.py` and `python -m pytest -q tests/tools` each exceeded the shell tool's 30-second limit; neither is counted as a passed run. Non-overlapping split runs: `tests/core tests/adapters` — **63 passed**; `tests/editing tests/runtime` — **49 passed**; `tests/llm` — **62 passed**; `tests/tools/fs` — **45 passed**; `tests/tools/knowledge` — **84 passed, 1 failed, 1 warning**; `tests/tools/system` — **39 passed**. The one knowledge failure is `test_missing_config_uses_default_enabled_synthesis`: unchanged `tools/knowledge/config.py` defaults to `gpt-6-luna`, while the test expects `gpt-5.6-luna`. This is outside the night-shift change; do not modify or include unrelated knowledge configuration in this step.

## Commit 05 offline guest tools (historical pre-commit snapshot; committed as `5c3a882`)

HEAD when inspected: `b86d05a`, Commit 04's offline transfer fixture. The working tree contains only Commit 05 guest-tool and documentation edits; no real VM or model call was run. The first post-approval run of `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` reported **159 passed, 6 failed, 4 skipped**. Two failures were Windows newline-conversion assumptions in new test fixtures; four were historical fake-inference tests still advertising the old two-tool profile. `python -m ruff check night_shifts tests/night_shifts` passed; `python -m mypy night_shifts` found **6 errors** in the new repository facade's Windows-visible typing; `git diff --check` passed. After the first fixes, the same night-shift command reported **164 passed, 1 failed, 4 skipped**; the remaining failure was a historical LLM adapter test assuming `run_command` is the first tool. `python -m ruff check .` and `python -m mypy night_shifts` both passed (42 source files); `git diff --check` passed. After the final fixture correction, `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **165 passed, 4 skipped**; `python -m ruff check .` — **All checks passed!**; `python -m mypy night_shifts` — **Success: no issues found in 42 source files**; `git diff --check` — exit 0. These are offline results only, not Gate A/B completion. Split non-overlapping suites: `python -m pytest -q tests/llm tests/runtime` — **79 passed**; `tests/core tests/adapters tests/editing` — **95 passed**; `tests/tools/fs tests/tools/system` — **84 passed**; `tests/tools/knowledge` — **84 passed, 1 failed, 2 warnings**. The knowledge failure is the pre-existing default-model mismatch recorded above, unrelated to night shifts. Windows fake/filesystem tests do not prove Linux openat confinement, process-tree cleanup, VM isolation, or a usable live tool channel.

Gate A and Gate B remain **BLOCKED**. The real serial adapter and deployed guest tool responder do not exist yet; do not run live coding tasks. Linux dirfd success, process-group/descendant cancellation and guest service OS hardening are not established by the Windows offline suite. Commit 05 was subsequently committed as `5c3a882`; no real-VM or model evidence is claimed.

## Commit 06 offline executor/result semantics (committed as `99ceeb8`)

Pre-edit HEAD `40788a3`, clean working tree. Baseline `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py`: **165 passed, 4 skipped**. Extracted the location-neutral model loop with a guest compatibility import. A final model response is `submitted`, not verified success; an explicit `BLOCKED: ` reason is `blocked`, mapped to the existing failed job lifecycle with a separate event outcome. Legacy whole-task `success` is retained. `WorkerResult` now has independent check, human review and cleanup statuses; older version-1 result frames without these optional fields decode with conservative defaults. This does not upgrade older decoders to understand new outcomes; deploy host/guest protocol readers together if using new outcome values across that boundary. The service persists the distinct statuses in its terminal transition event, not yet as dedicated SQLite columns. No schema migration was needed for this additive event/JSONL change; persisted job summaries remain just summaries.

Post-edit offline checks: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **183 passed, 4 skipped**; `python -m pytest -q tests/core tests/adapters tests/editing tests/runtime tests/llm` — **174 passed** (run after the initial extraction; the later hardening changed only the executor and night-shift tests); `python -m ruff check .` — **All checks passed!**; `python -m mypy night_shifts` — **Success: no issues found in 43 source files**; `git diff --check` — exit 0. Fake models/tools and historical guest-loop fixtures only; no real VM, model call, image validation or isolated sandbox tool service was used. Gates A/B remain **BLOCKED**.

## Commit 07 budget/usage groundwork (committed as `414551c`; live gate still blocked)

Pre-edit HEAD `99ceeb8`, clean working tree. Offline baseline: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **183 passed, 4 skipped**. Value-only job policy snapshots pin repository/revision, image digest, model/provider IDs, plan, tier, reasoning, profile, sandbox and bounded persisted job budget. New budget JSON keys load defaults from older records (no table migration). The policy derives bounded executor and gateway request/input/output limits, but is not wired to a live backend. Provider-neutral usage reports total input/output with cached/reasoning subsets and unknown categories; host OpenAI-compatible clients expose last-response usage where present. A cooperative monotonic control detects cancellation/deadline **between** synchronous operations, not during stalled calls. Live policy preflight refuses every dispatch while hard cancellation is missing; `NightShiftService.run_local` now rejects any strict-USD budget before even the historical backend runs. There is no trusted pricing, retry reservation, live transport or hard USD guarantee.

Observed offline checks after final service/deadline hardening: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **216 passed, 4 skipped**; `python -m pytest -q tests/llm tests/runtime` — **81 passed**; `python -m ruff check .` — **All checks passed!**; `python -m mypy night_shifts` — **Success: no issues found in 44 source files**; `git diff --check` — exit 0. Other non-overlapping groups run before final service/deadline-only hardening: `python -m pytest -q tests/core tests/adapters tests/editing` — **95 passed**; `python -m pytest -q tests/tools/fs tests/tools/system` — **84 passed**; `python -m pytest -q tests/tools/knowledge` — **89 passed, 1 Qdrant compatibility warning**. These are fake clocks/providers and offline tests, **not** hard-cancellation or VM isolation evidence. No paid model call, real VM, image inspection or host reconfiguration was run. At the time of this initial groundwork commit, Commit 07 acceptance was **not fully met**: there was no supervised inference subprocess/cancellable I/O, per-call SDK/Flex remaining-time propagation, priced pre-dispatch reservation, or full live backend. The offline follow-up below adds process isolation and worker-only SDK bounds; priced strict USD and real VM/tool transport remain blocked. Do not enable live jobs or claim Gate A/B completion.

## Commit 07 follow-up: killable host inference and worker SDK bounds (committed as `b5c19a2`)

Starting HEAD `414551c` with a clean working tree. One trusted host inference child per job now retains its model/Responses continuation state; parent JSON frames are bounded, invalid/replayed/malformed data fails closed through the gateway, and cancellation or a monotonic deadline kills and reaps the child (no daemon-thread cancellation claim). The host job wrapper verifies task, sandbox session and gateway model/profile/job binding, checks the sandbox command/deadline limits against the approved job policy, attempts both inference and tool-session cleanup even when callbacks fail, and does not mark VM cleanup clean before a backend observes destruction. An administrator-owned provider profile supplies credentials only to the spawned host child; unapproved IDs or silently ignored Flex/reasoning endpoints fail closed. Worker-only OpenAI Chat/Responses SDK calls disable automatic/semantic retries, bound generation tokens, and propagate remaining monotonic time including Flex and Responses tool continuations. Old head-agent SDK behavior remains unchanged. Strict USD jobs **remain blocked** without audited pricing and pre-call reservations; missing/billed-after-cancel usage remains explicitly unknown. The legacy whole-task backend is preserved.

Offline evidence after final binding tests: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **235 passed, 4 skipped**; `python -m pytest -q tests/llm tests/runtime` — **84 passed**; `python -m ruff check .` — **All checks passed!**; `python -m mypy night_shifts` — **Success: no issues found in 47 source files**; `git diff --check` — exit 0. Other non-overlapping groups run before the final inference-binding-only edit: `python -m pytest -q tests/core tests/adapters tests/editing` — **95 passed**; `python -m pytest -q tests/tools/fs tests/tools/system` — **84 passed**; `python -m pytest -q tests/tools/knowledge` — **89 passed, 1 Qdrant version-compatibility warning**. These are offline fake-model/fake-transport tests and local host process tests, not real VM isolation, guest command-tree cancellation or a paid inference run.

Limits not established by this step: no real Hyper-V named-pipe tool transport/service or end-to-end host-managed backend yet; VM provisioning, retrieval and destruction still lack a unified live deadline/cleanup supervisor. A cancelled provider call may still be billed; SDK/client cooperation cannot prove account-level cost. Strict USD dispatch continues to fail closed. Real Gates A/B remain **BLOCKED** and no live jobs may be enabled. The later backend must bind one monotonic deadline across provisioning/transfer/tool/inference/retrieval and separately persist unknown VM cleanup; an offline child-process test is not proof of VM confinement.

## What exists versus what is blocked

| Gate | State | Evidence needed / operator action |
| --- | --- | --- |
| A: real lifecycle | **BLOCKED — not run** | Operator-approved dedicated Windows Hyper-V host/permissions, reviewed provenance and SHA-256 of network-off protocol-test Linux VHDX with serial bootstrap, storage/resource settings and pipe access review. Run only opt-in real-host tests after review; capture VM/differencing-disk cleanup and sanitized results. The existing test includes fixed protocol exchange, timeout/cancel and exact-ID orphan cleanup; disconnect/failure cleanup and actual resource-limit guarantees still require verification. |
| B: real transfer | **BLOCKED — no real data-path evidence** | Offline fixture transfer passed fake-serial tests; Linux guest installation and a real named-pipe session have not been validated on this Windows host. Review/deploy the guest image, implement an interruptible bounded serial adapter and run operator-approved real VM boot/inject/check/retrieve/destroy including failed-retrieval cleanup. No arbitrary checkout transfer or live model work. |
| C: first model result | **BLOCKED by A/B** | Approved model/settings and paid-call consent; reproduce a fixture patch in a separate disposable workspace, report checks, usage and cleanup. |
| D: unattended queue | **BLOCKED by C** | Durable claiming, supervised runner, multi-job/restart evaluation with retained review bundles and owner-safe reconciliation. |

Existing code provides a Hyper-V lifecycle controller and whole-task COM1 JSONL transport, a host-side tool-session contract plus offline fixture transfer, a guest tool prototype, host-side inference gateway and synchronous service. It does **not** provide an interruptible real serial tool transport, deployed fixture guest service, demonstrated Hyper-V workspace/result transfer, real guest artifact retrieval, a live-bound independently retrieved review patch, hard USD cost enforcement, or a durable runner. An offline review-patch/bundle builder exists separately, but is not wired into the sandbox backend. The Commit 06 executor is location-neutral, with a compatibility import from `guest/`, and treats a final summary as an unverified submission. The offline Commit 06 changes were committed as `99ceeb8`. The guest CLI defaults to `UnavailableWorkerExecutor`.

## Known safety and reliability checks for later work

- Commit 04's fixed fixture installer creates the guest workspace and files as root (workspace mode `0700`); it is **not** a writable unprivileged coding workspace. A reviewed guest service must keep its protocol/config root-owned while explicitly assigning only the job workspace to an unprivileged worker and confining repository commands to that workspace. This has not been implemented or validated in a VM.
- `WorkspacePreparer` invokes host Git `clone`/`checkout`; before reuse for untrusted repos, review Git config/filter/hook execution and approved snapshot export; tracked secrets and unsupported submodules/LFS/binary/link content require explicit policy.
- The whole-task backend streams guest events on a daemon thread, and synchronous provisioning, inference, transfer, callback and retrieval calls are not uniformly interrupted by a job deadline. Some cleanup event/callback failures can interrupt later cleanup; isolate failures and persist unresolved resources.
- `JobBudget` now persists request/input/output/command limits alongside timeout/tool calls/optional USD, and the offline policy derives compatible executor/gateway limits. Existing backends do not yet use that policy; no trusted pricing/retry-aware reservation establishes a strict cost ceiling. Strict-USD `run_local` jobs are blocked, and missing usage is unknown, not zero.
- `HyperVSerialTransport` derives a pipe name from the sandbox ID and bounds individual JSONL frames, but named-pipe ACL/creator identity and job/session binding for a new tool protocol need review; a hostile guest can send arbitrary bytes. No general host networking from guest management channels.
- Existing `SandboxWorkerBackend` collects only worker-referenced artifacts; collecting a deterministic patch, validation checks and cleanup state independently of the model is not yet wired. Its existing `WorkerOutcome.SUCCESS` and `NightShiftService` completed state are not evidence of semantic task completion.
- Real-host `test_hyperv_real_host.py` is opt-in. Its exact-ID orphan reconciliation is appropriate for a dedicated test sandbox; do not run unscoped `reconcile()` alongside another runner. Record ownership and limits at the next gate, not inferred guarantees.

## Commit 08: offline review-bundle foundation (committed as `c011189`; real acceptance BLOCKED)

Historical validation before the offline foundation was committed as `c011189` (then HEAD `b5c19a2`): post-fix checks: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **260 passed, 4 skipped** (the first concurrent attempt exceeded the shell's 30-second limit; the standalone rerun completed in 26.05 seconds); focused review tests — **25 passed**; `python -m ruff check .` — **all passed**; `python -m mypy night_shifts` — **no issues in 49 source files**; `git diff --check` — passed. Other nonoverlapping offline groups: `tests/core tests/adapters tests/editing tests/runtime tests/llm` — **179 passed**; `tests/tools/fs tests/tools/system` — **84 passed**. `tests/tools/knowledge` exceeded the 30-second tool timeout; no passing result is claimed for that group. Test-owned `git apply --check` and a separate no-newline apply fixture succeeded, not VM replay. No real VM, paid inference or provider credentials were used in that validation; the offline foundation was subsequently committed as `c011189`.

The host-side work is described in [review-bundle contract](night_shift_review_bundle.md): bounded host-generated patch/inventory, distinct host-observed checks and guest claims, missing-evidence reporting on crash/timeout, cleanup and usage statuses, and write-once hashed `incomplete`/`complete` markers that survive restart. A fake replay receipt is only an offline binding check. Gates A/B remain **BLOCKED**: no real bound guest final export, configured checks in a real VM, actual second-VM replay, independent live backend collection, serial adapter or confirmed VM cleanup. Patch validation and a full real review bundle cannot be completed before these earlier dependencies exist. No live jobs may be enabled.

Follow-up offline work now implements a canonical job/sandbox/session-bound final workspace envelope, guest-only complete enumeration, bounded host retrieval and exact-ID destroy-before-persist orchestration. Post-hardening offline checks: `python -m pytest -q tests/night_shifts/test_final_workspace.py tests/night_shifts/test_review_collection.py` — **21 passed, 1 skipped** (Windows symlink privileges); `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **282 passed, 5 skipped**; `python -m ruff check .` — passed; `python -m mypy night_shifts` — no issues in **52 source files**; `git diff --check` — passed. Separate `python -m pytest -q tests/llm tests/runtime` — **84 passed** (run before the final resource/network-policy-only hardening). The resource/network-policy mismatch check now rejects export while still attempting exact-ID VM destruction; its fake-provider regression test passed. The fake serial/session/provider tests do not supply a real serial adapter, reviewed guest service, trusted checks in a VM, or second-sandbox patch replay. Commit 08's real acceptance remains blocked by A/B; neither a fabricated replay receipt nor fake Hyper-V provider completes it.

Next: obtain operator-approved dedicated Hyper-V host and reviewed network-off image configuration for Gate A; implement/review the real interruptible guest tool service and serial adapter before a separately authorized Gate B transfer and second-VM replay. The validated offline work does not complete Commit 08's real-host acceptance. Only real evidence can change the blocked gate state; never execute a repository in a host process as a shortcut. Strict USD remains blocked without trusted pricing and reservations. Operator approval and reviewed real host/image are prerequisites for Gates A/B and any paid call. Do not reinterpret offline fixtures as end-to-end evidence; record exact-ID cleanup status and image identity if a real gate is authorized.
