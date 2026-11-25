# Gate A live runs (2026-11-22)

Live attempts of `python -m night_shifts.gate_a_run` through the elevated
command helper. **Gate A passed on attempt 6 (2026-11-24): 7/7 real-host cases,
no leftover VMs or sandbox folders.**

## Results

| Attempt | Outcome |
|---|---|
| 1 | Nothing ran. The `&` call operator silently does nothing inside the helper (no output, empty `$LASTEXITCODE`); the wrapper still reported exit 0. |
| 2 | Copy, WSL cleanup and detach succeeded. Stopped at the Hyper-V VM inventory with `FileNotFoundError` (`powershell.exe` not on `PATH`). |
| 3 | `test_real_host_prerequisites` passed. `test_real_host_serial_round_trip_and_cleanup` hung ~13.5 min until killed; 5 cases not started. One VM and its sandbox folder left behind (`cleanup_unknown`). |
| 4 | Same pattern, killed at the 420 s case cap (run `gate-a-e445a867…`). Stack dump located the hang (see below). VM `night-shift-b531690a41d142d78e2fa9251c07a78e` and its sandbox folder left behind. |
| 5 | Fresh copy cleaned with the `ready`-handshake guest script (run `gate-a-32e883a9…`). Round-trip case ended in 20 s; VM and disk removed, but `Remove-VM` left empty `vm-config\<name>\Virtual Machines` dirs, so the workspace `rmdir` failed (WinError 145) and the cleanup error hid the job result. Fixed: remove only empty config dirs; keep the job result in cleanup errors. |
| 6 | **Passed** (run `gate-a-541c03ed…`, 398 s, `--base-image` from attempt 5). All 7 cases passed: prerequisites, round trip, rejection, disconnect, cancellation, timeout (243 s), reconciliation. Inventory before/after equal; no sandbox dirs left. |

Gate A base image (attempt 5, with `ready` handshake):
`D:\NightShift\gate-a\gate-a-32e883a99e1f493b84494d1930e5dafe\base.vhdx`,
SHA-256 `13bc986452a63d145b6cdd2d5b79e629d9244745269b0996b3bf24daf39894d6`.

Superseded cleaned image (attempt 2, old guest script):
`D:\NightShift\gate-a\gate-a-7ad0a82d93fa4248bbbefc0528bf1f3e\base.vhdx`,
SHA-256 `4ccedb4f00fbe3b9726f21a9909ef563ab95305fdbd03e3c557ed657e171b667`.
Cleanup audit `pass`; removed the three `etc/night-shift-diagnostic-027/*`
files and the `debug-shell.service` wants-link.

## Recovering an interrupted run

Use an elevated Windows terminal from the repository root. Pass the **one run
folder** whose `report.json` and `sandboxes` you want to inspect. The first
command is a read-only preview; only `--apply` changes VM or disk state.

```powershell
.\.venv\Scripts\python.exe -m night_shifts.gate_a_cleanup --run-dir 'D:\NightShift\gate-a\gate-a-<full-run-id>'
.\.venv\Scripts\python.exe -m night_shifts.gate_a_cleanup --run-dir 'D:\NightShift\gate-a\gate-a-<full-run-id>' --apply
```

Before applying, confirm the old runner, its pytest and PowerShell children,
and any in-flight Hyper-V operation for the run have stopped. If that's
unknown, use preview only. The run lock prevents concurrent use by the new
runner; it is not proof that a child or an admitted provider operation exited.
A timeout is not proof of cleanup or permission to retry.

The command finds sandbox IDs in the selected run's sandbox folder and any
new VM names captured in its report. It does not sweep other runs or use a name
prefix alone. It retains preexisting VMs and refuses mismatched ownership,
paths, disk parent, references, or linked entries. It removes verified
`worker.vhdx` disks and empty sandbox directories only; it never removes the
base image, the run report, or the logs. `review_needed` means some state could
not be verified or safely removed. Capture the JSON stdout for the cleanup
record; it does not replace the original Gate A report.

This is attended recovery, not an automatic watchdog. Live acceptance is a
separate check: in a fresh test run, deliberately leave one disposable sandbox
behind, verify that the runner and children have stopped, then preview and
apply. Confirm the exact VM ID/name and sandbox path are gone, the before/after
inventory of unrelated VMs is unchanged, and the pinned image hash is unchanged.

## Elevated helper environment

The helper runs as the interactive user (`JULIANPC\JulianSiek`, profile `jul20`),
admin, FullLanguage PowerShell 5.1, but with a stripped environment:

- **`&` does not run native programs.** Use `System.Diagnostics.Process` (or
  `Start-Process -Wait -PassThru`) and treat a missing exit code as failure.
- **`COMPUTERNAME` is missing.** Hyper-V cmdlets then fail in
  `Server.GetServer(name)` with `Value cannot be null. Parameter name: name`.
  Reproduced unelevated by removing only `COMPUTERNAME`.
- **`PATH` lacks `System32\WindowsPowerShell\v1.0`.** Bare `powershell.exe`
  fails; `wsl.exe` still works because `System32` is always searched.
- Helper output is truncated around 16 KB; print summaries and keep detail in
  `report.json`.

`gate_a_run.ensure_host_environment()` now fills `SystemRoot`, `WINDIR`,
`COMPUTERNAME` and the System32/Wbem/PowerShell `PATH` entries for itself and
every child. `gate_a_fixed_actions.py` already set these explicitly.

## Serial round-trip hang

Evidence from the leftover VM `night-shift-66cf6632914d4ea087a74ea9430f76d3`
(ID `f73a5ca3-67e1-4712-a002-f73023b17cf3`) before removal:

- Running, uptime 16 min, CPU 0 %, Gen 2, Secure Boot on (Microsoft UEFI CA).
- Heartbeat `OK`, so the Ubuntu guest booted and its Hyper-V integration runs.
  KVP `No Contact`.
- COM1 → `\\.\pipe\night-shift-66cf6632914d4ea087a74ea9430f76d3-com1`; single
  disk `worker.vhdx` in its sandbox folder; network adapter unconnected.

So the guest booted but no reply arrived over COM1, and the host kept waiting
far past the 180 s job timeout. Likely, unconfirmed: the guest protocol service
is not serving `ttyS0` (matches the earlier `Input/output error` on the
diagnostic boot), and the host serial read has no timeout of its own. The test
log was empty because pytest ran with `-q` and the timeout path dropped stderr.

`gate_a_run` now runs each case with `-v -s`, keeps stdout and stderr on a kill,
dumps all thread stacks after 300 s (`faulthandler_timeout`), and caps each case
at 420 s.

### Attempt 4 stack dump: host-side close deadlock

- Reader thread blocked in `HyperVSerialTransport._read_message` →
  `channel.read()` (guest still silent).
- Main thread blocked in `HyperVSerialTransport.close()` →
  `channel.close()`, called first in `SandboxWorker._cleanup`.

On Windows, closing a synchronous handle waits for another thread's pending
`ReadFile` on it. So once the job timeout fired, cleanup hung on the pipe and
never reached `provider.destroy()` — that is why the VM leaked, not a missing
timeout. Fix: `close_channel()` closes on a helper thread while cancelling
pending I/O with `CancelIoEx`, gives up after 5 s and lets teardown proceed
(stopping the VM releases the pipe). The guest still never replied; that is the
remaining Gate A blocker.

### Attempt 4 guest inspection

The leftover VM `night-shift-b531690a…` (Running, uptime 21 min, CPU 0 %,
heartbeat OK) was turned off and its `worker.vhdx` mounted read-only
(`ro,noload`) in WSL. Saved to
`D:\NightShift\gate-a\inspect-b531690a\inspection.txt`.

- Image correct: Ubuntu 24.04.5, protocol unit enabled, `serial-getty@ttyS0`
  masked, bootstrap script present, no `console=ttyS0` on the kernel command
  line. No persistent journal; only the last 200 syslog lines were kept, and
  they contain no `night-shift` unit messages.
- Boot finished after 2 min (`systemd-networkd-wait-online` times out without
  a network).
- **The VM never powered off.** The unit has `SuccessAction=poweroff` and
  `FailureAction=poweroff`, so the bootstrap never exited: it was blocked
  waiting for a task.

Likely cause: a startup race. The host sends the task as soon as Hyper-V
reports `Running` (firmware/bootloader time), long before the guest opens
`/dev/ttyS0`. Bytes that arrive before the tty is open are discarded, so the
guest waits for a task and the host waits for a result. Fix: the guest
announces `ready` after opening the port and the host sends the task only after
that frame (needs the guest file in the image updated).

## Cleanup

The leftover VM was removed after an ownership check (name, single disk path in
its sandbox folder), confirmed gone by ID, and its sandbox folder deleted.

Seven older VMs from earlier work remain and were not touched:
`night-shift-finalize-{2f2ea761…, 40ac18e1…}`,
`night-shift-image-prep-{20ce30aa…, 2486645f…, 6584fc35…, 8e3e0fce…}`,
`night-shift-recovery-8c4c51e2…`.

## Next (historical, done)

1. Remove the seven older VMs above in a separate scoped cleanup. *(Done: all
   seven removed and confirmed gone.)*
2. Protected runtime Gate A: trigger the same run as a fixed operation without
   per-run elevation approval. *(Done: see below.)*

## Gate A through the fixed scheduled task (2026-11-24)

One-time elevated install of `\AiAgentGateA` (SYSTEM, no triggers, demand-only,
`PT15M`, `IgnoreNew`) into `C:\Program Files\AiAgentGateA`, with an embedded
Python 3.14.8 (python.org SHA-256 verified) and six PyPI wheels (SHA-256
verified). The operator account has read/execute only; writes to the install
folder, `runs\` and code were refused. Runs are started unelevated with
`python -m night_shifts.gate_a_task start` and read with `... status`.

| Install | Bundle SHA-256 | Result |
|---|---|---|
| 1 | `23406485...4805d` | **failed** after 2.6 s, `KeyError: 'SystemRoot'`; no VM created |
| 2 | `e2fb2e9a...260c` | **failed**: prerequisites passed, reply test got an invalid JSON line after `protocol_test_echo`; VM removed, no leftovers |
| 3 | `b0883bb7...1f3b` | **passed 7/7** in 388.6 s, no new VMs, no sandbox folders |

Findings:

- **Bundle missing `llm/base.py`** (`night_shifts/__init__.py` imports
  `night_shifts.inference`). Caught in review before install; the bundle now
  ships `llm/__init__.py` + `llm/base.py` and a test imports the Gate A modules
  from an extracted bundle only.
- **Install 1:** `{**os.environ}` has upper-case keys on Windows
  (`SYSTEMROOT`), so the fixed child runner's `env['SystemRoot']` failed on the
  first PowerShell call (listing VMs, before any test). Fixed by resolving
  PowerShell via `GetSystemWindowsDirectoryW`.
- **Install 2:** intermittent invalid JSON line from the guest after the echo
  event. Guest writes are single-threaded and the host line splitter is
  correct; **cause unknown**. It did not recur in install 3. Worker JSON errors
  now include position, length and a 160-character escaped excerpt, so a
  recurrence shows what arrived. Treat as an open risk.
- **Evidence:** install 1's run files were lost during the first reinstall
  (`Copy-Item -LiteralPath` with `*` copied nothing, without error); recreated
  from the session in `D:\NightShift\gate-a\task-attempts\install-1\`.
  Install 2's files were copied and SHA-256 verified per file before removal
  (`task-attempts\install-2\`).

Install 3 run `gate-a-d34858715f4f4eaaa8c193d2e2d9c9ca` (19:54:05-20:00:34 UTC):

| Test | Result | Time |
|---|---|---|
| Prerequisites | passed | 4.0 s |
| Fixed reply over COM1, then cleanup | passed | 20.5 s |
| Unsupported task rejected | passed | 30.5 s |
| Guest disconnect | passed | 31.4 s |
| Cancellation | passed | 28.0 s |
| Timeout forces cleanup | passed | ~244 s |
| Restart cleanup removes only its orphan | passed | ~30 s |

**Chat-close check:** the operator closed the agent app for about one minute
while the run was in progress; the task kept running (it is independent of the
app), and the result was read after reopening. Task Last Result `0`.

## Recovery check after an interrupted run (2026-11-24)

One approved elevated request (commit 9ddaec3), run
`D:\NightShift\gate-a\gate-a-874de6552b04489f89be94c70c4c94ec`:

1. Preconditions: scheduled task idle, no `night-shift-*` VMs.
2. Started an attended `gate_a_run` with only the timeout test against the
   passing image on `D:`.
3. After 23 s its VM `night-shift-55fd80efe23e46c7b85cae14990217ad`
   (ID `adbb8495-a1c8-4c6d-be9b-6b541a83cebf`) was `Running` with
   `worker.vhdx` in its sandbox folder; waited 10 s more.
4. Force-killed the whole runner tree (4 `python.exe` + `conhost.exe`); all
   gone 5 s later. Result: report status `running`, VM still `Running`, sandbox
   folder present, `preexisting_sandbox_vms` empty.
5. `python -m night_shifts.gate_a_cleanup --run-dir <run>`: `preview`, sandbox
   classified `vm_candidate`.
6. `... --apply`: `clean`.
7. Independent check: VM absent by ID and by name, no `night-shift-*` VMs,
   sandbox folder gone, `base.vhdx` SHA-256 still `13bc9864...94d6`.

The run folder is kept as evidence (`report.json`, `.gate-a.lock`, empty
`sandboxes`).

Scope: this proves manual recovery after a hard kill of an attended run. It
does not cover a killed **scheduled task** run: that leaves `latest.json` at
`running_or_unknown`, which blocks new starts until an administrator reviews
it; there is no automatic watchdog cleanup yet.

## Reply stress test (2026-11-25)

Goal: measure how often the one-off `Invalid worker JSON: Expecting value`
failure (task install 2) recurs. Elevated helper, repo venv, only
`test_real_host_serial_round_trip_and_cleanup`, 15 consecutive runs against the
Gate A base image (`13bc9864...94d6`), job timeout 120 s, per-run cap 300 s.

- **15/15 passed**, 25.8-27.3 s each (`D:\NightShift\gate-a\stress-20261125-065405`,
  `summary.json` and one `pytest.log` per run). No invalid JSON.
- No leftover VM or sandbox entry after any run; Hyper-V inventory identical
  before and after; base image last-write time unchanged.
- Two earlier attempts the same morning did not run any test: the script
  missed the documented helper fixes (missing `COMPUTERNAME` made `Get-VM`
  fail; `&` silently did not start Python). A read-only check confirmed
  Hyper-V was healthy with no VMs or stale configs.

Interpretation: the failure is rare. Zero failures in 15 runs puts the rate
under roughly 20% (95% bound) for this path. It does not rule out a cause
specific to the SYSTEM scheduled task, where the only failure occurred.

## Next

1. If the invalid-JSON failure recurs, use the new excerpt to find the cause.
   Before Gate B, consider repeating the stress test through the scheduled
   task path (SYSTEM) as well.
2. Decide whether the scheduled task should run `gate_a_cleanup` itself on the
   next start after a `running_or_unknown` receipt, or keep that manual.
