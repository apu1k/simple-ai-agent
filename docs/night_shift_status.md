# Night-shift implementation status and validation gates

## Commit 01 observed baseline

- Checkout HEAD when inspected: `6ea7f75` (`feat(settings): add max OpenAI reasoning effort`); prior commits `3a04eb0`, `ad9b864`. `git status --short` returned no changes. The handoff's previously modified `config/knowledge.yaml` and `tools/knowledge/config.py` were clean when checked; do not bundle unrelated future changes.
- `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py`: **109 passed, 1 skipped** (non-real-host tests only; one skip inside selected tests).
- `python -m ruff check .`: **All checks passed!**
- `python -m mypy night_shifts`: **Success: no issues found in 37 source files**.
- `git diff --check`: exit 0, no output on the initial clean tree.
- No real VM, real-host validation, image inspection, model call, host reconfiguration, or paid inference was run. These results do **not** establish isolation or an end-to-end coding result.

## What exists versus what is blocked

| Gate | State | Evidence needed / operator action |
| --- | --- | --- |
| A: real lifecycle | **BLOCKED — not run** | Operator-approved dedicated Windows Hyper-V host/permissions, reviewed provenance and SHA-256 of network-off protocol-test Linux VHDX with serial bootstrap, storage/resource settings and pipe access review. Run only opt-in real-host tests after review; capture VM/differencing-disk cleanup and sanitized results. The existing test includes fixed protocol exchange, timeout/cancel and exact-ID orphan cleanup; disconnect/failure cleanup and actual resource-limit guarantees still require verification. |
| B: real transfer | **BLOCKED — not implemented** | Safe revision export/guest injection/retrieval adapters, bounded negative tests, then operator-approved real VM boot/inject/check/retrieve/destroy and failed-retrieval cleanup. No arbitrary checkout transfer or live model work. |
| C: first model result | **BLOCKED by A/B** | Approved model/settings and paid-call consent; reproduce a fixture patch in a separate disposable workspace, report checks, usage and cleanup. |
| D: unattended queue | **BLOCKED by C** | Durable claiming, supervised runner, multi-job/restart evaluation with retained review bundles and owner-safe reconciliation. |

Existing code provides a Hyper-V lifecycle controller and whole-task COM1 JSONL transport, a guest tool prototype, host-side inference gateway and synchronous service. It does **not** provide a host-managed sandbox tool session, safe Hyper-V workspace transfer, real guest artifact retrieval, an independently generated review patch, hard USD cost enforcement, or a durable runner. `MediatedModelExecutor` still lives in `guest/` and considers a nonempty final summary success. The guest CLI defaults to `UnavailableWorkerExecutor`.

## Known safety and reliability checks for later work

- `WorkspacePreparer` invokes host Git `clone`/`checkout`; before reuse for untrusted repos, review Git config/filter/hook execution and approved snapshot export; tracked secrets and unsupported submodules/LFS/binary/link content require explicit policy.
- The whole-task backend streams guest events on a daemon thread, and synchronous provisioning, inference, transfer, callback and retrieval calls are not uniformly interrupted by a job deadline. Some cleanup event/callback failures can interrupt later cleanup; isolate failures and persist unresolved resources.
- `JobBudget` contains timeout/tool calls/optional USD, but the executor and gateway enforce separate request/turn limits; no trusted pricing/usage reservation currently establishes a strict cost ceiling. Treat absent or unknown usage as unknown, not zero.
- `HyperVSerialTransport` derives a pipe name from the sandbox ID and bounds individual JSONL frames, but named-pipe ACL/creator identity and job/session binding for a new tool protocol need review; a hostile guest can send arbitrary bytes. No general host networking from guest management channels.
- Existing `SandboxWorkerBackend` collects only worker-referenced artifacts; collecting a deterministic patch, validation checks and cleanup state independently of the model is not yet wired. Its existing `WorkerOutcome.SUCCESS` and `NightShiftService` completed state are not evidence of semantic task completion.
- Real-host `test_hyperv_real_host.py` is opt-in. Its exact-ID orphan reconciliation is appropriate for a dedicated test sandbox; do not run unscoped `reconcile()` alongside another runner. Record ownership and limits at the next gate, not inferred guarantees.

Next step: Commit 02 offline preflight/test hardening. **Stop for operator approval and reviewed image/host configuration before launching a real VM.** Keep this file updated with commands/results, image identity and cleanup status whenever a gate is attempted.
