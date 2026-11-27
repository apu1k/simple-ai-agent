# Gate B1: preview a multi-source workspace

B1 prepares a manifest on the PC. It reads and hashes the selected bytes but does **not** copy them to a disk, start a VM, fetch from the Internet, call a model, or require administrator rights. See [the Gate B plan](night_shift_plan.md#gate-b-design-revised) for the later VM steps.

## Write a profile

The profile is operator-owned configuration, not model input. Store it outside the folders it selects and do not commit private machine paths or previews to Git. For example:

```json
{
  "version": 1,
  "sources": [
    {
      "name": "code",
      "kind": "git",
      "path": "C:/work/project",
      "access": "writable",
      "revision": "HEAD",
      "upstream": "refs/remotes/origin/main",
      "exclude": ["examples/large-fixtures/**"]
    },
    {
      "name": "measurements",
      "kind": "folder",
      "path": "D:/data/measurements",
      "access": "read-only",
      "include": ["session-01/**"]
    },
    {
      "name": "local-notes",
      "kind": "folder",
      "path": "D:/projects/local-notes",
      "access": "writable"
    }
  ]
}
```

- Each `name` becomes `/workspace/<name>` in the later VM stages. Names are unique, using lowercase ASCII letters, digits, `_` or `-`. Access defaults to `read-only`; `writable` refers to a future guest copy, not your original.
- `git` reads the committed tree, never your working changes or Git history. `revision` defaults to `HEAD`; use a full commit ID to pin a particular revision. Unless you explicitly replace `upstream` with `"allow_unpublished": true`, the revision must be reachable from the specified **local remote-tracking branch**. For a checkout with local commits ahead of the remote, pin the last published commit rather than `HEAD`.
- The remote-tracking branch is cached evidence, not a live check of GitHub. Fetch from a trusted upstream **before** the preview if current remote state matters. A remote can be private, or a reference stale or manually changed. Git tracking/publication does not prove the absence of secrets. Only use ordinary local checkouts and a trusted Git executable, configuration, and object store. Linked worktrees and bare repositories are not supported in B1. Git LFS provides the committed pointer file only; no LFS download takes place.
- `folder` reads the selected files as they exist now: binaries, uncommitted files and empty directories are fine. There are **no silent name-based exclusions**. For example, a plain folder that contains `.git` includes that directory by default, including any history/config it contains. Use a `git` source for committed-only content or exclude `.git/**` explicitly.
- Patterns are optional, slash-separated, relative and case-sensitive. `*` and `?` match within a single component, and `**` matches zero or more components. `**/*.csv` matches CSVs at any depth, including the source root; `private/**` excludes the directory and its descendants. Exclusions win. Parents of selected entries are kept. A pruned directory counts as one excluded entry, not a count of everything underneath it.
- Unsafe entries fail the preview rather than silently disappearing. Selected symlinks, junctions, other reparse points, hard-linked files, Git submodules and paths that would collide on Windows are not imported. Exclude an unwanted link explicitly. Windows paths must use a local drive. Files are hashed in chunks, with a default total budget of 64 GiB (`max_bytes`, up to 1 TiB) and a 200,000 visited-entry limit; these are preview bounds, not a live VM capacity claim. Keep source directories stable while previewing; this is a scan, not a filesystem point-in-time snapshot.

## Review before approving

From the repo root, using the project's Python environment:

```powershell
python -m night_shifts.gate_b_preview D:/NightShift/workspace.json --summary
python -m night_shifts.gate_b_preview D:/NightShift/workspace.json > D:/NightShift/workspace-preview.json
```

The summary shows the exact Git revision and cached upstream tip, file and byte counts, selection effects, and warnings for names that look sensitive. Warnings do not remove files and are not a secret scanner. The full JSON adds relative paths, sizes and SHA-256 for each regular file. It has two digests: `manifest_sha256` hashes the portable manifest, and `preview_sha256` binds that manifest digest to the host-only source settings and summary. They are hashes of compact sorted-key JSON with ASCII escaping; the latter omits both the `preview_sha256` and `manifest` fields.

Review the full preview locally. A digest is **not** approval by itself; B1 has no VM-start path. The disk-building step must take operator approval for the exact preview and verify the bytes actually staged against it before the VM can start. If a source changes, build and approve a new preview; do not silently substitute new content. Only the portable manifest is intended for the guest, not the host paths or profile. The originals will not be written back by Gate B.
