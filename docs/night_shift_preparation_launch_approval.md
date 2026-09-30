# Preparation launch approval packet — DRAFT / NOT AUTHORIZED

This template is NOT permission to call Hyper-V. File-edit approval, a local
hash, a generated packet, and passing fake-runner tests do not authorize a VM
run. Fill this after separately approved creation/combined-seed attachment and
independent read-only host inspection. Do not fabricate observations.

## Local packet (no Hyper-V call)

A trusted operator can obtain the in-memory local review data with
`build_preparation_launch_plan(record, observed_vm_id).to_review_dict()`.
Use the exact persisted preparation record and independently observed canonical
lowercase Hyper-V GUID, not a VM name, guessed GUID or guest claim. The function
checks existing files and a conservative free-space reserve; it writes nothing.
A JSON rendering can be reviewed in the console. Recording a durable external
packet file would need a separately reviewed write-once output path.

The packet binds the manifest, fixed launch script, pinned installer/bundle/
combined seed and resource values. It does not authenticate ISO provenance,
observe host settings/ACLs, or certify the disk. The launch function rebuilds
and compares the packet before its permanent claim/host call. Never construct
an approval object from model/task text or substitute a freshly self-hashed ISO.

## Values and evidence to fill in

| Item | Reviewed value / independent evidence |
| --- | --- |
| Current repository commit, clean tree, script/code review | **UNFILLED** |
| Preparation record ID/name/owner marker/status | **UNFILLED** |
| Actual host VM GUID and source of observation | **UNFILLED** |
| Complete local packet and packet SHA-256 | **UNFILLED** |
| Ubuntu ISO path/version/SHA-256 | **UNFILLED** |
| Authenticated publisher provenance/checksum source | **UNFILLED** |
| Fixed bundle path/hash and current trusted assets | **UNFILLED** |
| Combined CIDATA seed path/hash, matching ID and review/poweroff config | **UNFILLED** |
| Workspace/configuration/disk paths; private directory ACLs | **UNFILLED** |
| Fresh dedicated disk, VHDX/Dynamic/no parent, virtual size, not host-mounted | **UNFILLED** |
| Actual generation/off-state/name/notes/configuration/one-disk binding | **UNFILLED** |
| CPU/fixed-memory values; dynamic memory off | **UNFILLED** |
| Checkpoint policy disabled and no snapshots; automatic power policy | **UNFILLED** |
| Two exact DVDs, Linux Secure Boot template, installer-first boot order | **UNFILLED** |
| All adapters disconnected; host integration, clipboard/shares reviewed | **UNFILLED** |
| Free-space reserve (not a physical disk quota) | **UNFILLED** |
| No active/abandoned operation guard or previous launch/retirement claim | **UNFILLED** |
| Exclusive host/workspace use; no other operator or runner changes | **UNFILLED** |
| Attending operator, graphical console access and approved time window | **UNFILLED** |
| Command timeout; manual abort/unknown-state inspection procedure | **UNFILLED** |
| Separate exact-owned discard consent, if/when required | **NOT GRANTED** |
| Explicit launch decision after review | **NOT GRANTED** |

Stop if required evidence is missing or any host value differs. The script does
not repair settings, weaken ownership checks or infer safe retry from a failed
receipt. Actual Hyper-V firmware/path representations still need observation;
passing static tests does not establish those APIs behave as assumed.

## Narrow action scope for a later explicit approval

- Start the **pinned exact-owned OFF preparation VM once**, for attended Ubuntu
  installation only. No host feature/network/permission change is authorized.
- Retain the installer's one-time disk-modification confirmation. Verify the
  ID-bound seed and sole new disk before consenting; do not add `autoinstall`,
  `console=ttyS0`, a login/password, SSH or a switch as an improvised workaround.
- At the fixed late-command wait, inspect the mounted `/target` using the live
  installer shell. Release its marker only after actual review; record sanitized
  findings. Observe requested power-off, rather than assuming it happened.
- On an uncertain result, inspect the exact GUID/manifest/claims/guard. No
  automatic retry, force-off, unregister or disk deletion is authorized by the
  launch decision. Retirement needs separate discard consent and can corrupt
  the retained disk; a launch-unknown state additionally needs explicit review.

The PowerShell command timeout does NOT bound the running VM lifetime. This is
not an unattended installation supervisor. A crashed launcher can leave a guard
and a running VM; investigate manually before any separately approved recovery.

**Excluded:** automatic installed-guest first boot, media/boot-order changes,
serial pipe configuration, image hygiene/freeze, filesystem deletion, runtime
VM reconciliation, repository transfer, model calls, background jobs and Gate A
acceptance. These require later reviewed steps and observed real evidence.

See the [candidate preparation runbook](night_shift_image_preparation_runbook.md).
No fields above are completed and no approval is granted by this coding step.
