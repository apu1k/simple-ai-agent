# Fixed validator build transaction — unelevated candidate

## Functional checkpoint and evidence

This batch connects a real local build path, not just another ownership interface:

- `bootstrap_native_build.py`: closed, memory-only review and fixed compiler recipe.
- `bootstrap_native_build_owner.py`: one-shot lifetime owner and shared deadline.
- `bootstrap_native_build_windows.py`: unelevated host gate, relative native file
  operations, private atomic compiler jobs and checked process observations.
- `bootstrap_native_build_stage.py`: fresh private NTFS staging, held identities,
  byte/security/alias reverification and held output snapshots.
- `bootstrap_native_build_artifacts.py`: bounded PE/CLI/manifest data inspection.
- `bootstrap_native_builder.py`: explicit candidate API; no CLI, tool/default
  wiring, installer, production pins or protected starter.

### Validation snapshot at repair review

- Applied focused selection: **293 passed**, warnings as errors, including real
  ordinary Windows builds of both fixed executables, held-source write/delete
  blocking and cancellation after an actual compiler resume.
- Broader applied selection: **3,289 passed, two failed, two skipped** across all
  45 related modules in three disjoint bounded shards. The failures were native
  job-accounting interpretation and an outdated primitive-import source guard.
  This is NOT a successful complete applied regression run.
- The native failure reproduced independently: basic job accounting reported
  total/active counts **3/3**, despite the separately configured/read-back native
  active-process limit of **two**. A prior focused pass did not expose it.
- With the proposed accounting/test/guard repair loaded **in memory only**, all
  **297 focused checks** pass: the five build suites (296 checks) plus the revised
  legacy guard. This includes real compiler execution, both artifact inspections,
  explicit native job-limit readback of **two for each job**, and actual compiler
  cancellation/termination observations. It is NOT applied-file verification or
  a complete related run. An earlier diagnostic incorrectly reloaded original
  test modules; its mixed result is not counted as proposed-repair validation.
- Applied repository Ruff and Windows-hosted Mypy across **111 source files** pass.

Before committing, apply the whole repair batch, rerun the affected native/fault
checks and the complete related selection, and check lint/types/whitespace. Do
not promote this review-time snapshot to an applied full-pass claim. Keep this
as one functional commit, with final applied results reported at that boundary;
no separate documentation-only commit milestone is required.

Neither produced executable nor either Main was invoked. No elevation, system
permission change, production profile/pins, protected claim, installation,
provisioning or VM operation occurred. Unknown native outcomes retained their
random fixture trees; they were not swept or retried as the same transaction.
**Gate A remains unrun. Never execute checkout code elevated.**

## Fixed end-to-end operation

`build_validation_candidate(review, source_files=..., toolchain_files=...,
deadline=..., cancelled=...)` reconstructs the existing
[closed build recipe](night_shift_native_build_recipe.md). It accepts no arbitrary
command, entry, reference, response file, helper, process limit or output selector.
The deadline is an absolute value in this process's `time.monotonic` domain;
6–300 seconds must initially remain. Setup, both compiles, artifact inspection
and closes consume that SAME window, including a five-second termination reserve.
The shared native clock guard covers inner file operations. No phase renews a
provisioning deadline or creates approval.

1. Require native x64 Windows, no thread impersonation, an actually UNELEVATED
   regular-account token and the actual Windows root matching the review.
2. Acquire the nine fixed Framework64 compiler/helper/config/reference inputs
   relative to held NTFS directories. Require complete byte pins and stable
   native identities/security before staging. The reviewed alias map lists 1–8
   complete Windows-rooted paths per member, including its selected path. Native
   enumeration and link count must match the whole inventory. Hold every alias
   and its ancestry, verify the SAME native identity/metadata/bytes, and reverify
   before launch/resume and output return. Unreviewed, missing, extra, duplicate,
   outside-OS or changed aliases refuse. Aliases select verification paths only,
   never additional code to execute. Observed test inventories are NOT approval.
3. Create ONLY the exact fresh stage/out/temp tree. Refuse occupied paths without
   repair, overwrite, deletion or alternative staging. Require exact protected,
   operator-owned user/SYSTEM/Administrators full-control DACLs. Retain no-delete
   directory handles and share-read-only sealed input readers. Reject reparses,
   sparse/compressed/offline/encrypted objects, case-sensitive or unqueryable
   directories, identity/path aliases, ALL multi-linked staged files/outputs and
   ALL multi-linked directories. Only explicitly inventoried OS file aliases are
   admitted. Permit ASCII case spelling differences only after checking directory
   case-insensitivity; inventories still reject case aliases.
4. Write/flush fixed source/profile/manifest/config bytes. BEFORE any child
   exists, close each writer under the held private parent, reacquire a reader,
   and require the SAME identity/security, controlled archive/size delta, exact
   final name, complete byte hash and EOF. This is NOT an atomic rights downgrade
   or a permanent-claim writer. The operator, Administrators, SYSTEM and stated
   Windows trust base are trusted across this local private-directory boundary.
5. Create one fresh private, non-inheritable kill-on-close/no-breakaway job per
   compiler. Set and read back a fixed native active-process limit of **two**.
   Use ONLY suspended atomic JOB_LIST creation, no create-then-assign or fallback.
   Application, argv, cwd and replacement environment come from the fixed recipe.
   No handles are inherited; standard streams are absent and diagnostics discarded,
   so unread or unbounded diagnostic pipes cannot block the owner.
6. Adopt both child handles, require initial membership/accounting of exactly
   one, reverify inputs, then resume once. Bound waits by time AND iterations.
   Cumulative accounting is separately bounded by **three** process creations
   per job: compiler root plus two helper creations. Accounting is sampled before
   and after waits and at completion; it is NOT a native total-creation quota or
   executable allowlist. Basic active accounting can include entries not counted
   identically by native active-limit enforcement. The proposed repair accepts
   accounting up to the fixed total while leaving the native limit at two.
7. Require signaled root and empty job before thread/process/job closes. Stop an
   exact residual job at most once. Require checked closes before the next
   compiler. A checked nonzero exit, including 259, refuses before another compile.
8. Acquire compiler outputs only at the corresponding checked completion
   boundary. Require exact inventories, empty temp and bounded held reads.
   Outputs must inherit exactly the user/SYSTEM/BA full-control ACEs from the
   held protected out directory; no post-create ACL repair. Retain each completed
   executable reader across the next compile. These are NOT installed targets;
   existing protected install/launch ACL policies remain unchanged.
9. Inspect actual held bytes: x64 PE32+, managed IL-only CLI header, exact entry
   MethodDef/type and `int Main(string[])` signature, expected assembly name,
   bounded fixed Framework references/versions/tokens and the fixed non-elevating
   manifest structure. This is data inspection, not assembly loading, complete IL
   verification, source attribution, origin authentication or installation review.
10. Reverify inputs/outputs, close conditionally and return immutable local bytes
    and observed hashes. Recheck time/cancellation at final close. Nothing is
    installed, published or executed; neither produced Main is invoked.

## Native repairs and preserved boundaries

Native preparation exposed Windows path case spelling, 2–4 hard links on the
selected installed OS files, Python 3.14 temp-parent `OWNER RIGHTS` ACLs and
object-type access masks. The repairs do not modify Windows or repair ACLs:

- Admit case-only names only with verified case-insensitive directories.
- Require the complete independently reviewed OS alias inventory and hold every
  alias; do not waive multi-link rejection for staged files or directories.
- Resolve `OWNER RIGHTS` only to the already verified trusted owner, not another
  account. Private staging still requires the exact explicit three-principal DACL.
- Use file rights for files/directories and generic object-mapped rights for
  jobs/processes/threads without adding trusted principals.
- Explicitly pin/hold `cvtres.exe` and its config. Job counts alone do NOT identify
  the helper images; trusted compiler/helper/loader behavior remains required.
- Distinguish basic accounting observations from the native enforcement limit.
  Keep native limit two, fixed cumulative observation bound three, initial count
  one, and mandatory root-signaled/empty-job completion. Four or active > total
  refuses. No caller-selected limits or runtime-worker policy change is added.
- Negative native tests require the exact intended refusal label/phase and zero
  compiler creations. An unrelated earlier failure cannot pass a negative case.
- Extend the old native-primitives import guard only to the two exact uninstalled
  build adapters. Exact import aliases and marker/probe/star-import prohibitions
  remain; no production/tool wiring is authorized.

## Uncertainty and trust boundary

Unknown creation/membership/wait/clock/termination/close outcomes stop the
transaction and conservatively retain its actual owner/input lease. Handle and
stop/close slots are disarmed before single attempts; other closes are attempted
after one fails. Later partial observations never turn uncertainty into success.
Known cancellation/timeout/nonzero exit permits release only after required
process observations and closes remain known within the original deadline.

Unknown owners and uncertain partial acquisition are strongly retained locally.
Retention is NOT persistent protection, proof every lock remains held, a protected
receipt or survival across owner death. No reset/retry/finalizer/reaper or cleanup
sweep exists. The candidate never deletes staging, even after success. Independent
supervision remains required for blocked OS/CLR calls and owner death.

The Windows/.NET trust base, compiler/helper/configuration/load behavior and the
builder's own Python/runtime/import closure MUST be independently reviewed BEFORE
production use. The nine byte-pinned tool inputs are NOT that full load closure.
Hash matches cannot authenticate already loaded code. OS ancestry permits
TrustedInstaller as part of the stated trusted platform; it is not a stage-owner
or protected installation-policy exception.

`LocalBuildObservation.scope` remains
`local_build_process_and_bytes_not_review_or_installation`. Observed hashes are
NOT independently approved finished-artifact pins. Compiler nondeterminism,
source/load review, protected acquisition and fresh binary/request/policy pins
remain separate. Forgeable API/return data confers no authority.

## Tests and next functional exit

Ordinary random-tree fixtures use actual repository sources, an INERT generated
profile and observed installed tool bytes/topology as consistency TEST data, not
production approval. They test real atomic compiler jobs and write/delete locks,
data-only artifact inspection, occupied staging, changed tools/aliases, checked
compiler failure and cancellation after actual resume with exact-job termination
and root/job observations. Unsupported host/policy behavior fails; it is not
silently replaced or classified as protected success.

Only an explicitly known fixture outcome and unchanged uncertainty registries
permit deletion of that exact random tree. Unexpected/unknown outcomes retain
trees/owners. Tests never reset live retention state, touch approval anchors,
launch produced executables, provision, operate Hyper-V or run Gate A.

Next functional target after this checkpoint: reviewed production platform/load
and profile setup, then a protected installer/starter that can establish trust
BEFORE loading the guardian, with authenticated capability/original-deadline
delivery, permanent early-failure/cancellation handling, an independent watchdog
and protected receipts/exact-owned reconciliation. This unelevated build candidate
does not supply those protections. Native installed-route characterization,
provisioning, protected VM validation and accepted image/channel work remain later.
