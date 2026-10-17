# Unified Administrator requests (candidate; separate installation required)

The single **Elevated commands: Enable next turn** setting replaces the two
operation-specific UI settings. It permits requests during the next head-agent
turn, not execution. Every elevated request needs acceptance in `\pending` and
Windows UAC. Ordinary `run_shell_command` calls and the app remain unelevated.

## Workflow

1. Enable the setting in `\settings`. The unused arm expires after two minutes.
2. Submit a task. The head turn has a 30-minute authorization budget.
3. An elevated tool freezes a review request. An orange conversation notice says
   to open `\pending` (or F9); nothing has executed. Both work while the agent waits.
4. Review the request, purpose/change explanation, working directory, timeout,
   script/helper identity and policy. Explanations are model assertions, not safety
   guarantees. Enter accepts; Delete/Backspace rejects.
5. Rejection returns `rejected` without UAC. Acceptance permits only this request,
   followed by UAC. Cancellation returns `uac_cancelled`; it does not grant a retry.
6. The protected launcher verifies the approved request digest, writes a permanent
   create-new start claim and approved snapshot, and launches one command process.
7. The result references a protected receipt. Another command requires another
   pending acceptance and UAC. There is no reusable elevated shell or batch approval.

The pending review shows PowerShell scripts in a separate multiline block, not
as a JSON string containing literal `\n` escapes. Scripts, hashes and metadata
soft-wrap to the pane width; PageUp/PageDown scroll vertically to the end. Actual
LF characters remain line breaks. Other non-printing characters (including tabs,
CR, escape codes and invisible directional controls) are shown as `<U+XXXX>`
markers so they cannot silently hide or reorder the displayed code. This is a
review representation, not an edited script: the original frozen request JSON,
script bytes, digest, acceptance binding and protected payload are unchanged.
Fixed helper requests without a script retain their entire frozen JSON display.
This UI-only correction needs an ordinary app restart, not helper reinstallation.

While processing, settings are accessible to **disable** elevation; other setting
changes remain blocked. Disable, turn exit, reset, shutdown or restart invalidate
unused approvals and wake waiters. They cannot undo already launched changes or
forcibly dismiss Windows consent. Late consent is refused at the helper deadline.
Approvals are volatile and never restored from history. Headless runtimes fail
closed rather than wait without an interactive approval frontend. Workers do not
receive the elevated tool or inherit head authority.

## General command tool

`run_elevated_shell_command(script, reason, timeout=30)` executes a complete
PowerShell script through the fixed native x64 system Windows PowerShell, with no
profile or interactive stdin. The current working directory is frozen into the
request. Local canonical directories without reparse points are required.

The general tool accepts an explicitly selected execution timeout of **1–900
seconds (15 minutes)**, defaulting to 30 seconds. This is independent of the
ordinary unelevated shell's unchanged 30-second maximum. Approval/UAC waiting is
separate, subject to the 30-minute turn authorization deadline; that deadline is
NOT an execution allowance. At worker launch the protected helper uses the smaller
of the requested timeout and remaining authorization time. Its policy independently
caps requests at 900 seconds and its native watchdog rejects zero or more than
900000 milliseconds before creating a process.

A retained, hash-verified general installation with `max_timeout=60` remains usable
only for requests up to 60 seconds. The client refuses longer requests before
pending/UAC; applying this source does not widen installed authority. Newly
reviewed installations use `max_timeout=900`. Existing installation replacement
requires a separately reviewed, hash-pinned deployment preserving prior evidence;
do not rerun the new-install-only installer or simply edit its policy.

Scripts are at most 32768 UTF-8 bytes; the whole review is capped at 65536 bytes.
The script snapshot is installed into the protected receipt directory with a UTF-8
BOM for PowerShell 5.1. A fixed, helper-authored encoded bootstrap configures UTF-8
console/pipeline output and invokes that snapshot; it does not replace the reviewed
script with opaque model-supplied code. Its exit handling preserves a nonzero
`LASTEXITCODE`, otherwise reports a failed final invocation as 1, else 0. Scripts
can intentionally change this state; process exit is not an effects audit.

Each stdout/stderr stream is continuously drained but retained only up to 25000
raw bytes and 4000 decoded characters. Truncation is explicit. Exit code zero is
process completion, **not verification of effects, successful cleanup, or image
acceptance**. The launcher clears nonessential inherited environment variables,
including provider keys and Python hooks, before starting the worker. This avoids
passing them accidentally; approved Administrator code can still access account
data and is not sandboxed.

The fixed evidence/inspection tools use the same setting and pending approval
interface, but are NOT general-script calls. Historically their native workers
could use the remaining 30-minute turn budget: the general tool's old 60-second
limit never applied to them. This explains why a multi-minute inspection could
run without bypassing the general launcher.

The updated fixed helpers instead cap complete worker execution (including
hashing, media preparation and descendant processes) at **900 seconds**, shortened
by approval expiry. Their protected policies must explicitly contain the integer
`max_execution_seconds=900`; clients refuse older/missing policies before pending
or UAC rather than silently use their longer deadlines. Pending review shows this
execution cap separately from the authorization deadline. Both the launch site
and native watchdog enforce the cap. The inspection worker's inner PowerShell
command limit is also 900 seconds, not the remaining turn budget.

This change does not deploy a helper, extend an approval, reset a consumed claim
or authorize another inspection. Existing protected installations/receipts must be
preserved through separately approved deployment/recovery review. In particular,
a consumed V2 must not be replaced/reinstalled merely to evade its claim. A single
turn allows at most one attempt of each fixed operation, even if rejected or
cancelled.

## Trust and failure boundaries

This is a **general Administrator executor, not a sandbox**. Approved code can
modify/delete files, install software, change ACLs, launch services/VMs/tasks,
access account data, or even modify its own launcher/receipts. Hash binding freezes
approved script text, **not every dependency or path the script later loads**.
Review referenced scripts/modules too; mutable checkout imports are not protected
merely because the top-level command was approved. Destructive operations require
explicit review of the actual targets and consequences.

Textual approval is a trusted-app safeguard. It is not an OS-enforced proof of a
human click against a compromised app. UAC confirms elevation of PowerShell; it
does not validate the command's meaning or identify every action on its prompt.
Protected receipts resist ordinary unelevated writes, not approved malicious
Administrator code. Do not describe them as universally tamper-proof.

The worker starts suspended, is assigned to a kill-on-close Windows Job, then
resumes. A native wait enforces its execution budget independently of the app's
progress/wait loop. At expiry the watchdog requests termination of the contained
process tree; it does not merely stop waiting. Termination observation can add up
to five seconds and general output draining up to another five seconds, plus
launcher/receipt overhead. These are not extra worker execution allowances.
The general tool returns `timeout_outcome_unknown`; fixed inspection remains
blocked/UNKNOWN and refuses partial success facts after timeout. Failed native
waits must not be misreported as observed timeout termination.

Services, Hyper-V VMs, scheduled tasks, external work,
and already written changes are not undone or proven stopped. Process loss,
missing/malformed receipts, or incomplete observation remain UNKNOWN. No automatic
retry, rollback, claim release, repair or broad cleanup is supplied.

## Auditing

The existing tool-call store records tool arguments and the returned outcome,
including request identity/review digest and the decision. This audit remains
best-effort and subject to its existing redaction/retention rules. UI notices also
remain visible in the conversation. The general launcher must durably write its
protected create-new start receipt before executing, or refuse. Protected files:

- `<id>.start.json`: permanent request claim, identity, reviewed digest, deadline.
- `<id>.approved.json`: the exact approved request bytes.
- `<id>.payload.ps1`: the reviewed script snapshot.
- `<id>.result.json`: bounded output, exit/timeout state, no verified effects.

The inbox is mutable transport data; its contents are hash-checked and copied into
protected storage before execution. A changed request or duplicate ID refuses.
Secrets should never be put into reviewed scripts, reasons, arguments or output;
these may be recorded or sent to the model/provider.

## Separately reviewed setup — do not run just because code was approved

New installation only:

```text
C:\Program Files\AiAgentElevatedCommands\
    helper.ps1
    policy.json
    requests\      # Intentionally operator-writable data inbox; never helper code
    receipts\      # Administrator-owned; operator read-only
```

Review this document, the helper/installer, test evidence, exact commit and helper
SHA-256 first. The app has no installer tool. In a dedicated native x64 Windows
PowerShell Administrator terminal under the same operator account, separately
approve setup and run the reviewed installer with explicit pinned inputs:

```powershell
.\scripts\install_privileged_command_helper.ps1 `
    -HelperSha256 '<reviewed exact helper SHA-256>' `
    -OperatorSid '<same account SID>'
```

Also verify the installer bytes against the reviewed digest before launching it.
No download, command execution, old-helper replacement, inspection retry or VM
operation occurs during setup. Existing/partial installations refuse overwrite;
stop and review failures rather than rerun, delete, or repair permissions.

Code tests use fake operations and ordinary unelevated native processes. They do
not establish live UAC, protected-install ACLs, or a successful Hyper-V inspection.
The preserved first failed inspection and consumed claim remain untouched.

## First deployment finding: empty file DACLs

After deployment of `d53916b`, the operator reported `status=installed` with
`launch_performed=false`. Unelevated read-back found the expected directory ACEs,
but access to `helper.ps1` and `policy.json` was denied. The operator's subsequent
Administrator read-only query reported both as Administrators-owned with a
protected empty DACL (`O:BA...D:P`, with no ACEs). The app's launcher validation
fails closed before approval/UAC. The request inbox and receipts directory were
observed empty; no general elevated command or live approval-flow pass is claimed.

Cause: passing an owner-only `FileSecurity` to the create-new `FileStream` does not
supply the parent's expected access rules. The helper's receipt/snapshot writer
used the same construction and requires the same correction. The code fix gives
files an explicit protected DACL: SYSTEM and Administrators full control, the
pinned operator read/execute only. Each write checks owner/group/DACL read-back
before reporting success or proceeding. It does not grant the operator write
access or change the separate writable-inbox policy.

The regression exercises these exact function definitions and the native file
creation overload in disposable unelevated fixtures. It checks the production
Administrators owner/group in memory, then substitutes the current user as
owner/group solely for fixture creation; the production DACL is unchanged. This
is not live validation of Administrator-owned installation or UAC.

The code fix does not modify the existing protected installation. Do not rerun
the new-install-only installer, delete its directory, or perform ad-hoc ACL repair.
Existing-install recovery needs a separately reviewed, hash-pinned procedure and
authorization. It must cover the corrected helper and its policy digest as well
as file access; merely unlocking the two old files leaves the receipt-writer bug.
Preserve the existing installation and all Hyper-V helpers, claims and evidence.
