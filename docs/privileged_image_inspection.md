# One-shot protected image inspection (candidate; NOT Gate A)

This adds a **separate** head-agent tool, `inspect_privileged_image_copy()`, around
existing copy-only image maintenance. It does not widen read-only evidence or
`run_shell_command`. No checkout code, editable virtual environment, site-packages,
model-selected paths/commands, credentials or arbitrary guest programs run elevated.
Code approval is not installation, an inspection run, image acceptance or Gate A.

## Action scope

The UI now uses **Elevated commands: Enable next turn** and the shared
[pending approval workflow](elevated_commands.md). The arm expires after two
minutes; the head turn has a 30-minute budget. This fixed inspection gets at most
one attempt per turn and still requires its separately installed permanent claim.
Workers never inherit it. The matching tool consumes its fixed attempt before
checking installation/approval/UAC. Rejection, UAC cancellation and failure do not
refund it. Each request needs its own acceptance in `\pending`; other approved
commands do not widen this helper's scope. Unmount/reset/restart revoke unused
authority. Windows UAC and protected code, not this in-process gate, are the
security boundary. Neither the old installation nor its consumed claim is changed.

The installed policy binds source path/current reviewed SHA-256, recovery ISO
path/reviewed SHA-256, existing empty private workspace, operator SID, preservation
and provenance decisions, code/runtime inventory and a finite approval window.
Actual execution rechecks inputs, source references OFF, unattached parentless
20 GiB dynamic VHDX, private control ACLs and free-space reserve. Only a fresh
copy is attached to one new generation-2 recovery VM: 2 CPUs, fixed 2 GiB RAM,
no network adapter, GSI disabled, no checkpoints, Linux Secure Boot and ISO-only
boot. COM1's connected object owner/DACL is checked before the handshake; broader
principals/unsupported ACEs refuse without ACL repair. This native policy has
failed a live V2 check (`principal_rejected`) and has not passed live validation;
review actual SID/access-mask evidence instead of relaxing it blindly.

Guest inspection requires the live overlay/NoCloud identity, loopback-only network
and fixed partition layout, sets block devices read-only, mounts ext4 `ro,noload`,
checks completed initialization and reports bounded diagnostic names/code hashes.
It is **not a complete finalization/security audit**. Successful unmount/read-only
state, unchanged source, stopped/removed exact VM, detached/unreferenced copy and
pipe evidence are required for `inspected_not_accepted`. Copy/media and possibly
configuration directories remain as evidence; VM removal does not mean directory
removal. No finalization, publication, Gate A or broad reconciliation is permitted.

## Fixed side-by-side V2 deployment (separate new-attempt authorization)

The current client, installer, supervisor and worker select **only** the fixed
`AiAgentHyperVInspectionV2` installation. This is a deployment identity, not a
policy-schema change. A missing, expired, drifted or consumed V2 refuses; there
is no discovery, fallback to V1, claim reset, automatic upgrade or automatic retry.
A future failed V2 still needs separate recovery review; do not increment a name
or reinstall simply to evade its claim. Each new deployment is new authority,
not a continuation of the old approval.

The installer requires `-AuthorizeNewInspectionAttempt` in addition to its
provenance/preservation switches. That flag records an explicit operator decision,
not proof that an evidence audit occurred. Installation itself does not inspect
or start a VM. A distinct pending approval and UAC are still required for inspection.

- Candidate new protected code/runtime/policy/authoritative receipts:
  `C:\Program Files\AiAgentHyperVInspectionV2` (Windows known-folder location).
- Proposed fresh workspace, requiring separate creation and private-ACL review:
  `D:\NightShift\image-inspect-v2`.
- Retained V1 installation: `C:\Program Files\AiAgentHyperVInspection`.
- Retained occupied V1 workspace: `D:\NightShift\image-inspect-preflight`.
- New outputs: `<new-workspace>/<fresh-id>` and sibling `<fresh-id>.control`.

Do not move, overwrite, remove or repair the V1 installation, claim, receipts,
workspace, VM, disks or media. Its expired policy is historical evidence, not an
approval window to extend. Reusing the separately reviewed CPython archive or
recovery ISO requires rechecking their exact bytes; author a fresh bundle with
the V2 worker and current channel diagnostics. No app restart, code commit or
new bundle alone authorizes protected deployment or a VM launch.

Retained diagnostic source, original VMs/media/manifests/claims and old operation
locks are never repaired, reused as outputs or deleted. Existing read-only evidence
installation remains unchanged.

## Separately reviewed setup (do not execute merely because code was approved)

1. Review the fixed source changes/commit and complete diagnostic preservation.
   Collect fresh source evidence; do not use the diagnostic record's pre-boot hash.
   Authenticate the Ubuntu ISO provenance and review Hyper-V permissions/isolation.
2. Independently obtain/review a **CPython 3.11+ Windows x64 embeddable ZIP**, including
   publisher provenance and the full archive SHA-256. No downloads occur in the tool
   or installer. The interpreter/DLLs/stdlib are installed protected, not taken from
   the app's runtime. Embedded `_pth` must contain only `.` and its bundled stdlib
   ZIP (comments/blank lines allowed); `import site` or external paths refuse.
3. Review the pinned `pycdlib==1.21.0` dependency and author a new bundle unelevated:

   ```powershell
   python -B -m night_shifts.inspection_bundle --output '<new absolute reviewed .zip path>'
   ```

   Inspect the ZIP/manifest and record its SHA-256. It contains fixed maintenance
   assets, pure-Python pycdlib sources, and empty package initializers to exclude app
   orchestration/provider imports. It is not an image or an installation.
4. Review `scripts/install_privileged_inspection_helper.ps1` and
   `scripts/privileged_inspection_helper.ps1`. In dedicated native x64 Administrator
   PowerShell under the **same operator account**, perform separately approved setup:

   ```powershell
   .\scripts\install_privileged_inspection_helper.ps1 `
     -Bundle '<reviewed bundle.zip>' -BundleSha256 '<reviewed digest>' `
     -PythonArchive '<reviewed CPython embeddable.zip>' -PythonArchiveSha256 '<authenticated reviewed digest>' `
     -HelperSha256 '<reviewed exact helper bytes digest>' -OperatorSid '<ordinary app SID>' `
     -SourceDisk '<reviewed diagnostic VHDX>' -SourceSha256 '<fresh reviewed source digest>' `
     -RecoveryIso '<reviewed live ISO>' -RecoveryIsoSha256 '<reviewed ISO digest>' `
     -Workspace '<existing empty private external workspace>' `
     -InspectionApprovedUntilUtc '<explicit UTC time, 30 minutes to 24 hours ahead>' `
     -PythonProvenanceReviewed -IsoProvenanceReviewed -EvidencePreserved `
     -AuthorizeNewInspectionAttempt
   ```

   The installer validates exact bytes before copying, refuses unsafe ZIP entries,
   replacement/link paths and existing installations, and creates protected files
   with Administrators ownership **at creation**. It tests only the installed x64
   interpreter. No source/ISO/workspace mutation, VM action or permission repair.
   Partial setup failures are retained for review, never automatically retried.
   Different-account credential elevation is deliberately unsupported.
5. Restart the app normally. Enable the unified elevated-commands setting and
   request one inspection only after reviewing the exact action scope/approval
   window. Review/accept the fixed inspection in `\pending`, then accept only the
   expected UAC operation. The helper verifies the full deployed code/runtime
   inventory and makes a **permanent installation-level inspection claim** before
   worker launch. No retry/reset/upgrade/removal tool is supplied.

## Timeout, failure and recovery boundary

The updated protected policy requires integer `max_execution_seconds=900`. The
client refuses older/missing policies before approval/UAC. The native supervisor
caps the complete worker at 900 seconds (or earlier approval expiry), independently
of the 30-minute authorization window. The inspection worker's inner command is
also capped at 900 seconds. The native watchdog refuses zero or more than 900000
milliseconds and distinguishes native wait failure from observed timeout. On
timeout no partial success facts are accepted. Termination observation/receipt
writing may add bounded response overhead; they do not extend worker execution.
These source changes are NOT a protected deployment or a new inspection grant.
Do not overwrite the consumed V2, reset its claim, extend its original expiry or
increment an installation name merely to retry.

The worker starts suspended inside a kill-on-close Windows Job before resuming;
its Python and PowerShell descendants are process-bounded. **Hyper-V VMs are not
Job children.** Window closure, app failure, watchdog expiry or killed PowerShell
can leave the exact recovery VM running. Never describe this as successful cleanup.
The native script writes create-new GUID/name/config/copy evidence immediately
following New-VM, before configuration/start. A crash before that receipt can still
leave an uncertain provisioning outcome: use the fresh identity/name and host
inventory, never guess or sweep.

Normal caught script failures attempt an exact-ID/marker/path-bound stop and retain
resources. If process termination prevents it, status is UNKNOWN. The helper writes
protected `<request>.start.json`, `.worker.json`, `.vm.json` when provisioned,
`.failure.json` on a normally caught maintenance failure when it can be written,
`.facts.json` when returned, and `.result.json` when completion can be recorded.
The create-new failure receipt contains only the fresh identity/mode, fixed phase
and channel substage/code, an optional numeric Windows error, exact VM GUID when
known, and `unknown` or `off_observed` stop observation. It never contains raw
exceptions, SDDL, guest output or log/key contents. Its schema/bindings are checked
before inclusion in the manifest, protected facts and app's UNKNOWN result.
Missing/partial/malformed/mismatched evidence cannot infer Off. A killed process
may produce no failure receipt. `off_observed` is an exact-owned snapshot after
read-back, NOT current state, unmount, VM removal, inspection success or retry
permission. The original GUID receipt remains unchanged.
Only verified final receipts prove success; progress/time/GUID receipts do not.
Manual recovery, another fresh workspace or replacement installation requires
separate review and authorization. No claim release or automatic retry is allowed.

## Retained first live attempt — 2026-10-13

The first protected inspection request `9dc25cd0f6754a51b17efaa83d82de41`
created maintenance identity `2f2ea761172a42f7bac11fe534158dd9` and VM GUID
`51434da9-9168-428a-8624-72a246ccc18d`. The manifest records `CHANNEL` failure
and `maintenance_unknown`; no successful guest inspection or final source-hash
check was returned. The operator's later exact-ID query observed that VM Off,
matching name/marker/config/COM1 path, and its copied VHDX unattached. This is not
VM removal or image acceptance; the copy remains referenced by retained config.

The installed `7253fe3` bundle did not preserve channel substages/native error
codes. Later diagnostics cannot retroactively explain that failure. Preserve the
old protected installation/claim/receipts, VM/config/copy/media and control claim.
These checkout changes do not deploy to that installation. Another deployment or
attempt needs separate review; no reset, overwrite, permission repair or retry is
introduced. `DebuggerMode: On` was observed, not established as the cause.

## Fresh read-only recovery evidence — 2026-10-17

The general launcher's corrected read-only inventory request
`fda848c7cf054d36be4869a590ff85f6` observed retained VM
`51434da9-9168-428a-8624-72a246ccc18d` Off, with exact name/owner/config matches,
2 CPUs, fixed 2 GiB RAM, zero network adapters/checkpoints, GSI disabled and the
recorded Linux Secure Boot template/media. COM1 `DebuggerMode` remained On; no
cause or change is inferred. Source and failed-inspection copy were unattached,
parentless dynamic 20 GiB VHDX files. The source's referencing diagnostic VM
`24651418-5ca1-4e35-8cb9-2a498b44f33f` was also Off.

The fixed evidence request `6a199c922ae04680b10fdee4b3f78358` independently hashed
source and ISO, matching the existing reviewed bindings:

- Source SHA-256: `a8470ae83c3608065292a298be1030c6501142f9a4665accbf00075745e63ccb`.
- ISO SHA-256: `97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8`.
- Private workspace ACL passed; approximately 253 GiB was free.
- Overall input status was `blocked` by `workspace_not_empty`, as expected for the
  preserved V1 attempt. This does not authorize emptying/reusing that workspace.

An initial general inventory request failed before inventory because the launcher
cleared `COMPUTERNAME`. An unelevated differential fixture reproduced the null-name
error; setting that process variable from `[Environment]::MachineName` reached
normal permission checks, and the separately approved corrected inventory passed.
The V2 supervisor derives the variable from Windows for its own process only.
This does not change the general launcher or diagnose the old CHANNEL failure.

These receipts are snapshots, not guest inspection, pipe-ACL acceptance, launch
permission or Gate A. No VM lifecycle operation, mount, ACL repair, source mutation
or claim reset occurred. The V1 deployment's 69 pinned files matched, with no extra
payload/runtime files; its claim remains consumed and approval expired. Preparing
V2 in the repository does not install or launch it.

## Retained V2 live attempt — 2026-10-17

Request `b49f709675e24b07a143f4f0f6e6491c` created maintenance identity
`40ac18e14aec40a59598b00f75b648fe` and VM GUID
`91eb0537-4519-494d-b80e-6e1aa5f40de6`. Protected receipts under
`C:\Program Files\AiAgentHyperVInspectionV2\receipts` record start at
`2026-10-17T07:06:02.7438499Z` and completion at
`2026-10-17T07:11:18.4327321Z` with `CHANNEL / acl_check / principal_rejected`,
no numeric Windows error and `stop_observation=off_observed`. The result remains
`blocked_or_outcome_unknown`, accepted=false, Gate A unrun, retry unauthorized.

The deployed code rejects this label only when an access-allowed COM1 ACE has a
SID outside SYSTEM, Administrators, the current operator and that exact VM SID.
Connection/security parsing/VM-SID resolution and owner/nonempty-DACL checks
precede it; the controller handshake follows it and was not sent. This does not
identify the rejected SID or its access mask: neither is retained in this failure
schema. It does not establish a guest-image defect or safe pipe permissions.

The failure handler observed the exact-owned VM Off at read-back. This is not a
fresh current-state check, copy-detachment verification, VM removal, guest
inspection/unmount or final source-hash verification. Preserve the V2 installation,
consumed claim, VM/config/copy/media, manifest and receipts. Its retained workspace
is `D:\NightShift\image-inspect-v2`. Do not reuse or clean it automatically.

Next diagnostic review must obtain the actual rejected SID and access rights,
assess whether the pipe is unsafe or the allowlist is incomplete, and preserve
bounded exact-resource evidence without permission repair. An Off VM may no
longer expose its COM1 pipe; any diagnostic VM start needs separate authorization.
Do not substitute guessed SIDs, broaden the allowlist blindly, or redeploy/retry
inspection merely to discover the same failure.

This multi-minute run used the fixed inspection supervisor, whose then-installed
watchdog allowed the remaining turn budget. The general-script launcher's old
60-second cap was not its limit. The proposed 900-second caps in this checkout
are not deployed by committing/restarting the app.

## Captured V2 pipe permissions and policy review — 2026-10-18

The [COM1 pipe security review](night_shift_pipe_security_review.md) records the
separately approved preservation failure and successful diagnostic, exact receipt
bindings, final state and native follow-up experiments. It supersedes the earlier
missing-SID diagnostic gap, not the consumed inspection claim or its failed result.

Diagnostic `7223f9c08a7d4295bf28f78cfdf438e1` preserved ten verified backups,
started only the exact retained recovery VM, captured COM1 security without any
guest read/write/handshake, and observed it Off. Its 507-second run completed
within the requested 900-second worker ceiling. Protected evidence remains at
`C:\Program Files\AiAgentElevatedCommands\receipts\pipe-acl-v2-stable-config-20261018`.
Post-run read-only request `251a7132d6ea4fd7ba89ade6772d5cb1` confirmed Off,
unattached source/copy, zero checkpoints and the pipe absent. The automatic-
checkpoint flag was nevertheless true; future new VMs need it explicitly disabled.
No VM/config/copy/media was removed, no existing permissions were repaired, and
V2's consumed claim/policy/original result/manifest remain preserved.

The captured pipe grants Everyone read including data (`0x00120089`), Hyper-V
Administrators full control and the `VmWorkerProcess` capability full control.
The capability name was confirmed by an exact native Windows SID derivation,
not assumed from a guessed label. It is not the exact VM SID and does not prove
caller identity. These grants still fail the current plaintext policy. Merely
recognizing their names, observing an empty group or tightening an ACL after open
must not enable inspection: disposable native tests show already granted read
handles can survive even an explicitly empty replacement DACL.

Keep plaintext blocked while reviewing an authenticated encrypted maintenance
channel and protected per-attempt credential provisioning, or another supported
private/VM-bound endpoint. No production channel change or new inspection attempt
is authorized by this review. The general launcher update does not upgrade the
fixed helpers; their deployment/900-second policy and fresh attempt authorization
remain separate prerequisites. Gate A is still unrun.

## Validation boundary

Synthetic tests cover grants, policy/receipt binding, wrong operations/profiles,
space refusal, bundle inventory and unknown outcomes. Native parsing/watchdog
fixtures are not live NoCloud boot, COM1/ACL, mount/unmount or cleanup evidence.
The first authorized run must remain inspection only. Successful inspection is
followed by review and separately approved finalization/publication, then Gate A.
