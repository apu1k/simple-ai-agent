# Night shift: host-managed sandbox worker MVP

This is the current implementation direction. The existing guest-mediated model loop and whole-task serial protocol are retained as historical foundations, not the next production execution path. See [status and validation gates](night_shift_status.md), [Hyper-V lifecycle](night_shift_hyperv.md), and [existing restricted runtime](night_shift_worker_runtime.md).

## One useful result first

Submit one bounded coding task for an administrator-approved repository and immutable base revision. A single, host-managed worker model session gets **only** a job-bound `WorkerToolProvider` backed by tools inside a disposable, network-off Hyper-V Linux VM. The orchestrator exports an approved revision, retrieves a bounded patch/check evidence/summary, destroys the sandbox, and leaves the user's checkout untouched. A durable sequential queue and head-agent management tools follow only after one real result works.

No regular `create_agent(profile="coding-worker")` runtime/tool registry: those profiles provide host tools, not filesystem isolation. Never run repository tests, hooks, dependency installation, checkout filters, or repository-supplied helpers on the host. Keep model credentials and provider clients on the trusted host; the guest receives neither. No automatic patch application, push, PR, publishing, arbitrary repositories, networking, parallel agents, or interactive mailbox workflow.

## Smallest compatible implementation seams

- Keep `NightShiftService`, `WorkerBackend.run`, job models/state machine, SQLite stores, and Hyper-V lifecycle. `run_local` is synchronous; `JobStore.update` is not transactional claiming. Add ownership, migrations, cancellation and distinct execution/check/review/cleanup statuses before enabling a durable runner. A worker's final summary is a submission, not verified success.
- Extract/adapt `guest.executor.MediatedModelExecutor` into a location-neutral host loop with injected per-job `WorkerInferenceClient` and `WorkerToolProvider`; retain the guest import for compatibility if practical. `InferenceRequest/Response` and `TrustedInferenceGateway` already validate identities, schemas and payloads. Unify `ModelExecutorLimits`, `InferenceLimits`, and `JobBudget`, then implement real deadline, usage/cost, provider retry and cancellable-I/O policy. The current nonempty final response maps directly to `WorkerOutcome.SUCCESS`; this must not imply task verification.
- Keep `SandboxProvider` for VM lifecycle. Add a separate sandbox-backed `WorkerToolProvider` and narrow bounded host-to-guest session for tools plus orchestrator-only transfer/finalization. Reuse framing/pipe code from `HyperVSerialTransport`, but preserve the old `WorkerChannel` whole-task contract and `SandboxWorkerBackend`; that JSONL protocol is not a per-tool RPC. Extend the trusted stable-ID `TrustedExecutionRegistry` for the new backend rather than allowing model text to choose code, paths or credentials.
- Reuse `RepositoryRegistry`, `WorkspaceProvider/Injector`, `ArtifactRetriever/Collector`, and `GuestWorkerTools` where they fit. Current `WorkspacePreparer` performs a host Git clone and checkout and has no reviewed export/secret policy: it is **not** an approved way to transfer arbitrary repositories or prove no repository code executes on the host. Review Git config, hooks, filters, submodules, LFS, binary/link and tracked-secret behavior; export only approved data without executing repository-controlled helpers on the host. No host mounts or raw host-path tool calls.
- Implement bounded workspace-scoped guest read/search/edit/check tools under OS confinement. `pytest` permits arbitrary repository code in the guest; command allowlists alone do not establish isolation. Collect patches and check evidence independently of model-supplied artifact references. Treat guest results as untrusted and record cleanup status separately.

## Incremental gates (not interchangeable)

1. **Commit 01:** this architecture and an observed baseline; docs only.
2. **Commit 02 / Gate A:** document and validate the existing opt-in Hyper-V lifecycle/protocol-test image on an operator-approved real host. Mocked tests are not Gate A.
3. **Gate B (revised, see below):** multi-source workspace snapshot on a per-run data disk, result retrieval, real-host boot/inject/fixed check/retrieve/destroy and failure cleanup. No live model tasks until Gates A and B have real evidence. The earlier Commit 03–04 serial-only fixture transfer (64 text files, ~2 MB) remains as offline groundwork, not the target design.
4. **Commits 05–08:** practical guest tools, host-neutral executor and honest submission semantics, unified budgets/cancellation, independently collected durable review bundles and patch validation in another disposable workspace.
5. **Commit 09 / Gate C:** one approved live-model fixture task with replayable patch, checks, usage, and verified cleanup; failures and cancellation included. Never use the main project as the first task.
6. **Commits 10–12 / Gate D:** one separately supervised sequential runner, narrow head tools, small evaluation set, restart recovery and operator runbook. No unscoped cleanup against another live runner.

## Gate B design (revised)

Goal: give the offline VM a workspace built from several sources, from a few MB up to many GB (code, measurement data, later 3D/computer-use material). The PC prepares everything; the VM never gets network access.

**Workspace profile** (defined per run): a list of sources, each mounted at `/workspace/<name>`:
- `git`: a local checkout (GitHub repos are fetched/cloned on the PC beforehand, never from the VM). Only the files of one exact **committed** tree are exported from Git objects; no working tree, no uncommitted changes, no history, no hooks/filters run on the PC. Default: the commit must already be on the upstream remote (i.e. published); allowing unpushed commits is an explicit option. The VM gets a fresh Git repo of that tree so a patch can be produced.
- `folder`: a normal folder on the PC, copied as-is (also for unpushed projects or extra files).
- Per source: `read-only` or `writable`, and optional include/exclude patterns. **No default exclusions.**

**Preview and approval:** before each run the PC builds a preview (sources, file counts, sizes, include/exclude effects, symlinks/junctions refused, warnings for files that look like secrets: warn only, never auto-exclude). The operator approves it once; the full path-to-SHA-256 manifest is stored with the run.

**Transport:** large data does not go over COM1. Per run the PC creates a **data disk** (VHDX) with the snapshot and manifest and attaches it read-only; an empty **output disk** is attached writable. COM1 carries only control messages and the short result. The VM stays network-off; no host folder is shared or mounted into the VM.

**Results:** patch against the start commit for writable `git` sources; changed/new/deleted files compared to the manifest for writable `folder` sources; size-limited and validated on the PC, stored in the run folder. **Never written back to the original folders automatically.** Reading the guest-written output disk on the PC is a parsing risk and must be reviewed in B4.

**Image change:** the guest needs a small service that mounts the data disk at `/workspace` (read-only source, copied to a writable work area where allowed) and the output disk at `/output`. That requires a new cleaned image and a Gate A rerun with it.

| Step | Content | Check |
|---|---|---|
| B1 | Profile + snapshot builder + preview/manifest on the PC (no VM); see the [B1 preview guide](night_shift_gate_b_preview.md) | Unit tests; real preview reviewed by operator |
| B2 | [Approved input staging](night_shift_gate_b_disks.md), then data/output disk creation and attach; guest mount service; new image | Staging checks, disk-only round trip, then Gate A rerun with new image |
| B3 | Guest prepares workspace, fixed check recomputes all SHA-256 against manifest | Live run, manifest matches in VM |
| B4 | Result retrieval (patch / changed files), limits, host validation | Live run with a deliberate change in the VM |
| B5 | Full Gate B through the scheduled task, including a mid-run failure | Results correct, VM and disks gone, originals unchanged |

Out of scope for Gate B: GPU/3D, GUI/computer use, writing results back, network access in the VM.

Before any real VM, model call, image build/download, elevation, host reconfiguration, or paid evaluation: obtain explicit operator authorization. If Hyper-V is unavailable, report a blocker; do not fall back to an unisolated local worker. Report test type (mock, real VM, live model), image identity, cleanup evidence, and unresolved risks separately at each gate.
