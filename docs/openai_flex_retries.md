# OpenAI Flex capacity retries — timing, diagnostics and server waits

## Visible wait notices — applied; offline verification passed

The operator applied the visible-notice batch. Its standard applied-source
checks pass as recorded below; no runtime correction was needed. The earlier
93-case run verified only the five-minute budget before notices were added.
The current Flex suite passes 111 cases, including 18 new notice regressions.
These mocked tests do not establish live capacity availability.

The operator requested visible feedback before a retry wait. The applied
batch adds a context-local request-progress listener around the agent's
initial requests and Responses tool-output continuations. Immediately before
each authorized extra sleep, the wrapper emits a numeric/fixed-text notice:

```text
Flex capacity unavailable — waiting 5 minutes (300 seconds) before retry 1/5; staying on Flex.
```

Shorter actual delays are shown too. Textual schedules the notice onto its UI
thread and displays it as a System message in the chat view while the worker
waits. It is display-only, not an assistant answer, provider input, persisted
final-turn content, tool result, or privileged-operation progress. It does not
require debug logs. No notice announces a wait the retry policy has rejected;
there is no extra notice for the SDK's own initial internal retries.

The listener is scoped to a synchronous agent request and restored on success
or error, including after model switches without mutating shared client state.
Unrelated threads have no listener. Display callback failures do not change
the request outcome or cause duplicate requests. Notices contain the chosen
wait and attempt count, not raw headers, prompts, credentials or error bodies.
The existing terminal diagnostic remains available if all allowed retries fail.

The five-minute extra-sleep budget, server minimums, worker opt-out and no-tier-
fallback behavior are unchanged by this notice batch. Total wall-clock request
time can still exceed five minutes. The source and regressions have passed
post-application checks and are ready for an intentional operator-controlled
reload. No automatic reload, live capacity request, service/network change,
elevation, commit or Gate A operation is part of this batch.

### Applied notice verification

All pytest runs used `python -B -W error -m pytest -q`, with `-rs` and
`-p no:cacheprovider`, against the applied checkout without source substitution:

| Selection | Result |
|---|---|
| `tests/llm/test_openai_flex.py` | **111 passed** in 24.43 seconds |
| Remaining `tests/llm`, excluding that file | **54 passed** in 12.79 seconds |
| `tests/core` | **65 passed** in 0.15 seconds |
| `tests/adapters/textual/test_model_settings.py` | **8 passed** in 4.49 seconds |

Total: **238 passes**. The new headless UI case also passed alone in 0.72
seconds; that duplicate run is not added to the total. Mocked sleeps verify
notification delivery before waiting, exact 300-second boundary recovery,
terminal refusal without a second five-minute wait, both OpenAI APIs and
Responses continuations, scoped listener restoration/thread isolation, broken
callbacks, fixed-text formatting, and ineligible requests with no false notice.
The headless Textual worker test confirms visible feedback while processing,
responsive input and separation from privileged progress, without a real wait
or API call.

Repository `ruff check .` and `git diff --check` pass. Warning-as-error in-memory
compilation and Python 3.12 grammar parsing pass for the six changed/new Python
files in the notice batch. This is not an executed Python 3.12 compatibility
run. No new Mypy or broad runtime-suite result is claimed; the two previously
recorded baseline runtime failures remain outside this verification.

With repeated 300-second server guidance, the five-minute budget permits
**one extra retry**, not two: initial SDK dispatch, notice, 300-second extra
sleep, extra dispatch, then stop if another positive wait would be required.
Exactly consuming the sleep budget does not block that final dispatch or its
success. The initial SDK dispatch may itself contain SDK-managed retries,
which are excluded from `extra_retries`. Request time remains additional.

## Latest live finding — five-minute extra-wait budget

After loading the longer-wait policy, the operator supplied:

```text
Request retry diagnostic: Flex capacity; extra_retries=2/5; extra_backoff=600.0s; elapsed=611.5s; stop=extra_backoff_budget_exhausted; requested_tier=flex; server_min_wait=300s
```

The extra retries now work: two 300-second sleeps consumed the previous
600-second extra-wait budget. The remaining 11.5 seconds were measured inside
the request wrapper but outside its extra sleeps. Five extra retries is a
ceiling, not a promise; every refusal can supply a new server minimum. These
waits are capacity guidance, not time spent generating a successful answer.
Waiting longer does not reserve or guarantee Flex capacity.

The operator requested less waiting. The applied correction reduces
`FLEX_MAX_EXTRA_BACKOFF_SECONDS` from **600 to 300 seconds** per wrapper
invocation. The per-server-wait cap stays 300 seconds, ordinary backoff stays
at most 60 seconds, and the retry-count ceiling stays five. With repeated
300-second guidance, this permits one extra dispatch after one five-minute
wait, then stops if refused again. It does not shorten server minimums to
squeeze in more retries. Shorter guidance can allow more dispatches.

This is a **five-minute extra-sleep budget, not an end-to-end deadline**:
request/processing time and the initial SDK's own retries/sleeps are additional.
The existing 900-second per-request Flex timeout is unchanged. A hard overall
five-minute deadline would require a separate request-budget/cancellation
change and is not claimed here. There is still no automatic paid-tier fallback;
workers, non-Flex requests and other error types keep their existing behavior.

The applied five-minute policy initially passed the 93-case offline Flex
suite. Its regressions cover updated real-SDK mock counts, terminal budget
exhaustion, successful responses at exactly 300 seconds of extra sleep on both
APIs, and refusal to truncate a later server minimum to fit the remaining
budget. The notice feature is now also applied and verified as recorded above.
No live capacity call or automatic reload is part of this work. Historical
results below apply to the earlier policies, not the newer notice change.

## Previous live finding and ten-minute correction — offline verification passed

The operator reloaded the application and reported this live terminal diagnostic:

```text
Request retry diagnostic: Flex capacity; extra_retries=0/5; extra_backoff=0.0s; elapsed=6.5s; stop=server_retry_after_exceeds_60s; requested_tier=flex
```

This establishes that the diagnostic code was loaded for that request and that
our 60-second server-wait limit stopped extra retries before any extra sleep.
It does not reveal the exact Retry-After value, nor count the SDK's internal
retries. The measured wrapper elapsed time is 6.5 seconds; the operator's
perceived UI timing is not the same measurement. This is a policy limitation,
not evidence that the retry loop or reload failed.

The applied correction separates three limits:

- Ordinary exponential/jittered backoff: unchanged, at most **60 seconds**.
- Valid server-requested minimum: honor in full up to **300 seconds** per wait.
- Extra sleep across this wrapper invocation: at most **600 seconds**, still
  with at most **five** extra dispatches. A wait that would exceed the remaining
  budget is refused, never truncated to retry earlier than the server asks.

The 600 seconds excludes SDK-internal sleeps, request duration and processing;
it is not a total deadline. A success after exactly consuming that extra-wait
budget is accepted. An explicit `x-should-retry: false` still stops immediately.
Workers and non-Flex requests still receive no extra retries. Quota, other
rate-limit, authentication and timeout errors remain outside this policy.
There is no automatic standard-tier fallback.

Terminal diagnostics gain `server_min_wait`: a normalized positive finite
number of seconds (three significant digits), or `none` if no usable minimum
was parsed. No raw header/body text is added. New stop labels are
`server_retry_after_exceeds_300s` and `extra_backoff_budget_exhausted`; the old
`server_retry_after_exceeds_60s` belongs to the prior policy below.

The operator applied all three proposals. **The corrected source passes the
standard offline checks below and is ready for an intentional app reload.**
No further runtime correction was needed after application. The application
has not been reloaded as part of verification; the earlier reload loaded only
the diagnostic-only code, not this wait-policy correction.

### Post-application verification of the wait-policy correction

All pytest selections used `python -B -W error -m pytest -q`, with `-rs` and
`-p no:cacheprovider`. These are ordinary applied-source runs, not temporary
source substitutions or live model requests:

| Selection | Result |
|---|---|
| `tests/llm/test_openai_flex.py` | **83 passed** in 19.25 seconds |
| Remaining `tests/llm`, excluding that file | **54 passed** in 12.78 seconds |
| `tests/core` | **65 passed** in 0.14 seconds |

The total is **202 passes**, including the 83 Flex cases; those are not added
twice. The Flex suite increased from 54 to 83 cases. Mocked sleeps and HTTP
mock transport cover long-wait recovery, header formats and boundaries,
cumulative extra-wait exhaustion, later minimums, unchanged exclusions,
terminal diagnostics and nonmultiplying SDK retries on both APIs.

Repository `ruff check .` and `git diff --check` pass. Strict warning-as-error
in-memory compilation and Python 3.12 grammar parsing pass for
`llm/openai_flex.py`, `tests/llm/test_openai_flex.py`, `llm/base.py` and
`core/agent.py`; this is not an executed Python 3.12 compatibility run. No new
Mypy or broad runtime-suite run is claimed. The earlier two baseline runtime
failures recorded below remain unfixed and were not rerun in this verification.

No paid/API capacity request, automatic reload, service/network change,
elevation, commit or Gate A operation occurred. Passing mocks establish the
policy behavior, not live capacity availability. Server waits above 300 seconds
or explicit no-retry instructions can still cause immediate terminal errors.

## Original investigated behavior — before the applied correction

The head-agent Flex retry implementation remains present in
`llm/openai_flex.py`. Both Chat Completions and Responses initial requests use
it, as do Responses tool-output continuations. Direct OpenAI HTTPS requests
must explicitly opt into `service_tier=flex` to receive the extra retry budget.
Budget-controlled workers intentionally opt out; ordinary non-Flex, quota,
rate-limit, authentication and timeout failures do not gain extra retries.
There is no automatic fallback to standard processing.

After the initial SDK dispatch (which retains its normal SDK retry policy),
there are at most five extra capacity retries. Additional dispatches disable
SDK retries to avoid multiplying loops. Nominal extra waits are **5, 10, 20,
40 and 60 seconds**, with jitter and a 60-second per-wait cap. With no server
minimum, exhausting the entire sequence adds roughly **108–150 seconds** of
backoff, nominally 135, plus request/initial-SDK time. This is NOT a guaranteed
minimum elapsed time, a total deadline or a guarantee that all retries occur.
The Flex request timeout of 900 seconds does not force an immediate 429 to wait.

The policy deliberately stops early when:

- `x-should-retry: false` is present on a capacity refusal; or
- valid Retry-After guidance asks for more than the 60-second per-wait bound.
  The implementation does not silently retry earlier than the server asks.

These headers are considered on every refusal, not just the first one. A server
minimum within the cap can lengthen the nominal schedule (for example, five
60-second minimum waits). It does not silently extend the permitted per-wait
maximum.

## Evidence from this investigation

Before the diagnostic changes, the standard existing suite passed **41 tests**:

```text
python -B -W error -m pytest -q tests/llm/test_openai_flex.py -rs
```

Installed SDK in the tool's Python environment: **OpenAI 2.32.0**. Its status
error constructor unwraps the nested `error` object into `RateLimitError.code`
and `.type`, so the supplied normal JSON error shape is recognized by current
source. This inspection is not evidence of a live request's actual headers or
of the code loaded inside another already-running Python process.

Three synthetic reproductions against the existing, unchanged implementation,
with fake requests/sleeps and no network, confirm:

| Synthetic response sequence | Calls | Extra waits before terminal error |
|---|---:|---:|
| First refusal says no retry | 1 | None |
| First refusal asks for 120 seconds | 1 | None |
| Two ordinary capacity refusals, then a 120-second instruction | 3 | 5 + 10 = 15 seconds |

Thus the reported 15–30-second failures were possible under the original policy,
even though a normal exhausted backoff sequence is much longer. At that point
the specific cause was not established: saved terminal errors identified Flex
capacity but did not retain the relevant headers, retry counts or elapsed
request timing. The newly supplied live diagnostic now confirms the over-60s
early-stop condition for that request, as recorded above. The inspected Textual log files contain
no matching retry evidence; absence there does not establish that no retries
ran. No broad/debug request logging or provider-secret inspection was enabled.

## Applied diagnostic-only correction — offline verification complete

The applied source batch leaves eligibility, delay bounds, retry counts,
server no-retry instructions, worker budgets and service tier unchanged. It:

- Adds a bounded exception note on a recognized terminal Flex capacity refusal.
  The original SDK error type, identity, body and string are retained; callers
  that catch RateLimitError still can. No timeout/ambiguous request is retried.
- Records `extra_retries`, accumulated `extra_backoff`, monotonic `elapsed`,
  a fixed `stop` label and whether Flex was explicitly requested. Extra counts
  exclude the SDK's internal first-dispatch retries; elapsed includes time in
  that dispatch. Accumulated backoff is not the complete request duration.
- Emits that same note in the agent's final error, including tool continuations.
  It no longer relies on the Python logger being visible in the Textual UI.
  Only a bounded, single-line runtime-prefixed note is surfaced; unrelated,
  oversized and multiline exception notes are not copied into chat.
- Logs the new note using only numeric measurements and fixed labels, never
  prompts, tool outputs, credentials, raw headers or provider payload text.
  This restriction concerns the new diagnostic, not a replacement for the
  pre-existing provider error message shown by the agent.

Example of a synthetic early stop (not a captured live result):

```text
Request retry diagnostic: Flex capacity; extra_retries=2/5; extra_backoff=15.0s; elapsed=21.0s; stop=server_retry_after_exceeds_60s; requested_tier=flex
```

Stop labels distinguish `server_x_should_retry_false`,
`server_retry_after_exceeds_60s`, `retry_budget_exhausted`,
`flex_not_explicitly_requested` and `extra_retries_disabled`. The last two help
identify routing/eligibility problems rather than guessing that backoff failed.
Non-capacity errors get no Flex note. A future fast capacity error with no note
would require checking whether the diagnostic batch is actually loaded and the
request reaches this wrapper before drawing a conclusion about retry policy.

The new regressions cover terminal reasons/counts/timing, the exact 15-second
synthetic sequence, preserved original exceptions, non-capacity exclusions,
private-note filtering, both APIs and the agent's Responses tool continuation.
The applied standard Flex suite passes **54 tests in 12.76 seconds**, including
all **13 new diagnostic cases** and the earlier 41 tests. There is no transient
hook or source substitution in these applied checks. There is no paid/API
capacity test in this source work.

### Broader applied verification and explicit limitations

All commands use the ordinary tool environment, without reloading the served
application. Warnings are errors in the applied pytest runs:

| Applied command selection | Result |
|---|---|
| `tests/llm/test_openai_flex.py` | **54 passed** |
| Remaining `tests/llm`, excluding that file | **54 passed** |
| `tests/core` | **65 passed** |
| `tests/runtime` | **233 passed, 2 failed, 5 skipped** |

The first combined LLM/core/runtime command hit the shell tool's **30-second
limit** and supplied no final verdict; it is not counted as passed. The smaller
standard runs above provide the actual results. LLM plus core total **173
passes**; this includes the 54 Flex cases rather than adding them again.

Both runtime failures are the two parameterizations of
`test_tool_failure_is_not_refunded_or_leaked` in `test_privileged_turn.py`: their
mock collection callback is called zero times rather than once. A separate
baseline-only comparison loaded the three original HEAD modules (`llm/base.py`,
`llm/openai_flex.py`, `core/agent.py`) in memory, without modifying the checkout,
and reproduced the same **two failures**. That comparison emitted one pytest
plugin-already-imported warning; it is baseline evidence, not a replacement for
the normal applied runs. These failures predate the Flex diagnostic change and
remain unfixed; the broad runtime suite is **not green**. No privileged tests,
policies, permission gates or installed code were relaxed to make them pass.
The five skips are retained native-fixture entry points and unavailable ordinary-
user test symlinks, not successful privileged execution.

Repository Ruff and `git diff --check` pass. Mypy passes the existing
`night_shifts` selection across **84 source files**; this is not a claim of a
new strict whole-repository typing run. All four changed Python files pass
warning-as-error in-memory compilation and Python 3.12 grammar parsing. This
is syntax validation, not an executed Python 3.12 compatibility test.

An initial overbroad whole-file whitespace assertion stopped on legacy trailing
spaces in `llm/base.py`. A corrected baseline-aware check confirms the existing
13 such lines there and five in `core/agent.py` are inherited from HEAD, not
introduced by this batch. Compilation was then run for all four files, new-doc
whitespace passes, and the normal added-line `git diff --check` passes. No
unrelated whitespace cleanup was proposed.

That diagnostic-only source was verified for diagnosis, not as a capacity fix.
The operator subsequently reloaded the app and supplied the live finding
recorded at the top. The original diagnostic verification did not validate
the wait-policy correction; its separate post-application results are above.

## Applying and following up safely

The ten-minute policy was applied, verified offline and subsequently reloaded
by the operator; the latest live diagnostic above is evidence that it ran.
Its historical tests used mocked sleeps and HTTP mock transport, not paid/API
capacity calls. The five-minute budget and visible-notice feature are now both
applied and verified by the 238-pass selection above. Earlier 83/202-pass
results and the 93-case budget-only check are historical, not the notice result.

The operator can now intentionally reload the Python/Textual app using the
normal reconnect procedure to load the verified notices and five-minute budget. A browser reconnect may retain the old process. No automatic
runtime, Tailscale, Caddy, authentication-service or host restart is authorized
during this remote session. No elevation, dependency installation, commit or
Windows reboot is required for source/test verification.

Continue normal requests after the verified change is loaded. A minimum above
300 seconds will still stop without sleeping; its normalized value will be in
the diagnostic rather than silently capped. An explicit no-retry instruction
still stops, and exhausted retry/sleep budgets can still expose real capacity
unavailability. Longer waits do not guarantee capacity. No need to force a
paid failing request solely to test this change.

Gate A/handoff work is paused for this side task. Its uncommitted files and
existing pending validation updates are separate and are not superseded here.
No live model call, service/network change, elevation, VM operation or commit
occurred as part of this investigation.
