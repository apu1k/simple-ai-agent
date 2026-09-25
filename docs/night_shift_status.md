# Night-shift implementation status and validation gates

## Commit 01 observed baseline

- Checkout HEAD when inspected: `6ea7f75` (`feat(settings): add max OpenAI reasoning effort`); prior commits `3a04eb0`, `ad9b864`. `git status --short` returned no changes. The handoff's previously modified `config/knowledge.yaml` and `tools/knowledge/config.py` were clean when checked; do not bundle unrelated future changes.
- `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py`: **109 passed, 1 skipped** (non-real-host tests only; one skip inside selected tests).
- `python -m ruff check .`: **All checks passed!**
- `python -m mypy night_shifts`: **Success: no issues found in 37 source files**.
- `git diff --check`: exit 0, no output on the initial clean tree.
- No real VM, real-host validation, image inspection, model call, host reconfiguration, or paid inference was run. These results do **not** establish isolation or an end-to-end coding result.

## Commit 02 offline preparation

The [Gate A preflight and resource-enforcement matrix](night_shift_hyperv_preflight.md) records what must be reviewed and observed on an approved real host. The opt-in suite is extended to check rejected-objective failure, deliberate disconnect after the guest sleep event, host-observed VM absence, differencing-disk removal, and exact-ID reconciliation. No VM/image has been launched or inspected as part of this preparation. The test file remains opt-in; local/fake tests do not complete Gate A. Post-edit offline checks: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **109 passed, 1 skipped**; `python -c "import os, pytest; os.environ.pop('NIGHT_SHIFT_HYPERV_INTEGRATION', None); raise SystemExit(pytest.main(['-q', 'tests/night_shifts']))"` — **109 passed, 2 skipped** (the opt-in module was skipped); `python -m ruff check .` — **All checks passed!**; `python -m mypy night_shifts` — **Success: no issues found in 37 source files**; `git diff --check` — exit 0. The opt-in file was AST-parsed, not exercised against Hyper-V. Record any real-host outcomes in a later status update; do not replace **BLOCKED** with PASS without operator-authorized evidence.

## Commit 03 offline contract (locally validated; real gates blocked)

The [tool-session protocol contract](night_shift_tool_session.md) and fake-transport tests define a host-managed, job/sandbox/session-bound model tool facade separate from the old whole-task channel. There is no real serial tool adapter or guest responder yet. Do not infer VM confinement or real transport timeout behavior from fake-transport tests. Post-edit checks: `python -m pytest -q tests/night_shifts --ignore=tests/night_shifts/test_hyperv_real_host.py` — **138 passed, 1 skipped**; `python -m ruff check .` — **All checks passed!**; `python -m mypy night_shifts` — **Success: no issues found in 38 source files**; `git diff --check` — exit 0. These are offline tests only; Gates A and B remain **BLOCKED**.

## Commit 04 offline implementation (proposed; validation pending approval)

The [fixture snapshot transfer design and limits](night_shift_snapshot_transfer.md) describe an exact, approved-Git-object snapshot, fake-serial guest load/fixed check/report and exact-sandbox cleanup attempt. These are **not** a deployed guest image, safe real serial adapter, real-host demonstration, or durable artifact bundle. Proposed files have not been applied or tested yet; record observed post-approval commands/results here before treating offline work as validated. Gate A and Gate B remain **BLOCKED** pending authorized real-host evidence.

## What exists versus what is blocked

| Gate | State | Evidence needed / operator action |
| --- | --- | --- |
| A: real lifecycle | **BLOCKED — not run** | Operator-approved dedicated Windows Hyper-V host/permissions, reviewed provenance and SHA-256 of network-off protocol-test Linux VHDX with serial bootstrap, storage/resource settings and pipe access review. Run only opt-in real-host tests after review; capture VM/differencing-disk cleanup and sanitized results. The existing test includes fixed protocol exchange, timeout/cancel and exact-ID orphan cleanup; disconnect/failure cleanup and actual resource-limit guarantees still require verification. |
| B: real transfer | **BLOCKED — no real data-path evidence** | Proposed offline fixture transfer and fake transport require approval/testing. Then review/deploy the guest image, implement an interruptible bounded serial adapter and run operator-approved real VM boot/inject/check/retrieve/destroy including failed-retrieval cleanup. No arbitrary checkout transfer or live model work. |
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

Next step: Gate A still requires operator approval and a reviewed image/host configuration. Commit 04 can begin with offline bounded workspace/result transfer; real transfer is Gate B and requires separate authorized real-host evidence. Do not enable live jobs while A/B are blocked. Keep this file updated with commands/results, image identity and cleanup status whenever a gate is attempted.
