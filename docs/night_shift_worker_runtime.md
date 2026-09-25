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
- Profile-scoped guest tool allowlists and a concrete adapter for policy-approved commands and bounded text artifacts.
- Fail-safe backend ordering for workspace injection and artifact retrieval.
- Default-off networking remains enforced by `SandboxSpec` and the Hyper-V controller.

## Command boundary

Worker commands are argv vectors, never shell strings. The initial policy permits only narrow read/check operations such as selected `git` inspection commands, `pytest`, `ruff check`, `mypy`, and `python -m compileall`. Git publishing, remotes, credentials, orchestration, host management, arbitrary Python scripts, shell interpreters, absolute targets, and parent traversal are denied.

This allowlist is defense in depth, not the complete sandbox. The reviewed Linux image must still enforce user identity, read-only system paths, workspace mount policy, cgroups, process limits, lifetime, and default-off networking.

## Guest-safe model tool boundary

Worker executors now receive only a `WorkerToolProvider`; they no longer receive the raw command runner or artifact writer. The provider publishes bounded JSON-style tool schemas and accepts structured calls. Its concrete guest adapter independently checks the assigned profile, validates argument shapes, routes command requests through `approve_worker_command`, and routes artifact requests through `ArtifactWriter`.

The initial guest tool set is deliberately small:

- `run_command` is available only to coding and review workers and remains restricted to the existing shell-free command policy.
- `write_artifact` is available to all worker profiles but writes only to the separate bounded artifact staging directory, not the repository.

Guest tool names are intentionally distinct from the head runtime's host-side tools. Tests explicitly align equivalent command access by profile, but no host tool implementation or registry is passed into a VM. Repository read/edit tools remain a future reviewed adapter slice; a model executor must not bypass this boundary with direct filesystem objects.

## Historical guest-mediated inference boundary (deferred)

The existing modular layer uses provider-neutral `InferenceRequest` and `InferenceResponse` records. A `TrustedInferenceGateway` runs on the trusted host and creates short-lived clients bound to one job, worker profile, administrator-selected stable model ID, request budget, payload limits, and expiry. Worker requests cannot select a provider, model, endpoint, or credential.

`LLMInferenceModel` owns the existing provider client on the host and requires native tool support. The current `MediatedModelExecutor` prototype runs the bounded tool loop in the guest through a pre-authenticated `WorkerInferenceClient`. The gateway independently checks job/profile identity, exact profile tool schemas, transcript shape, tool-call authorization, request count, and input/output limits. Model-requested tools are still executed only by `GuestWorkerTools`, so inference mediation does not grant filesystem, shell, publication, or orchestration authority.

The semantic boundary and local bound-client adapter are implemented and tested independently of delivery. The earlier proposal to carry guest-to-host inference requests through a new transport is **deferred**, not a prerequisite for the current MVP. Instead, adapt the loop to the trusted host with only a sandbox-backed `WorkerToolProvider`; no provider credential or regular host tool belongs in the VM. The command-line guest continues to select `UnavailableWorkerExecutor` by default.

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
