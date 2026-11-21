# Gate A exact-VM watchdog candidate (not installed)

`night_shifts.gate_a_watchdog` implements a one-shot watch/cleanup sequence
shared by automatic image finalization and the fixed smoke run. The Windows
adapter waits on exact held process handles and a local cancellation event;
it does not discover a target process by PID, poll the chat, or depend on the
runtime unwinding. Its armed event is a readiness acknowledgement, not a
launch grant. These modules are not a service, installer, command entry point,
or replacement for the protected launcher and permanent attempt claim.

## Required host ownership and order

1. From independently reviewed protected inputs, a host owner claims one
   fresh attempt, privately holds workspace/configuration, media, and the
   exact VM GUID, and sets the original absolute monotonic cap. The cap is at
   most 900 seconds; normal work must stop 30 seconds before it. Preparation,
   VM creation and the interval before the watchdog has a GUID are the
   **protected owner's** responsibility, not managed by this core. In
   particular, losing `New-VM` output cannot justify a name-based cleanup.
2. Before allowing a start, bring up the watchdog **outside** both the runtime
   and guest-exchange worker processes, and outside any job the runtime can
   terminate. Transfer authenticated, non-inheritable synchronization handles:
   runtime and worker process handles with query rights, and separate
   manual-reset `cancel` and `armed` events. The launcher must retain them and
   must verify the exact fresh VM is Off and correctly configured. It must
   serialize its start path against the permanent lifecycle seal and make any
   work cutoff effective independently of the guest. A pre-signaled handle or
   the work cutoff before arming skips readiness. The launcher still has to
   check its own gate and deadline even if it observed `armed`.
3. On exact runtime/worker exit, cancellation, deadline, or bad signal, stop
   admitting VM writes. Prove any admitted lifecycle operation has actually
   settled **in Hyper-V**, not just in its client process. The lifecycle seal
   must do both, atomically with respect to admission. No controller, guest
   exchange worker, chat, or secondary cleanup code may be a lifecycle writer.
   If quiescence cannot be proved, do not race a potentially in-flight start:
   retain the claim and report unknown. The worker exit/cancel signal carries
   no result or authority for VM changes.
4. Only then run the held, pinned `reconcile_gate_a_vm.ps1` action once for the
   exact GUID and fixed operation, under the original cap and a protected
   process lifetime bound. Capturing output must be bounded at the source; never
   submit an arbitrary path or command from the runtime. `finalization` retains
   the copy; `smoke` must use `-RemoveSmokeDisk` and positively observe disk
   absence. Successful output must match the bounded schema, attempt, GUID and
   disk policy. Late/malformed/failed evidence is unknown; no retry, broad sweep,
   repair, claim release or rollback follows from this watchdog.
5. Publish protected host evidence separately from the guest audit or smoke
   reply. Even a verified cleanup receipt does not prove image acceptance or
   Gate A success. No result, an independently killed watchdog, or an
   unresponsive host remains unknown until separately investigated.

The current code supplies the wait adapter, fixed disk policy, the deadline
and teardown sequence, and receipt validation. The installed independent role,
handle delivery, start/settlement gate, pinned action invocation and durable
receipt integration are not supplied by this candidate. Unit tests exercise
mock lifecycle ordering, native Windows event/process signals from outside the
fixture children, and receipt compatibility with the teardown script using
**fake Hyper-V cmdlets only**. They do not perform UAC, installation, live
recovery, or real-VM teardown.
