# Gate A live runs (2026-11-22)

First live attempts of `python -m night_shifts.gate_a_run` through the elevated
command helper. Gate A has **not passed** yet.

## Results

| Attempt | Outcome |
|---|---|
| 1 | Nothing ran. The `&` call operator silently does nothing inside the helper (no output, empty `$LASTEXITCODE`); the wrapper still reported exit 0. |
| 2 | Copy, WSL cleanup and detach succeeded. Stopped at the Hyper-V VM inventory with `FileNotFoundError` (`powershell.exe` not on `PATH`). |
| 3 | `test_real_host_prerequisites` passed. `test_real_host_serial_round_trip_and_cleanup` hung ~13.5 min until killed; 5 cases not started. One VM and its sandbox folder left behind (`cleanup_unknown`). |
| 4 | Same pattern, killed at the 420 s case cap (run `gate-a-e445a867…`). Stack dump located the hang (see below). VM `night-shift-b531690a41d142d78e2fa9251c07a78e` and its sandbox folder left behind. |

Cleaned base image (attempt 2, reusable via `--base-image`):
`D:\NightShift\gate-a\gate-a-7ad0a82d93fa4248bbbefc0528bf1f3e\base.vhdx`,
SHA-256 `4ccedb4f00fbe3b9726f21a9909ef563ab95305fdbd03e3c557ed657e171b667`.
Cleanup audit `pass`; removed the three `etc/night-shift-diagnostic-027/*`
files and the `debug-shell.service` wants-link.

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

## Next

1. Add the `ready` handshake (guest bootstrap + host transport) and update the
   guest file in a fresh cleaned image via the WSL path.
2. Rerun Gate A; the close fix ensures a failing case still removes its VM.
3. Remaining cases: rejection, disconnect, cancellation, timeout, reconciliation.
