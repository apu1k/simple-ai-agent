# Fixed Gate A task (candidate; not installed)

This is a separate, demand-only Windows Task Scheduler operation for the seven
real-host Gate A tests. It reuses the **exact image bytes** from the passing run,
does not rebuild the image, and starts no general elevated shell. It does not
change the existing elevated tool, policy, approvals or receipts.

After one reviewed Administrator installation, the selected Windows account can
request a run without a new UAC prompt. The task is `\AiAgentGateA`, runs under
SYSTEM, has one fixed action and a 15-minute Scheduler execution limit, and
ignores duplicate launches while active. The operator can read/execute the
fixed task but cannot modify it or its installed package. It accepts no chat
text, filenames, case selections, environment overrides, executable paths or
command parameters from a caller. Ordinary checkout files are not loaded by the
installed runner.

## Review and install once

1. Obtain the official **x64 Windows embeddable CPython 3.14 ZIP** and pure
   Python wheels for `pytest`, `iniconfig`, `pluggy`, `pygments`, `packaging`, and
   `colorama`. Review their provenance and exact digests separately. The ZIP
   builder never downloads dependencies; do not source them from an arbitrary
   executable already found on PATH or copy a mutable virtual environment.
2. In the ordinary repo session, build with `python -m
   night_shifts.gate_a_install_bundle --output <new.zip> --python-zip
   <reviewed-embed.zip> --pytest <wheel> --iniconfig <wheel> --pluggy <wheel>
   --pygments <wheel> --packaging <wheel> --colorama <wheel>`. Review the
   bundle contents (including the compiled runtime, test dependencies and
   source commit) and independently check its printed SHA‑256. The bundle
   includes the Gate A tests and package code, not the entire live checkout.
3. In a **separately approved** native x64 Windows PowerShell Administrator
   session, review and run the installer with canonical local paths:

   ```powershell
   .\scripts\install_gate_a_task.ps1 -BundlePath '<reviewed bundle.zip>' `
       -BundleSha256 '<independently checked SHA-256>' `
       -BaseImage 'D:\NightShift\gate-a\gate-a-32e883a99e1f493b84494d1930e5dafe\base.vhdx' `
       -OperatorSid '<same Windows account SID>'
   ```

   It needs space for a **separate ~4.6 GB protected copy** of the passing
   base, plus temporary disks/logs. It verifies the copied image against
   `13bc986452a63d145b6cdd2d5b79e629d9244745269b0996b3bf24daf39894d6` before
   registering anything. It installs under `%ProgramFiles%\AiAgentGateA` and
   does not run the task. There is no overwrite, repair, or retry after an
   uncertain install. Inspect retained state before any separately approved
   recovery or uninstall. Lack of this setup does not affect attended Gate A.

## Start and read the result without elevation

From the ordinary repo session:

```powershell
.\.venv\Scripts\python.exe -m night_shifts.gate_a_task start
.\.venv\Scripts\python.exe -m night_shifts.gate_a_task status
```

`submitted` is a Scheduler acknowledgement, not evidence of execution. Look
for a **new** run directory in the next receipt. The runner writes
`running_or_unknown` before any VM activity and publishes a terminal receipt
only when the run returns. `%ProgramFiles%\AiAgentGateA\runs` holds `latest.json`,
all per-run `report.json` files and test logs. A previous non-passing or unknown
receipt blocks new runs; this client cannot clear it. Use Scheduler readback and
separately reviewed operator inspection to diagnose a missing terminal receipt.
Do not infer that a hard limit, a stopped process or a closed window removed any
VM.

## Live acceptance for tasks 1 and 2

1. After installation, verify the registered principal, action, demand-only
   settings, time limit and ACL; verify the operator can read/run but cannot
   change the task or write the installed code, base or receipts. Verify that a
   normal call requests no UAC. Confirm the task refuses request parameters and
   no unreviewed code or pytest configuration can enter through the client.
2. Start the task unelevated, wait for the new run receipt, and close the chat
   app during a test. Reopen it. Confirm the independent task finished **7/7**,
   its before/after VM inventory matches, it left no sandbox folders, and the
   protected image hash is unchanged.
3. Separately validate interrupted-run recovery using a disposable attended
   test, per [Gate A live runs](night_shift_gate_a_live_runs.md). After verifying
   process and provider quiescence, preview and apply cleanup, and verify exact
   VM and disk absence. This check requires its own approval. Do not deliberately
   kill the installed task and then try to clear its protected receipt in order
   to get a passing test.

The task survives closing the chat because the Scheduler owns it, not because
we installed the candidate exact-VM watchdog. A crash, forced stop, or host
restart that kills the *protected runner* is a different case. It remains an
unknown result until separately inspected; there is no automatic destructive
cleanup or re-execution in that case. The existing single-VM watchdog requires
proof of provider-operation settlement and is not wired to this multi-case
runner.
