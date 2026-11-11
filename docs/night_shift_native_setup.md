# Fixed anchor preparation and setup publication — uninstalled candidate

## Functional boundary

This batch connects the existing build/profile/request contracts to create-new
setup operations. It is NOT a trusted executable installer, installed starter,
approval channel, independent watchdog or Gate A implementation. **Never load or
run checkout code elevated.** Independently reviewed OS/CLR/installer load trust,
authentic setup authorization, approved input pins and external supervision must
exist BEFORE production use. This API cannot establish those prerequisites by
hashing its own inputs. No production defaults, profile, tool or CLI is supplied.

The batch contains:

- `bootstrap_native_setup.py`: memory-only fixed packet preparation and profile
  derivation from separately observed/reviewed anchor identities.
- `native_validator_setup.cs`: serialized one-shot preparation/publication, whole
  packet binding, existing request-codec composition, held inventory/byte checks.
- `native_validator_setup_windows.cs`: explicit relative NTFS create-new adapter,
  protected BA/SYSTEM descriptors at creation, checked write/flush and closes.
- One setup-only shape check in the existing bound-request type, avoiding a
  second JSON decoder. Guardian/worker source selection remains sixteen sources;
  setup is a separate compilation unit, not code added to either entry path.
- Packet, CLR fault/composition and ordinary native primitive tests together.

## Two steps, deliberately separated by independent review

### 1. Prepare stable references before building

`SetupTransaction(parent, seconds).Prepare()` requires an independently reviewed
existing protected local NTFS parent: exact canonical path, native volume/index
identity and enabled same-account Administrator. The parent is not created or
repaired. The existing strict BA/SYSTEM ancestor policy is retained; incompatible
Windows ancestry refuses, not a reason to modify stock OS permissions.

Create ONLY `native-validator-bootstrap` under that parent, then exactly:

```text
approval/claims/
imports/claims/
launch/scratch/
```

Every directory has an explicit protected BA/SYSTEM-only full-control DACL at
creation. Capture distinct same-volume identities for all seven directories;
check empty claims/scratch, full inventories, security, final names and held
ancestry before checked closes. No arbitrary attempt-name, existing-tree repair,
OPEN_IF, overwrite, reset, deletion or alternate-name fallback exists. The fixed
root is itself the preparation collision barrier, including partial failures.

These observations are forgeable data, not approval. Independently review the
references, emit the existing non-circular guardian profile, perform the reviewed
unelevated build, then independently pin the finished binaries/configurations and
complete import closure. Construct/review the final request AFTER those binary
pins exist. Setup publication does not attest which profile/source was compiled
into a binary; finished-binary provenance is a separate mandatory review.

### 2. Publish one independently approved packet

The host packet builder accepts only the fixed complete import/launch inventories
and exact pinned canonical outer request. It binds launch/import/scratch identities
to the prepared references, derives the existing worker request and exact approval
policy bytes, and emits a bounded binary packet. Source/output references must be
outside the ENTIRE setup tree and must not alias any prepared/parent identity.

`NVSU0001` framing is fixed: little-endian uint32 count, then ordinal-sorted
records of uint16 ASCII-name length, exact name, uint32 byte length and raw bytes.
There are exactly **94 members**, no paths selected by incoming records, maximum
**129 MiB**. The whole packet length/hash MUST be independently approved before
publication. A digest returned by the host builder is only a local observation.

`Publish(refs, packet, expectedBytes, expectedSha)` clones/pins the complete packet
BEFORE decoding it, uses the existing closed request binder, verifies every leaf
pin, fixed profile/worker/config/policy bytes and setup isolation, then reacquires
all seven exact identities and their expected empty inventories. It creates the
fixed `publication.claim` BEFORE any payload write, irrespective of request ID.
The claim binds packet/request hashes with scope
`setup_publication_consumed_not_acceptance`. Existing/partial publication refuses.
Approval and import `install-attempt.claim` leaves remain ABSENT for their later
one-shot consumers; setup never consumes or resets those execution claims.

Create only fixed catalog-derived directories/files. Write/flush/read back each
new file through its exclusive writer. With the private parent still held, close
that writer once, reopen share-read-only and require the SAME identity/security,
controlled archive/length delta, complete bytes and EOF. This is NOT an atomic
rights downgrade. Administrators/SYSTEM and the independently reviewed platform
are trusted across that transition. Retain sealed readers through publication,
verify exact inventories and bytes again, and publish `approval.json` LAST.

An interrupted setup can leave a valid policy file and partial/uncertain artifacts.
The policy does NOT certify setup completion or installation acceptance. A future
starter must have its own authentic whole-attempt/completion and reconciliation
boundary; it MUST NOT infer successful setup from policy presence or process exit.
No activation/publication registration or execution occurs here.

## Time, failure and evidence

Each transaction has one cooperative 6–300-second monotonic window including
packet processing, native I/O and closes; publication can only shorten it to the
approval expiry. Sample monotonic time BEFORE obtaining the UTC observation, so
observation cost cannot move the translated expiry cap later. Rollback/nonfinite
monotonic readings and observed UTC rollback refuse. Expiry/deadline are rechecked
after final closes. Preparation and later
publication are intentionally separate approved setup operations, NOT renewals of
the provisioning attempt's original execution deadline. Authenticated original
execution-window delivery remains the starter's job.

No child is created, so conditional child-lifetime retention is not needed here.
Every acquired handle close is disarmed before one attempt, remaining closes are
attempted after a failure, and close uncertainty cannot return success. Native
exceptions are normalized. Partial objects/claims remain; no retry, rollback,
cleanup sweep, permission repair or claim reset is supplied. A flush/read-back is
not a power-loss/storage-rollback guarantee. An external whole-attempt authority
must cover cancellation, failure BEFORE root/claim creation and process death.
Cooperative checks cannot interrupt blocked kernel/CLR work; external supervision
and protected receipts/reconciliation remain prerequisites, not features here.

Tests use inert nonrunnable leaf data and fake native state for full transaction
composition, including policy-byte compatibility with the existing approval body.
The actual production enabled-operator gate is tested only for UNELEVATED refusal.
A separate ordinary native fixture substitutes the user SID for BA ONLY in exact
DISPOSABLE compiler copies of descriptor policies. It characterizes relative
creation, collisions, flush/read-back, identity, non-inheritance and write/delete
sharing locks. It does NOT admit that parent through production acquisition and
is NOT evidence of production BA/SYSTEM ownership, authentic approval, durability,
trusted installation or full native setup. Only a normally completed exact random
fixture is removed; failures/timeouts/unknown closes retain it.

## Validation snapshot at repair review

- Applied new selection: **82 passed**, warnings as errors, no skips. All eighteen
  repository C# sources compile with an inert generated profile and model harness.
  The actual production host gate refuses unelevated access; the deliberately
  adapted ordinary native fixture passes create/collision/flush/identity/sharing
  checks. Neither executable nor either Main is invoked.
- Complete applied **48-module** related selection, three disjoint bounded shards:
  **3,375 passed, one failed, two skipped**. The failure is the old guard equating
  every `native_validator_*.cs` file with the guardian/worker source set. The
  proposed guard admits ONLY the two exact standalone setup sources, separately
  asserts their exclusion, and keeps the executable source count exactly sixteen.
  No production source selection or compiler fallback changes.
- Two additional synthetic-clock regressions reproduce a timing defect: UTC
  observation cost could move the translated expiry cap later. The proposed
  repair samples monotonic time first and checks the resulting earlier cap before
  acquisition. The pre-repair code fails BOTH added timing cases; the repaired
  temporary core passes them, including zero acquisition after sampling consumes
  the cap. Seven additional compiled shape-isolation regressions cover both
  source/output paths, parent overlap, aliases, cross-volume and component-prefix
  controls. The existing close-fault test now injects BEFORE remaining closes,
  rather than only at the last close.
- Proposed core/test repair loaded in memory / a temporary fixture: **91 setup
  checks pass** (57 CLR scenarios, 32 host packet checks, one source guard and one
  ordinary native fixture). The revised legacy build guard passes separate direct
  in-memory validation. These are NOT applied-file verification or a complete
  repaired regression run; an initial mixed run still executed the old guard.
- Applied repository Ruff and Windows-hosted Mypy across **112 source files** pass.
  Scoped Linux-targeted typing passes for setup/request/build host modules. Applied
  Python 3.12 grammar, warning-as-error compilation, UTF-8, links and whitespace
  checks pass. The proposed tests also compiled/executed in the temporary check.

Apply the repair batch, then verify the actual focused files and complete related
selection before committing. Keep implementation, repairs, tests and this record
in ONE functional checkpoint; no separate documentation-only approval milestone.
No elevation, production profile/pins, protected installation/claim, produced-EXE
launch, provisioning or VM operation occurred. Only known exact ordinary fixtures
were removed; no retained/unknown fixture, protected anchor or OS ACL was repaired.

Next: independently reviewed platform/runtime/load policy and an actual trusted
setup host, then the protected starter with pre-load capability/original-deadline
delivery, permanent early-failure/cancellation policy, independent process watchdog
and protected receipts/exact-owned reconciliation. Native installed-route
characterization must precede provisioning and VM validation. **Gate A is unrun.**
