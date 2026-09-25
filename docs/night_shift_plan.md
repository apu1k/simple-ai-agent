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
3. **Commits 03–04 / Gate B:** bounded tool session and safe workspace/result transfer, including real-host boot/inject/fixed check/retrieve/destroy and failure cleanup. No live model tasks until Gates A and B have real evidence.
4. **Commits 05–08:** practical guest tools, host-neutral executor and honest submission semantics, unified budgets/cancellation, independently collected durable review bundles and patch validation in another disposable workspace.
5. **Commit 09 / Gate C:** one approved live-model fixture task with replayable patch, checks, usage, and verified cleanup; failures and cancellation included. Never use the main project as the first task.
6. **Commits 10–12 / Gate D:** one separately supervised sequential runner, narrow head tools, small evaluation set, restart recovery and operator runbook. No unscoped cleanup against another live runner.

Before any real VM, model call, image build/download, elevation, host reconfiguration, or paid evaluation: obtain explicit operator authorization. If Hyper-V is unavailable, report a blocker; do not fall back to an unisolated local worker. Report test type (mock, real VM, live model), image identity, cleanup evidence, and unresolved risks separately at each gate.
