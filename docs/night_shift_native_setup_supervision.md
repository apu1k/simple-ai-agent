# Fixed executable setup host and independent process supervisor — candidate

**Uninstalled, unreviewed for production use. Never elevate checkout code.** This
batch connects executable entry, protected input/claim/result bodies, native job
supervision and the existing bounded unelevated compiler transaction. It is not a
protected tool, approved deployment, production platform/load review, trusted
installer/starter for provisioning, or Gate A. No production profile is shipped.

## Closed build order, without circular binary pins

`bootstrap_native_setup_build.py` accepts only canonical fixed profile data:
operation (`prepare` or `publish`), exact operator/parent references, a separate
preinstalled host-root identity plus claims/receipts/scratch identities, attempt
ID, 6–300-second cap, UTC expiry, and (publish only) exact prepared references and
independent packet pin. The profile's binary binding is deterministic across
Python/C#. It is consistency data, never an authenticator or review grant.

The host root must be disjoint from the setup parent. It must ALREADY exist with
reviewed protected ancestry, BA/SYSTEM-only private descriptors, exact inventories
and independent native identities. This batch does not create or populate that
host deployment, authorize its policy, alter stock OS permissions or establish its
self/OS/CLR/DLL/load trust. A matching hash cannot authenticate already loaded code.

Two explicit build APIs reuse the existing one-shot build owner/native stage:

1. `build_setup_host_candidate`: one fixed `validator-setup-host.exe` compile,
   twelve repository sources plus required generated `ReviewedSetupHost.g.cs`.
2. Independently review/pin the FINISHED host binary and fixed configuration.
   Do not promote an observed build hash to approval automatically.
3. `build_setup_watchdog_candidate`: separate fixed
   `validator-setup-watchdog.exe` compile, fourteen repository sources plus the
   same host profile and required `ReviewedSetupSupervisor.g.cs`, which binds the
   independent host binary pin. It does not embed its own executable hash.
4. Independently review/pin the finished watchdog and complete supported runtime/
   loader closure, then separately install/review the operation policy/host tree
   BEFORE loading either executable elevated.

Both builders use fixed x64 C#5/warnings-as-errors options, no implicit compiler
response/config/library selection, existing non-elevating manifest/configuration,
restricted environment, exact input/tool/complete alias pins, private fresh staging,
atomic compiler jobs and checked completion/close/artifact inspection. Compiler
concurrency remains TWO and observed total extent THREE. One-command setup builds
are separate operations, not renewed provisioning time. The original guardian/
worker recipe remains exactly sixteen sources/two compiles, with unchanged entry
selection and no default setup selection. Metadata inspection admits only the four
fixed executable/entry pairs. No arbitrary compiler/command/helper/entry selector.

## One preinstalled operation per host root

```text
validator-setup-host.exe + .config       # independent finished host pin
validator-setup-watchdog.exe + .config   # independently trusted BEFORE loading
policy.json                             # separately installed authentic approval
setup.packet                            # publish only; independent complete pin
claims/                                 # fixed install-attempt.claim after use
receipts/                               # fixed result and supervisor receipt
scratch/                                # remains empty
```

`policy.json` binds the full profile digest and independent host binary pin with
scope `protected_setup_operation_approval_once`. Native acquisition verifies exact
private policy bytes before creating the permanent fixed claim. The claim has
scope `setup_host_attempt_consumed_not_acceptance` and is independent of the attempt
ID/path digest. Existing/partial claims refuse. There is no overwrite, reset,
repair, alternative-name fallback, rollback or cleanup sweep.

Preparation and later publication need separately reviewed ONE-ATTEMPT host
installations/policies. Never replace the first deployment/policy/claim to switch
phases or retry. The fixed setup output root remains its original collision
barrier. Review the returned prepared identities before building/pinning guardian
and worker binaries and the final publication packet.

The supervisor pins/holds inputs before loading its host. Both sides hold exact
relative NTFS ancestry/identities/security, reject case-sensitive/reparse/multilink/
sparse/compressed/offline/encrypted shapes, check exact inventories and repeat
complete held-byte verification. The host sees the existing exact claim and
private policy; argv pins alone do NOT supply authority or authenticate a parent.
Pre-load provenance is established by the external trusted deployment and actual
supervisor path, not by the child's later role/policy checks.

## Original window and exact native containment

The watchdog starts ONE guarded monotonic/UTC window before admission. It reuses
the existing `ProvisionProcessGuardian` lifetime body with a new internal
window-only seam; request binding is still a distinct extension. Its actual
post-held-target stop point is delivered through common-machine QPC BEFORE the
host loads. The command has only the fixed mode, absolute counter cap/frequency
and host length/hash consistency fields: no request bytes, file/command selectors,
secrets, stdin transport or environment-selected policy.

The fixed native setup adapter creates an unnamed, non-inheritable kill-on-close,
no-breakaway job with active-process limit ONE and checked readback. Cumulative
job accounting has a separate bounded total of TWO (active cannot exceed total);
that observation bound does not raise the native admission limit. On this test
host, normal completion reported total TWO and active ZERO despite limit ONE.
The fixture does not attribute the extra accounting entry to a particular process.
The host is created suspended with atomic JOB_LIST assignment, zero inherited handles, absent
standard streams, fixed application/cwd and a replacement environment. No
create-then-assign, shell, PID/name lookup, fallback or alternate process command.
Root signaled/empty-job/checked-close observations remain mandatory. This is not
independent VM supervision or evidence that OS/CLR calls cannot block.

The host translates the earlier QPC cap conservatively in its own clock origin.
One rollback/nonfinite/UTC guard spans reception, held input acquisition, packet
copy, actual setup body, result write and closes. The setup transaction's internal
incoming-cap overload can only shorten time; the public historical API is
unchanged. The five-second process stop reserve remains INSIDE the watchdog's
original window; it is never added back to the host.

A normal host writes only a fixed 97-byte `NVSR0001` result binding phase, profile
and seven observed/expected directory identities. The supervisor checks its exact
job/root/close outcome, parses the bounded result and creates the fixed supervisor
receipt. Receipt scope is `local_setup_process_observations_not_acceptance`.
Missing/malformed results, nonzero exits and deadline stops do not become
acceptance. Policy/result/receipt presence and exit zero cannot establish trusted
installation, provenance, durability or later execution permission.

After uncertainty entering process creation/supervision, the actual owner and
input lease are retained and Main parks for external supervision/reconciliation.
Partial later observations do not release locks or manufacture a receipt. Handle
and stop slots remain once-only; no retry/reset API or finalizer is supplied.
The independent upper execution host must cover watchdog load/death/blocked calls,
failure/cancellation BEFORE its claim and exact-owned reconciliation. That trusted
host/channel is still required. Power-loss/storage rollback is not settled by
flush/read-back. A process watchdog alone never proves VM/disk absence.

## Tests, evidence and next exit

The proposed tests combine closed profile/recipe checks, one-command build-owner
faults, real unelevated host/watchdog builds with inert/observed TEST data, actual
production-entry UNELEVATED refusal, compiled end-to-end host/lifetime/frame/result
models, and ordinary native supervision fixtures (normal exit, timeout and owner
death). Fixture roles/files/actions are explicit non-production doubles; the native
job descriptor is user-adapted only in an exact disposable source copy. Neither
production BA/SYSTEM acquisition nor native setup is inferred from those fixtures.

Native fixture controllers receive an exact duplicate of the ACTUAL child handle
returned by creation. They wait on that capability, not a looked-up child PID/name
or exit-code-only inference. Only their exact owned watchdog handle may be stopped
on fixture failure; failed/unknown trees remain. Normal known completion and checked
controller closes are required before removing that exact random tree. The fixtures
have inert setup bodies: no real protected approval, installation, provisioning,
Hyper-V, disk mounting or VM operation. No security default/test bypass is shipped.

### Validation at repair review

- Applied new selection: **74 passed, two failed**, warnings as errors. Both fixed
  setup products build through the real unelevated transaction; metadata checks,
  compiled composition/fault models, actual production-entry unelevated refusal
  and native watchdog-death/exact-child-handle containment pass. Normal completion
  and deadline fixtures enter the conservative park path and time out.
- A disposable diagnostic observes total TWO / active ZERO at normal completion.
  The old native adapter incorrectly bounds cumulative total by admission limit
  ONE. The proposed repair keeps native limit ONE and its readback unchanged,
  separately bounds cumulative total by TWO, and still requires a signaled root,
  empty job and checked closes. Six compiled accounting cases exercise empty,
  root, total-two, active-two and invalid total/active observations. No assertion
  is replaced by exit-code-only inference or a looked-up child PID.
- Proposed repair loaded in memory / disposable compiler copies: **82 focused
  checks pass**, including both real setup builds, six added accounting cases,
  ordinary native normal/deadline/owner-death supervision and atomic publication
  of complete duplicated-child-handle text in the fixture. This is NOT applied
  repair verification. Production sources/profiles contain no fixture bypass.
- Broader applied **51-module** selection: **3,560 passed, two failed, three
  skipped** across bounded disjoint selections. It comprises all
  `test_*native*.py` modules plus confinement-contract, daemon-asset, public-probe,
  public-KVP, maintenance-credentials/TLS/failure-diagnostics, preparation-control
  and image-preflight modules. Its only failures are the two native cases above.
- Applied Night Shifts Mypy passes across **113 source files**; scoped Linux typing
  passes across six build modules. Applied source Python 3.12 grammar/compilation
  and Git whitespace checks pass. Repository Ruff finds 23 formatting/unused-import
  diagnostics in four new Python files; proposed corrections pass Ruff via stdin
  without suppressions. The final applied repository checks remain required.

Apply this repair batch, then verify the actual focused files and related
regressions before committing. Keep source, repairs, tests and this single record
in ONE functional commit, without a documentation-only approval stage. Failed
native fixture trees and diagnostic source copies remain for review; no sweep,
claim reset, permission repair or production retry occurred. All executed setup
product entries were UNELEVATED refusal checks; operational process launches used
explicit inert ordinary-user fixtures. No elevation, protected installation,
production setup/claim, provisioning or VM operation occurred.

Next production prerequisites: independent supported platform/load review and
actual profile/pin/deployment authorization, trusted pre-load setup launch and
whole-attempt receipt/reconciliation host. Provisioning still needs its separate
protected guardian starter/original-deadline route, followed by installed native
characterization before provisioning/VM validation. **Gate A remains unrun.**
