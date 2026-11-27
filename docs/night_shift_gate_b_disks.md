# Gate B2: approved input staging and VM disks

## B2.1: stage a reviewed workspace on the host

Use the [B1 guide](night_shift_gate_b_preview.md) to create a profile and save a **full** preview. Read the file list and warnings, then copy `preview_sha256` from the exact preview you intend to approve. From the project environment:

```powershell
python -m night_shifts.gate_b_stage D:/NightShift/workspace.json D:/NightShift/workspace-preview.json D:/NightShift/staging/example-input --approve-preview-sha256 <reviewed-preview-sha256>
```

Replace the angle-bracket placeholder with the digest. Use an existing, operator-controlled parent, outside every source, and a **new** destination directory. The command does not mount a disk, boot a VM, access a network, or execute source files. The digest binds the reviewed contents and settings; it is not authentication from an arbitrary caller. This command is for the operator, not a tool available to a worker/model or an elevated service.

The command refuses a changed profile, altered preview, changed Git revision/upstream tip, or changed selection/bytes. It streams approved files into `workspace/<name>` and reads them back to check the exact paths and hashes. It writes only the portable `manifest.json` into the staging directory, not the preview or absolute host paths. `sealed.json` records the two digests and is written last. Existing destinations are never overwritten; a failure attempts to remove only the fresh staging directory and reports if it could not. Use a trusted work directory and don't expose it to a guest or another writer during staging. An interruption can leave an unsealed directory; do not use or resume it. Staging contains the actual input data: review who can read that directory and clean it up when no longer needed.

The seal records verification at staging time. It is not proof that files have not changed since then or that the backing disk was flushed and detached. B2.1 proves no VM isolation or large-disk throughput by itself.

## B2.2: build and attach the disks (next)

- Keep the passing Gate A image untouched. Use a fresh run-owned input VHDX and a separately bounded output VHDX. Candidate input filesystem: **exFAT**, to fill from Windows and mount read-only in Ubuntu. Verify the exact guest kernel's exFAT support and test portable names, binary data and disk size before committing to it. Unix executable bits come from the manifest, not the transport filesystem.
- Separate privileged disk setup/teardown from copying. Format only the new, blank VHDX positively identified by its backing file and attachment; fail closed on ambiguous mapping. Do not accept a raw physical disk number from the caller. Stage directly onto the mounted input volume to avoid an extra full-size copy. Dismount and record the exact sealed VHDX hash outside the disk. Check identity, capacity/free-space bounds, and ownership again before attachment.
- Do not assume Hyper-V has a read-only switch for an ordinary virtual hard disk. The planned fallback is an immutable input VHDX parent with a run-owned differencing child attached at a fixed SCSI slot, and `ro,nodev,nosuid,noexec` on the guest input mount. Never merge the child back. The disposable VM cannot change the approved parent through that child, even if the child is writable at the virtual hardware layer.
- The guest must distinguish system, input and output devices by their expected attachment identity, not by enumeration order. Refuse missing or ambiguous disks; never format an unidentified device. Do not mount a guest-written output disk on the Windows host in B2. Review the output extraction boundary in B4.
- Live acceptance requires separately approved disk/image/VM operations. First do a small disk-only round trip, including one failed stage with verified dismount. Then use a **new** guest image and rerun Gate A, including cleanup. Verification includes absence of run-owned VM/disk attachments afterwards and the unchanged original image hash. COM1 carries control only.
