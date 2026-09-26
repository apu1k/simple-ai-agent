# Restricted night-shift worker runtime

The repository contains a fail-closed guest-worker prototype; it does **not** enable untrusted real work. The current host-managed model-loop direction supersedes the old guest-to-host inference transport next step: see [`night_shift_plan.md`](night_shift_plan.md) and [`night_shift_status.md`](night_shift_status.md). This document describes existing contracts and historical guest-loop behavior, not instructions to deploy a live worker.

## Implemented

- Explicit command policies for `coding-worker`, `read-only-worker`, and `review-worker`.
- Structured argv execution without a shell, with fixed workspace, sanitized default environment, timeout, process-group termination, and bounded combined output.
- Trusted repository registry keyed by opaque repository ID.
- One detached, origin-free workspace per job, pinned to a resolved commit and created without hardlinks.
- A read-only workspace manifest binding the job ID, repository ID, requested revision, and resolved commit.
- A version-1 `/dev/ttyS0` guest loop that accepts one task, validates workspace identity, emits bounded events, and returns one bounded result.
- Bounded guest artifact staging and host-side validation/copying into trusted artifact storage.
- Independent `SandboxProvider`, `WorkerChannel`, `WorkspaceProvider`, `WorkspaceInjector`, and `ArtifactRetriever` contracts.
- Lifecycle-only Hyper-V sandbox management, with serial communication selected separately at the trusted composition root.
- Stable-ID trusted component selection with no dynamic imports, task-selected classes, host paths, or credentials.
- A small `WorkerToolProvider` contract separating model adapters from command and artifact implementations.
- Profile-scoped guest tool allowlists and a concrete adapter for policy-approved commands, bounded text artifacts, and proposed bounded guest-only repository tools (Commit 05; verify after approval).
- Fail-safe backend ordering for workspace injection and artifact retrieval.
- Default-off networking remains enforced by `SandboxSpec` and the Hyper-V controller.

## Command boundary

Worker commands are argv vectors, never shell strings. The initial policy permits only narrow read/check operations such as selected `git` inspection commands, `pytest`, `ruff check`, `mypy`, and `python -m compileall`. Git publishing, remotes, credentials, orchestration, host management, arbitrary Python scripts, shell interpreters, absolute targets, and parent traversal are denied.

This allowlist is defense in depth, not the complete sandbox. The reviewed Linux image must still enforce user identity, read-only system paths, workspace mount policy, cgroups, process limits, lifetime, and default-off networking.

## Guest-safe model tool boundary

Worker executors now receive only a `WorkerToolProvider`; they no longer receive the raw command runner or artifact writer. The provider publishes bounded JSON-style tool schemas and accepts structured calls. Its concrete guest adapter independently checks the assigned profile, validates argument shapes, routes command requests through `approve_worker_command`, and routes artifact requests through `ArtifactWriter`.

The proposed guest tool set is deliberately small:

- `list_files`, `read_file` and `search_text` are available to all profiles: portable text paths only, no links or special files; bounded recursion, reads, search results and response frames. Unsupported files fail explicitly.
- `apply_patch` is available only to coding workers: one exact unique span replacement guarded by SHA-256, or exclusive text-file creation. It does not accept a unified diff or delete files; independently exported patch generation is later work. External concurrent guest writers are not supported by this stale-content guard.
- `run_command` is available only to coding and review workers and remains restricted to the existing shell-free command policy. Review is **not** filesystem read-only: its test commands may write caches or execute repository code inside the guest. The read-only profile has no command or repository-write tool.
- `write_artifact` is available to all worker profiles but writes only to the separate bounded artifact staging directory, not the repository.

Guest tool names are intentionally distinct from the head runtime's host-side tools. Linux dirfd/no-follow operations are required for the repository facade on a real guest; its Windows fallback serves offline tests only and must never be used as VM isolation. The model receives no host tool implementation or registry. The guest service must be root-owned with a root-owned parent, unprivileged repository subprocesses, writable workspace/artifact paths only, disabled networking and cgroup-enforced process lifetimes. The current runtime and test fixtures are not that deployed service; do not enable live work on these tests.

## Host-neutral executor and historical guest import

`night_shifts.executor.MediatedModelExecutor` is the location-neutral model loop; the old `night_shifts.guest.executor` import is retained as a compatibility re-export. The loop accepts an injected inference client and `WorkerToolProvider`, not host filesystem or head-agent tools. Its prompt says that inference runs on the trusted host and repository tools operate inside the sandbox. The legacy guest CLI still defaults to `UnavailableWorkerExecutor`; moving the import does not create a deployed VM tool service.

A nonempty final response now yields `submitted`, **not** verified success. A final response beginning with `BLOCKED: ` yields a self-reported `blocked` outcome. Empty/oversized summaries and malformed tool requests fail closed. Tool failures are returned to the model and counted; neither a model claim nor a tool transcript marks configured checks as passed. `WorkerResult` carries independent check (`not_run` by default), review (`not_reviewed`), and cleanup (`unknown`) statuses. Legacy `success` outcomes and old frames without status fields still decode; historical backends may continue to return `success`. The service maps submissions to the existing `completed` lifecycle state (which does **not** mean approved), and blocked outcomes to `failed` with a separate outcome in the event. There is no automatic acceptance-criteria oracle or review-ready gate yet.

## Historical guest-mediated inference boundary (deferred)

The existing modular layer uses provider-neutral `InferenceRequest` and `InferenceResponse` records. A `TrustedInferenceGateway` runs on the trusted host and creates short-lived clients bound to one job, worker profile, administrator-selected stable model ID, request budget, payload limits, and expiry. Worker requests cannot select a provider, model, endpoint, or credential.

`LLMInferenceModel` owns the existing provider client on the host and requires native tool support. The former guest-loop prototype can still run with an injected `WorkerInferenceClient` for compatibility; the new MVP direction runs the same loop on the trusted host with a sandbox-backed tool provider. The gateway independently checks job/profile identity, exact profile tool schemas, transcript shape, tool-call authorization, request count, and input/output limits. Model-requested tools are still executed only by `GuestWorkerTools`, so inference mediation does not grant filesystem, shell, publication, or orchestration authority.

The semantic boundary and local bound-client adapter are implemented and tested independently of delivery. The earlier proposal to carry guest-to-host inference requests through a new transport is **deferred**, not a prerequisite for the current MVP. Instead, adapt the loop to the trusted host with only a sandbox-backed `WorkerToolProvider`; no provider credential or regular host tool belongs in the VM. The command-line guest continues to select `UnavailableWorkerExecutor` by default.

## Commit 07 offline budget and usage groundwork (not a live-worker guarantee)

`WorkerExecutionPolicy.snapshot` copies approved, value-only repository, revision, image digest, provider/model IDs, profile, model settings, sandbox and persisted budget. `JobBudget` adds bounded request, input/output bytes, generation tokens and command limits; older SQLite budget JSON loads defaults. The policy derives executor/gateway limits; **no backend yet passes this policy through a real VM job**. `ExecutionControl` observes monotonic deadlines between operations. `ProcessInferenceModel` starts a fresh, bounded host child per job, preserves that job's Responses conversation across requests, and kills/reaps the child on cancel/deadline. It is not a VM tool process. `ApprovedModelFactory` binds only a trusted provider profile to the frozen job settings; direct OpenAI is required for Flex/reasoning. Worker-only SDK settings disable automatic/empty-response retries, bound generation, and propagate the remaining monotonic time to both initial and continuation calls; ordinary head-agent clients remain unchanged. The fake sandbox tool session accepts a per-job command timeout and exposes close/cancel, but **there is still no reviewed real named-pipe adapter or verified guest process/VM teardown**. The host loop attempts tool/inference cleanup independently after callbacks fail and leaves VM cleanup `unknown` until a backend verifies removal. No daemon thread is used to claim that a stalled call stopped.

Provider-neutral inference usage records total input/output tokens and optional cached input/reasoning output subsets (not additive), or explicit unknowns. Host OpenAI clients expose usage from the last SDK response; absent usage, failed calls and possible provider-side billing after a killed call cannot be inferred as zero. Reporting usage is **not** hard spending enforcement. A strict USD budget is rejected before dispatch until administrator-approved pricing and conservative pre-call reservation exist. Worker-only SDK retries are disabled, but upstream billing can still be delayed or duplicated. `require_live_guarantees()` refuses dispatch unless a trusted backend attests both killable host inference and an interruptible sandbox transport; there is no such composed real backend today. These offline tests do not pass Gate A/B or enable live jobs.

## Modular execution boundary

`SandboxWorkerBackend` composes independently approved lifecycle, channel, workspace, and artifact implementations. `HyperVSandboxController` owns VM lifecycle only; `HyperVSerialTransport` owns JSONL framing and guest communication. The removed combined `SandboxController` and `_LegacyControllerChannel` are no longer compatibility paths.

Optional components must be configured in complete pairs: workspace provider plus injector, and artifact retriever plus collector. Trusted composition resolves preconstructed implementations by bounded stable IDs. Worker task/model text cannot select Python classes, imports, host paths, or credentials.

Execution prepares a trusted workspace, creates the sandbox, injects the workspace while the sandbox is stopped, and then starts the worker. Cleanup closes the worker channel, retrieves and validates referenced artifacts, destroys the sandbox, and finally removes host-side workspace staging. Failures are accumulated without skipping later cleanup steps.

## Workspace image contract

The guest expects a root-owned workspace root containing:

```text
/workspace/
├── workspace.json     root-owned, not group/world writable
├── repository/        isolated detached checkout
└── artifacts/         bounded worker artifact staging
```

`workspace.json` binds the serial task to its job and repository. The runtime rejects mismatched identities, writable/unowned manifests on Linux, repository symlinks, malformed frames, unknown profiles, and oversized output.

## Artifact boundary

Workers may stage only a small number of bounded UTF-8 text artifacts with safe names and approved kinds. Result messages contain relative `guest-artifact/<name>` references only. The orchestrator collector revalidates references and source files, rejects symlinks and traversal, enforces independent byte/count limits, calculates SHA-256, copies with exclusive creation into trusted host storage, and persists artifact metadata.

The backend now invokes an `ArtifactRetriever` after channel close and before sandbox destruction, then passes its temporary staging area to the existing collector. No Hyper-V-specific retriever exists yet, so real VMs still fail closed rather than mounting or extracting guest artifacts.

## Fail-closed status and remaining work

The command-line guest runtime intentionally uses `UnavailableWorkerExecutor`. Therefore a real coding/review task returns a structured failure unless the mediated executor and a reviewed transport are injected. For the current MVP, first validate lifecycle on a real host, then implement a bounded host-to-guest **tool** session, reviewed guest repository tools, safe workspace/result transfer, OS confinement, host-managed execution and independently collected patch/check evidence. A reviewed, digest-pinned Linux VHDX and operator approval are required for real-host work. The old guest inference transport remains deferred; keep the historical code and tests working. Publishing, branch pushes, and pull requests remain out of scope and require a separate approval-gated design.
