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

The maximum execution timeout is **60 seconds**, derived in Python as twice the
ordinary shell tool's 30-second maximum. Approval/UAC waiting is separate, subject
to the turn deadline. The protected policy independently caps execution at 60
seconds. A future ordinary-limit change requires a separately reviewed launcher
policy/code change; it must not silently increase installed authority.

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
interface but retain their separately installed policy, operation-specific scope,
longer workflow deadlines, and one-attempt constraints. This change does not reset
the consumed inspection claim or redeploy either old helper. A single turn allows
at most one attempt of each fixed operation, even if rejected or cancelled.

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
resumes. A timeout kills job-contained processes where possible and returns
`timeout_outcome_unknown`. Services, Hyper-V VMs, scheduled tasks, external work,
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
