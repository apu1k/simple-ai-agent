# Gate B2: approved input staging and VM disks

## B2.1: stage a reviewed workspace on the host

Use the [B1 guide](night_shift_gate_b_preview.md) to create a profile and save a **full** preview. Read the file list and warnings, then copy `preview_sha256` from the exact preview you intend to approve. From the project environment:

```powershell
python -m night_shifts.gate_b_stage D:/NightShift/workspace.json D:/NightShift/workspace-preview.json D:/NightShift/staging/example-input --approve-preview-sha256 <reviewed-preview-sha256>
```

Replace the angle-bracket placeholder with the digest. Use an existing, operator-controlled parent, outside every source, and a **new** destination directory. The command does not mount a disk, boot a VM, access a network, or execute source files. The digest binds the reviewed contents and settings; it is not authentication from an arbitrary caller. This command is for the operator, not a tool available to a worker/model or an elevated service.

The command refuses a changed profile, altered preview, changed Git revision/upstream tip, or changed selection/bytes. It streams approved files into `workspace/<name>` and reads them back to check the exact paths and hashes. It writes only the portable `manifest.json` into the staging directory, not the preview or absolute host paths. `sealed.json` records the two digests and is written last. Existing destinations are never overwritten; a failure attempts to remove only the fresh staging directory and reports if it could not. Use a trusted work directory and don't expose it to a guest or another writer during staging. An interruption can leave an unsealed directory; do not use or resume it. Staging contains the actual input data: review who can read that directory and clean it up when no longer needed.

The seal records verification at staging time. It is not proof that files have not changed since then or that the backing disk was flushed and detached. B2.1 proves no VM isolation or large-disk throughput by itself.

## B2.2: disk-only test, then VM attachment

The attended Windows test uses `scripts/gate_b_disk_smoke.ps1`, with `Open` and `Close` as separate explicit Administrator operations. It is **not** a worker action, automation endpoint, or general disk utility. It can only create a new 256 MiB dynamic VHDX under a unique protected `AiAgentGateB-DiskSmoke-<run-id>` directory in Program Files. It takes neither a disk number nor a path. `Open` uses two independent Windows lookups to cross-check the VHDX-to-disk mapping and initializes only an explicitly verified blank file-backed disk. `Close` validates the creation receipt and the VHDX identity, detaches by exact path, and checks `Get-VHD` again before hashing the detached VHDX. It does not delete the evidence. Nothing is attached to a VM.

1. Prepare a synthetic local folder with a binary file (include an empty directory and a non-ASCII filename). Save its full B1 preview and review the file list and digest while no disk is attached. Generate an independent 32-hex-character run ID for each trial.
2. Approve `Open` for the first ID. If successful, verify that the drive letter still resolves to the reported `volume_path` (for example, with `GetVolumeNameForVolumeMountPointW`) before writing to it. Create a fresh parent directory on that volume, then run B2.1 as the normal user with the reviewed digest and a new child destination there. Verify the seal, the files and their hashes. Approve `Close` for the same run ID and verify the drive was removed and the script reported a detached VHDX hash.
3. Repeat with a fresh disk and run ID, changing one byte in the synthetic source **after** the preview. Require staging to refuse it and leave no staged directory or seal. Approve `Close` even after the expected staging failure, and verify that disk detached as well.
4. No private data, guest-written disk, or existing VM/image is used. The exFAT volume has no per-file access controls; do not treat this scratch drive as private storage. If any elevated operation is interrupted or reports an unknown outcome, stop and inspect attachments before asking for any separately approved recovery. A timeout is not proof of detachment. Retain both test artifacts until reviewed; deletion is separate.

### Live progress (2026-11-27)

- First `Open` stopped before creating a disk: this host uses the versioned `Hyper-V/2.0.0.0` module directory. Module discovery was corrected and checked in native Windows PowerShell with a restricted module path.
- Next `Open` (`cc883ad3944e47fc85a18d124bf5036d`) created the new exFAT VHDX and reported `E:`. The unelevated check matched `E:` to the exact volume GUID. Staging stopped before copying any payload: on this exFAT volume, `GetFileInformationByHandleEx(FileAttributeTagInfo)` returned WinError 87; a diagnostic on the same directory handle confirmed `FileBasicInfo` works instead.
- `Close` reported the VHDX detached with SHA-256 `835ca97b9051b348ce003963fe27cd2daff0398d004473c7ded0518cf7fed6c7`. An independent check found both the temporary drive letter and the volume GUID path gone. The backing file is retained under Program Files; no VM or Gate A image was touched.

**Windows disk-only acceptance passed** after switching the no-follow handle query to `FileBasicInfo`. In both trials the unelevated process checked the drive-letter-to-volume-GUID mapping before writing, and after `Close` the Windows drive list returned to its baseline and the exact volume path was gone. No real workspace data, VM or Gate A image was used.

| Trial | Result | Scratch run ID | Detached VHDX SHA-256 |
| --- | --- | --- | --- |
| Approved copy | Two files (1,048,606 bytes, including `mésure.bin`) and an empty directory staged and independently read back; manifest and seal matched. | `cfe9afae2e1049f48390c06bd59bf359` | `59305686dac94a6080c917ad3f8356f5806b27f304153b4b01f16a1e8bd2f345` |
| Same-size one-byte change | Staging exited 2 with `file bytes changed after review`; no partial directory or seal remained. | `5d59b771934b43b9b92c90cf32744839` | `92650b59aec47d3aa6c42b018ebb9bf70ccb565939b5aa67b09cbe2e529d2b5f` |

The backing files are retained in the corresponding `AiAgentGateB-DiskSmoke-<run-id>` directories under Program Files. The approved-copy disk contains its manifest and synthetic fixture and can be considered for a separately reviewed read-only guest smoke test. These trials do not prove guest compatibility, large-workspace performance or the result-disk path.

### Remaining disk and guest design

- Keep the passing Gate A image untouched. Use a fresh run-owned input VHDX and a separately bounded output VHDX. Candidate input filesystem: **exFAT**, to fill from Windows and mount read-only in Ubuntu. Verify the exact guest kernel's exFAT support and test portable names, binary data and disk size before committing to it. Unix executable bits come from the manifest, not the transport filesystem.
- Separate privileged disk setup/teardown from copying. Format only the new, blank VHDX positively identified by its backing file and attachment; fail closed on ambiguous mapping. Do not accept a raw physical disk number from the caller. Stage directly onto the mounted input volume to avoid an extra full-size copy. Dismount and record the exact sealed VHDX hash outside the disk. Check identity, capacity/free-space bounds, and ownership again before attachment.
- Do not assume Hyper-V has a read-only switch for an ordinary virtual hard disk. The planned fallback is an immutable input VHDX parent with a run-owned differencing child attached at a fixed SCSI slot, and `ro,nodev,nosuid,noexec` on the guest input mount. Never merge the child back. The disposable VM cannot change the approved parent through that child, even if the child is writable at the virtual hardware layer.
- The guest must distinguish system, input and output devices by their expected attachment identity, not by enumeration order. Refuse missing or ambiguous disks; never format an unidentified device. Do not mount a guest-written output disk on the Windows host in B2. Review the output extraction boundary in B4.
- Live acceptance requires separately approved disk/image/VM operations. First do a small disk-only round trip, including one failed stage with verified dismount. Then use a **new** guest image and rerun Gate A, including cleanup. Verification includes absence of run-owned VM/disk attachments afterwards and the unchanged original image hash. COM1 carries control only.
