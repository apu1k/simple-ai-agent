# One-shot protected image inspection (candidate; NOT Gate A)

This adds a **separate** head-agent tool, `inspect_privileged_image_copy()`, around
existing copy-only image maintenance. It does not widen read-only evidence or
`run_shell_command`. No checkout code, editable virtual environment, site-packages,
model-selected paths/commands, credentials or arbitrary guest programs run elevated.
Code approval is not installation, an inspection run, image acceptance or Gate A.

## Action scope

The UI setting **Privileged image inspection: Enable next turn** replaces any unused
evidence grant. The arm expires after two minutes; the head turn has a 30-minute
budget and one attempt. Workers never inherit it. The matching tool consumes the
grant before checking installation/UAC. UAC cancellation and failure do not refund
it. Unmount/reset/restart revoke unused authority. Windows UAC and protected code,
not this in-process gate, are the security boundary.

The installed policy binds source path/current reviewed SHA-256, recovery ISO
path/reviewed SHA-256, existing empty private workspace, operator SID, preservation
and provenance decisions, code/runtime inventory and a finite approval window.
Actual execution rechecks inputs, source references OFF, unattached parentless
20 GiB dynamic VHDX, private control ACLs and free-space reserve. Only a fresh
copy is attached to one new generation-2 recovery VM: 2 CPUs, fixed 2 GiB RAM,
no network adapter, GSI disabled, no checkpoints, Linux Secure Boot and ISO-only
boot. COM1's connected object owner/DACL is checked before the handshake; broader
principals/unsupported ACEs refuse without ACL repair. This native policy is NOT
live-validated and may block on the host; review actual evidence instead of relaxing it.

Guest inspection requires the live overlay/NoCloud identity, loopback-only network
and fixed partition layout, sets block devices read-only, mounts ext4 `ro,noload`,
checks completed initialization and reports bounded diagnostic names/code hashes.
It is **not a complete finalization/security audit**. Successful unmount/read-only
state, unchanged source, stopped/removed exact VM, detached/unreferenced copy and
pipe evidence are required for `inspected_not_accepted`. Copy/media and possibly
configuration directories remain as evidence; VM removal does not mean directory
removal. No finalization, publication, Gate A or broad reconciliation is permitted.

## Recommended locations

- Protected code/runtime/policy/authoritative receipts:
  `C:\Program Files\AiAgentHyperVInspection` (Windows known-folder location).
- Existing reviewed workspace: `D:\NightShift\image-inspect-preflight`.
- Outputs: `<workspace>/<fresh-id>` and sibling `<fresh-id>.control`.

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
     -PythonProvenanceReviewed -IsoProvenanceReviewed -EvidencePreserved
   ```

   The installer validates exact bytes before copying, refuses unsafe ZIP entries,
   replacement/link paths and existing installations, and creates protected files
   with Administrators ownership **at creation**. It tests only the installed x64
   interpreter. No source/ISO/workspace mutation, VM action or permission repair.
   Partial setup failures are retained for review, never automatically retried.
   Different-account credential elevation is deliberately unsupported.
5. Restart the app normally. Enable the distinct inspection setting and request one
   inspection only after reviewing the exact action scope/approval window. Accept
   only the expected UAC operation. The helper verifies the full deployed code/runtime
   inventory and makes a **permanent installation-level inspection claim** before
   worker launch. No retry/reset/upgrade/removal tool is supplied.

## Timeout, failure and recovery boundary

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
`.facts.json` when returned, and `.result.json` when completion can be recorded.
Only verified final receipts prove success; progress/time/GUID receipts do not.
Manual recovery, another fresh workspace or replacement installation requires
separate review and authorization. No claim release or automatic retry is allowed.

## Validation boundary

Synthetic tests cover grants, policy/receipt binding, wrong operations/profiles,
space refusal, bundle inventory and unknown outcomes. Native parsing/watchdog
fixtures are not live NoCloud boot, COM1/ACL, mount/unmount or cleanup evidence.
The first authorized run must remain inspection only. Successful inspection is
followed by review and separately approved finalization/publication, then Gate A.
