# One-turn privileged Hyper-V evidence

This is **not an elevated shell mode**. The head agent receives one fixed
`collect_privileged_host_evidence()` operation with no model-selected arguments.
Workers never receive the tool. `run_shell_command` is unchanged and must remain
unelevated. Do not run the whole application as Administrator.

## Scope and expiration

In `\settings`, choose **Privileged Hyper-V evidence: Enable next turn**. Submit
the next message within two minutes. The next head-agent `Agent.step()` consumes
the arm, even if it never calls the tool. The turn has a 30-minute deadline.
Exactly one attempt is allowed; input/installation failure and UAC cancellation
consume it too. No retry or parallel privileged operations. Completion, error,
reset, unmount and restart discard unused authority. The current status appears
in `\state`, the header and the model's per-request runtime context.

The setting is intentionally not in `.env`, provider config or chat history and
cannot be enabled through a model tool. This in-process gate is a scheduling
control, not a security boundary against a compromised Python runtime. Windows
UAC and the protected fixed helper are the privilege boundary. This feature does
not remove the general risks of other existing local tools.

## Protected installation: separate, reviewed operator setup

**Applying repository proposals does not install or launch anything privileged.**
Review `scripts/install_privileged_host_helper.ps1`,
`scripts/privileged_host_helper.ps1`, and the existing read-only
`night_shifts/backends/hyperv_scripts/collect_host_evidence.ps1` first. Use a
trusted dedicated Administrator PowerShell for setup, not an elevated AI app.
Use native 64-bit Windows PowerShell and a native 64-bit Python runtime.

The installer creates only this fresh directory:

```text
C:\Program Files\AiAgentHyperVEvidence\
    helper.ps1
    collector.ps1
    policy.json
    receipts\
```

(The actual Program Files known-folder location is used.) Existing installations
are refused: there is no automatic overwrite, upgrade, ACL repair or removal.
The directory is created with a restrictive DACL: SYSTEM/Administrators full
control and the explicitly selected operator SID read/execute. Owners are
Administrators. Untrusted owners, reparse paths and replaceable installation
ancestors are refused. Review partial setup failures instead of retrying blindly.

Before elevation, obtain the operator SID from the ordinary application account,
using `(whoami /user)` in your usual terminal. With credential-based UAC, this may
be different from the account performing installation. Review the intended
source VHDX, recovery ISO, ISO digest and workspace. These inputs are pinned in
the protected policy: the model cannot select different paths or code.

Example setup (replace **every placeholder**, after review; not an agent command):

```powershell
# From the reviewed repository, in the dedicated Administrator terminal:
$helperHash = (Get-FileHash -LiteralPath '.\scripts\privileged_host_helper.ps1' -Algorithm SHA256).Hash.ToLowerInvariant()
$collectorHash = (Get-FileHash -LiteralPath '.\night_shifts\backends\hyperv_scripts\collect_host_evidence.ps1' -Algorithm SHA256).Hash.ToLowerInvariant()
# Ensure checkout files cannot change between review and obtaining these hashes.
.\scripts\install_privileged_host_helper.ps1 `
  -HelperSha256 $helperHash -CollectorSha256 $collectorHash `
  -OperatorSid '<ordinary application account SID>' `
  -SourceDisk '<reviewed absolute source VHDX path>' `
  -RecoveryIso '<reviewed absolute recovery ISO path>' `
  -RecoveryIsoSha256 '<independently reviewed lowercase ISO SHA-256>' `
  -Workspace '<reviewed absolute inspection workspace path>'
```

Installer hashes the exact bytes it copies, not a path followed by a second read.
No VM, source disk, ISO or workspace is created, repaired or modified. It is
acceptable to pin a missing workspace: collection later reports that blocker.
The installer itself must be reviewed/trusted; merely hashing scripts without
review does not establish trust. Policy or helper updates require a separately
reviewed administrative procedure, not an AI-writable replacement.

## Normal use

Restart the app after applying code changes. Enable the setting in `\settings`,
then ask: **Collect the read-only Hyper-V host evidence now.** The assistant uses
the new tool, and Windows asks for UAC consent. Confirm only the expected system
PowerShell operation. No pasted `py` command is required for each collection.

The client verifies the installed policy/schema/operator, file hashes, DACLs,
owners and ancestors. It locates Program Files and PowerShell through Windows
APIs rather than PATH or environment overrides. The helper executes the installed
collector, not a repository file. Only request identity/expiration travel as
arguments. No generic executable, command text, script path or input path is
accepted from the model. No profiles or caller-controlled module search path.

The evidence worker starts suspended and is placed in a Windows kill-on-close
job before resuming. An independent watchdog terminates the job on timeout;
closing/failing the helper also closes the job. No future VM operations are
scheduled. If the application exits during collection, already-running read-only
work may finish, but must not exceed the worker deadline. Revocation does not
undo completed reads. UAC itself is controlled by Windows and cannot be forcibly
dismissed by the client; acceptance after expiration is rejected without starting
the worker. Bootstrap/OS failures may leave an unknown outcome, never an automatic
retry. Inspect retained evidence before granting another turn.

## Live progress and timing

Collection remains synchronous from the model's perspective: no final answer is
returned before the helper exits and the protected result is validated. The
Textual app already runs the agent in a background worker. It now shows an
immediate collection notice and a rolling status-bar update with elapsed time
roughly every five seconds, leaving typing and rendering responsive. Progress
notifications are display-only; they are not added to model/API messages or
persisted as assistant answers. Status is cleared when the turn finishes.

The client observes the helper with short native waits against the same fixed
deadline. There are no retries, extra operations or widened privileges. With an
older installed helper it displays generic collection/elapsed-time updates. A
newly reviewed helper also writes protected, create-new phase receipts for
inventory, source hashing, ISO hashing and VM-state recheck. These bounded,
identity-checked hints select fixed UI labels only; missing or invalid hints
cannot imply success or authorize anything. The console shows an explanatory
banner instead of staying empty. The collector reports `host.phase_timings_ms`
for completed phases; hashes still cover every byte of both files.

**Repository approval does not replace installed code.** Existing installations
remain usable for generic progress, with their existing hashes and policy.
Phase receipts, console banners and timings require separately reviewed protected
code deployment. The installer still refuses an existing installation: do not
rerun it blindly, overwrite installed files, repair ACLs or remove old receipts.
A deployment/migration procedure must preserve existing audit evidence and must
not run concurrently with collection. No automated upgrade is introduced here.

## Audit and limitations

Normal requests and tool results use the existing tool-call audit. The elevated
helper additionally writes protected, create-new receipts:

- `<request-id>.start.json`: single-use claim, input paths, script hashes,
  elevated identity, start time, deadline and fixed operation.
- `<request-id>.worker.json`: exact executable/arguments before worker launch.
- `<request-id>.phase-<fixed-phase>.json`: optional protected stage-start hints;
  not completion evidence.
- `<request-id>.facts.json`: raw bounded host answer when available.
- `<request-id>.result.json`: finish time, status, worker exit code and answer.

Receipts are retained, not auto-deleted; do not infer successful completion from
a start receipt alone. Setup/compiler temporary artifacts can also remain under
this protected directory. No outcome means **unknown**, not successful cleanup.
Receipts are protected from the ordinary application account, not from an
administrator. API logs are supplementary, not the authoritative execution audit.
UAC cancellation before helper startup produces no protected helper receipt, but
is recorded in the normal tool result. Native handle and result sizes are bounded;
returned host facts use the existing collector's validation.

The result is a snapshot only. It does not approve image provenance, guest
contents, pipe ACLs, VM creation permissions, finalization, publication or Gate A.
The collector never starts/stops/creates/removes a VM, mounts a disk, repairs
permissions or creates a workspace. A separate [inspect-only protected adapter](privileged_image_inspection.md)
has its own installation, pinned approval and UI operation; the evidence setting
cannot authorize it. Selecting either operation replaces an unused grant for the other. Inputs and VM state can change after the
snapshot; later operations require their own checks and authorization.

## Validation

Offline tests cover gate expiry/revocation, exceptions, concurrent claims,
worker exclusion, UI activation, pinned-code/policy checks, unsafe ACLs/owners,
links, mismatched/oversized receipts, cancellation/unknown outcomes and existing
collector integration. PowerShell parsing and unelevated watchdog fixture tests
are separate from live UAC/Hyper-V acceptance. Do not treat offline success as a
verified privileged installation or live collection.
