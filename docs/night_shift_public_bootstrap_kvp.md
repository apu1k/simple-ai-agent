# Public-only Linux KVP publisher and exact-VM host reader — source candidate

**Verified offline after the applied test-ID correction; live feasibility unrun.**
This is the next integrated-bootstrap building block, not another marker-store
fixture. It implements native adapter code but does not deploy it, invoke WMI, publish KVP,
generate a credential, operate a VM, retry inspection or enable Gate A. See the
[credential/bootstrap boundary](night_shift_maintenance_credentials_design.md),
[pipe review](night_shift_pipe_security_review.md) and
[current status](night_shift_status.md). Existing claims, source/scripts, protected
fixtures and receipts remain untouched; neither failed fixture becomes a pass.

## Source boundary

- `night_shifts/public_bootstrap_kvp.py`: bounded Linux pool record encoding and
  append-policy parsing; strict WMI embedded-item XML parsing; a cooperative
  deadline/cancellation budget. Reuses the existing public certificate codec.
- `night_shifts/guest/publish_public_bootstrap.py`: explicit Linux/root-only
  function. Walks `/var/lib/hyperv` with retained relative directory descriptors,
  no-follow opens and root ownership/no group-or-other write checks. Opens only
  the EXISTING `.kvp_pool_1`; requires a regular single-link root-owned pool.
  Acquires a whole-file nonblocking POSIX record lock with bounded polling,
  rejects malformed/oversized/duplicate pools or ANY reserved-name collision,
  appends one fixed item and reads back the exact old prefix plus new record.
- `night_shifts/public_bootstrap_host.py`: explicit local Windows x64 reader.
  Uses native system PowerShell and local `root\\virtualization\\v2` .NET WMI,
  selecting a canonical VM GUID from a trusted future attempt. It requires the
  fresh feasibility name `night-shift-bootstrap-<attempt>` and sole Notes marker
  `night-shift-bootstrap-owner:<attempt>`, running VM/current realized settings,
  and exactly one enabled/healthy KVP component scoped to that same VM. It reads
  only `GuestExchangeItems`, not host/intrinsic pools. It repeats name/owner/state
  checks around acquisition and freezes the first VM state stamp and public key.

There is no CLI, service/daemon control, pool creation, file replacement/truncation,
permission repair, arbitrary path/key/value interface, network connection, serial
exchange, protected installer or VM lifecycle operation. The new files are not
in the existing inspection bundle and no existing production caller imports them.
Public APIs do nothing at import. Calling the publisher/reader is a separately
reviewed operation, not part of applying or testing this source batch.

## Native/wire details

Linux daemon records contain a **512-byte key array plus 2048-byte value array**.
They are UTF-8/ASCII NUL-terminated strings, not UTF-16 pool records and not the
kernel `hv_kvp_msg` packet. The kernel converts strings for the Windows transport.
The fixed public JSON remains <=1000 ASCII bytes with <=512 CA DER bytes; it
contains only the existing version/operation/attempt/VM/public-CA/leaf-pin fields.
No split values, private-key fields or generic payload writer are added. A typed
public certificate is not a DLP guarantee for arbitrary certificate extensions;
its future trusted factory must enforce the fixed certificate profile.

Use `fcntl`/`lockf` whole-file record locks, **not `flock`**, to coordinate with
`hv_kvp_daemon`. Preserve every unrelated record byte including post-NUL padding;
the daemon can leave nonzero padding. Never recreate/rename the pool underneath a
daemon retaining its inode. Refuse an existing reserved name even if identical.
One append syscall is attempted; a short/error write or cancellation/timeout after
possible mutation is **publication_unknown**. No retry, rollback or cleanup is
performed. Local read-back does not prove host receipt or durable persistence.

Only trusted, serialized publication in a fresh reviewed recovery guest is in
scope. POSIX record locks are per process; closing another descriptor to the same
inode can release them. The caller must not open/close this pool concurrently in
another thread. The daemon's separately locked read/modify/write operations do
not give a general transactional multi-writer protocol. Concurrent modification
of pool 1 must be excluded by the reviewed live setup, not assumed safe from this
append lock alone. Malicious guest root is outside this file-permission boundary.

Host acquisition is bounded to 32 embedded items, 8192 characters per XML item,
65536 aggregate XML characters and 128 KiB internal process capture. XML rejects
DTD/entity declarations, comments/CDATA, unexpected classes/properties/types,
duplicate properties/names and nested/ambiguous values. Source must be exactly
`1`. Only one reserved public record is selected; stale/wrong-attempt/malformed
records fail instead of being ignored. Absence can be polled only before the
first record. Changed CA/pin, disappearing record or changed VM state stamp
terminally closes the reader, without refresh, retrust or automatic polling.

Internal provider snapshots can contain unrelated public KVP values; they must
never be printed or attached to launcher receipts. Errors expose fixed labels
only. A future live fixture must emit a compact independently bounded report of
identity, public fingerprints, elapsed time and outcome, not raw snapshots.

## Limits and remaining live proof

The name/Notes/state checks are non-atomic stability observations, not a permanent
claim, image/content audit, boot attestation, full VM-confinement check or proof
that a guest possesses the advertised private key. KVP can cache/persist across
boots. The caller must independently establish a fresh claim, newly created VM,
reviewed trusted recovery code and integrity-protected binding seed, with no
reboot/save/checkpoint/migration or target execution. GUID/string matching or a
synthetic WMI snapshot alone cannot confer those facts. Actual TLS chain/time/role
validation and peer-pin/key-possession checks still come later.

The 30-second maximum budget and two-second WMI enumeration timeouts are not a
hard end-to-end guarantee: provider connection and native filesystem calls can
block. Host output is drained into bounded storage; timeout/cancellation attempts
to terminate the reader, with bounded termination waits. That does not stop a WMI
operation already executing inside the provider, or stop/remove a VM. A future
live runner still requires the protected native watchdog and explicit resource
state evidence; uncertain reader/VM termination remains UNKNOWN.

### Applied offline verification — standard rerun passed

The initial ordinary pytest invocation hit Windows' 32767-character environment
variable limit: pytest expanded two large byte parameters into unbounded test IDs
used in `PYTEST_CURRENT_TEST`, causing setup/teardown errors. No adapter assertion
failure or live provider access was observed. The applied test-only correction
gives both byte-parameter groups short explicit IDs; inputs, assertions and
runtime source are unchanged. The normal post-application reruns below passed
without any transient ID hook or runtime substitution. This source/test batch
is ready to commit, not ready for deployment or live execution. A separate earlier
attempted related command named a nonexistent test file and collected no tests;
the corrected existing-file selection passed.

The standard command `python -m pytest -q tests/night_shifts/test_public_bootstrap_kvp.py -rs`
passed **88 with 1 Linux skip** in 1.94 seconds. The normal combined ten-file
targeted selection passed **495 with 3 skips** in 6.03 seconds, INCLUDING those
88. Both ran without the earlier transient pytest-ID hook. The other skips were
unelevated symlink creation in the native-store and protocol-bundle fixtures.
The earlier hooked runs had the same counts; they are historical, not additional
coverage. Earlier separately run groups were credential/TLS/native-store/comparison
**307 with 1 skip** and maintenance/guest/diagnostic/protocol-bundle/Linux-payload
**100 with 1 skip**; these too are subsets of the 495.

Repository Ruff and Mypy across **79 source files** passed again, as did strict
parsing/compilation of all four new Python files, PowerShell parsing and synthetic
provider selection, local document links and `git diff --check`. These are targeted
checks, not a full-repository result.

The actual in-memory inspection ZIP had 31 entries and excluded all new adapters.
Both executed native-store fixture scripts and the existing inspection runtime/
bundle files matched HEAD after canonical LF comparison. All three prior result
receipts were independently rehashed and matched their documented pinned SHA-256
values; no protected marker data was accessed. No prior outcome was reclassified.

These tests make **no real WMI query or guest pool access**. The Linux disposable-fd
test substitutes ordinary ownership explicitly and skipped on this Windows host
without a WSL/VM fallback. PowerShell's native provider function is removed before
synthetic selection execution; its normal source is parsed, not queried. Models
and synthetic PowerShell selection are not live provenance evidence. No elevation,
service change, real credential, VM operation or protected deployment occurred.

Next live milestone is a separately designed/approved **non-secret feasibility
probe**: establish the exact reviewed ISO/daemon/runtime and Data Exchange state,
use a fresh isolated diskless recovery VM and attempt (never V1/V2), publish a
reviewed public synthetic record, observe it through the exact-VM reader within
the bound, independently capture the compact outcome and confirm VM cleanup.
Do not auto-enable Data Exchange, GSI, networking or install a missing daemon.
An unavailable or untrustworthy path stops this candidate for alternative-design
review; there is no plaintext or permission-widening fallback. A fixed synthetic
record may establish plumbing, never production peer authentication.

Production host-key factory/storage/loading, Linux RAM-key generation, live TLS
serial adapters, protected deployment, image inspection/finalization/publication,
the separate Gate A transport boundary and real Gate A cleanup tests remain open.
No elevation or restart is needed for source verification. Do not run either
native adapter manually or enable elevation for this draft.

## Reference material, not reviewed ISO/deployment evidence

- [Linux Hyper-V UAPI v6.8](https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/hyperv.h)
- [Upstream hv_kvp_daemon](https://github.com/torvalds/linux/blob/master/tools/hv/hv_kvp_daemon.c)
- [Msvm_KvpExchangeComponent](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/msvm-kvpexchangecomponent)
- [Msvm_KvpExchangeDataItem](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/msvm-kvpexchangedataitem)

These were read as reference text only, not installed or executed. The recovery
ISO's exact daemon implementation/version and provider behaviour are unvalidated.
