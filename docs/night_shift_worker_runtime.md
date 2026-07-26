# Restricted night-shift worker runtime

Phase 4 is in progress. The repository now contains the fail-closed worker-runtime foundation; it does **not** yet enable untrusted real work.

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
- Fail-safe backend ordering for workspace injection and artifact retrieval.
- Default-off networking remains enforced by `SandboxSpec` and the Hyper-V controller.

## Command boundary

Worker commands are argv vectors, never shell strings. The initial policy permits only narrow read/check operations such as selected `git` inspection commands, `pytest`, `ruff check`, `mypy`, and `python -m compileall`. Git publishing, remotes, credentials, orchestration, host management, arbitrary Python scripts, shell interpreters, absolute targets, and parent traversal are denied.

This allowlist is defense in depth, not the complete sandbox. The reviewed Linux image must still enforce user identity, read-only system paths, workspace mount policy, cgroups, process limits, lifetime, and default-off networking.

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

The command-line guest runtime intentionally uses `UnavailableWorkerExecutor`. Therefore a real coding/review task returns a structured failure unless a reviewed executor is injected. Remaining Phase 4 work includes:

1. Select and implement the model-inference boundary without placing publishing credentials in the VM. Prefer an orchestrator-mediated, narrowly authenticated inference channel.
2. Run the executor under profile-specific OS filesystem policy. In particular, read-only and review workers must not be able to modify the repository even if model/tool policy fails.
3. Install and harden the runtime in a reviewed, digest-pinned Linux VHDX.
4. Implement reviewed Hyper-V `WorkspaceInjector` and `ArtifactRetriever` adapters for the existing backend boundaries.
5. Define guest-safe worker tool contracts and reconcile them with the existing profile allowlists.
6. Add an opt-in harmless real-host repository task after Phase 3 host validation succeeds.

Publishing, branch pushes, and pull requests remain out of scope until Phase 5 and must continue to require approval.
