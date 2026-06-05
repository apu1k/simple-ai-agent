# Developer Reference

Technical outline for contributors working on isolated parts of the codebase.

This file focuses on architecture boundaries, ownership, and extension points. The goal is to keep the project easy to work on in a modular way: you should be able to change one subsystem without understanding the entire repository.

The architecture is deliberately split into narrow layers so that tools, protocol parsing, runtime wiring, frontends, editing, and LLM integrations can evolve mostly independently.

```text
main.py / main_textual.py
        ↓
runtime/*
        ↓
core/agent.py
   ├─ core/protocol.py
   ├─ core/tool_registry.py
   ├─ llm/*
   ├─ tools/*
   └─ editing/*
        ↓
adapters/*
```

---

## 1. Purpose of this document

This document is the contributor-facing map of the codebase.

Its main purpose is to explain how the repository is split into small, mostly independent subsystems so that work can happen locally inside one area without requiring a full understanding of the rest of the project. In other words, this document exists to reduce the amount of code a contributor needs to read before making a safe change.

This is not meant to be a user guide. The `README.md` explains what the app does and how to run it. This file explains how the code is organized, which module owns which responsibility, and which boundaries should not be crossed.

In particular, this reference should help a contributor answer questions like:

- Where does a new tool belong?
- Which layer is allowed to talk to the filesystem directly?
- Where should provider-specific LLM code live?
- Which modules are safe to change without touching UI code?
- How do the CLI and Textual frontends stay separate from the agent core?
- Where should new behavior be added so the architecture stays clean?

The intended workflow is:

1. identify the subsystem you want to change,
2. read only the sections relevant to that subsystem,
3. follow the dependency rules in this document,
4. keep the change local unless there is a strong reason to widen the impact.

That modular workflow is an explicit design goal of this repository.

---

## 2. Architectural philosophy

The project is intentionally structured around narrow, composable layers instead of one large application module. The design goal is to isolate concerns, keep boundaries explicit, and make it possible to evolve one subsystem without forcing accidental coupling with the rest.

Several principles drive the codebase:

### 2.1 Separation of concerns

Each major package owns one kind of problem:

- `core/` owns agent behavior and protocol parsing.
- `tools/` owns tool implementations.
- `editing/` owns approval-based file mutation.
- `llm/` owns provider loading and client implementations.
- `adapters/` owns frontend-specific interaction and rendering.
- `runtime/` owns composition and wiring.
- `config/` owns environment and path setup.

A file should usually belong clearly to one of those concerns. If a change feels like it belongs to multiple layers at once, that is often a sign that the design should be reconsidered.

### 2.2 Composition over entanglement

The runtime layer wires the system together instead of letting every layer import every other layer freely. This is why `runtime/bootstrap.py`, `runtime/cli_loop.py`, and `runtime/textual_loop.py` are important: they act as composition roots.

The benefit is that core logic remains reusable. The same `Agent` can be used by the CLI frontend and the Textual frontend because the UI is injected through callbacks rather than hardcoded into the agent.

### 2.3 Frontends are adapters, not the application core

The CLI and Textual UIs are intentionally treated as outer layers. They present state, collect user input, and render output, but they should not become the place where core business logic accumulates.

This keeps the center of the system stable:

- the agent loop lives in `core/agent.py`
- the protocol lives in `core/protocol.py`
- tool registration lives in `core/tool_registry.py`
- runtime state lives in `runtime/state.py`

A frontend can change significantly without forcing large changes in the agent core.

### 2.4 Explicit boundaries beat convenience imports

A common source of long-term codebase decay is letting “just one small import” cross a boundary. This project tries to avoid that. Some modules are intentionally a bit more indirect because that indirection protects modularity.

Examples:

- Tools do not import frontend code.
- The agent does not directly render UI.
- Editing logic is not spread across tools and runtime; it is centralized in `editing/store.py`.
- Provider-specific code stays in `llm/`, not in `core/`.

This can look stricter than necessary for a small project, but it pays off as the project grows.

### 2.5 Local reasoning is a feature

A contributor should be able to work effectively with limited context.

Examples of intended local workflows:

- A tool author should mostly read `tools/_base.py`, the relevant `tools/fs/*` helpers if needed, and tests for similar tools.
- A protocol change should mostly involve `core/protocol.py`, `core/agent.py`, prompt wording, and protocol tests.
- A Textual UI change should mostly stay in `adapters/textual/app.py` and maybe `runtime/textual_loop.py`.
- A provider change should mostly stay in `llm/` and configuration docs.

If a small change forces you to understand the entire repository, the modular design is failing and should be improved.

### 2.6 Approval-based mutation is intentional

The project does not treat file writes as a casual side effect of tools. Instead, edits are proposed first and only applied after explicit approval. That design is central, not incidental.

This keeps mutation logic auditable and makes tool behavior safer and easier to reason about. It also means file-editing concerns belong primarily to the `editing/` package and edit-related tools should delegate to it instead of reinventing write behavior.

---

## 3. High-level architecture

At a high level, the system is organized as a layered local agent runtime.

A frontend collects user input, the runtime layer wires up the application, the agent core decides what to do next, the LLM produces either a final answer or tool calls, and tools interact with the local environment. Some tool actions only observe state, while file modifications are routed through the pending-edit system.

A simplified view looks like this:

```text
User
  ↓
Frontend (CLI or Textual)
  ↓
Runtime composition
  ↓
Agent core
  ├─ protocol parsing
  ├─ tool registry lookup
  ├─ runtime-context injection
  └─ LLM client call
       ↓
   Tool execution / provider APIs
       ↓
   Tool results / pending edits / display items
       ↓
Frontend rendering
```

### 3.1 Main layers

#### Config layer
The `config/` package provides low-level environment and path setup. It should stay simple and independent.

#### Core layer
The `core/` package contains the durable logic of the agent:
- parsing model responses,
- representing tool calls,
- executing tool calls through the registry,
- enforcing retry and batch limits.

This layer should remain free of UI-specific concerns.

#### Tool layer
The `tools/` package contains functions the agent can call. Tools are registered with metadata and discovered automatically. They are the boundary between model-directed actions and local capability.

#### Editing layer
The `editing/` package owns the lifecycle of proposed edits. It is the only place that should own the rules for pending changes, approval, rejection, stale-checking, and diff generation.

#### LLM layer
The `llm/` package owns provider configuration and concrete API clients. It isolates external model-provider behavior from the rest of the application.

#### Adapter layer
The `adapters/` package contains frontend-specific code. The CLI and Textual frontends both live here. They should depend on core concepts, but core concepts should not depend on them.

#### Runtime layer
The `runtime/` package is the composition layer. It is where the pieces are assembled into a working app. This layer is intentionally allowed to know about many other layers because its job is orchestration, not reusable domain logic.

### 3.2 Control flow in practice

A typical interaction works like this:

1. the frontend collects user input,
2. the runtime has already created state, an agent, and an LLM client,
3. the agent sends the conversation plus runtime context to the model,
4. the model returns either plain text or a raw JSON tool call,
5. the protocol parser validates that response,
6. if tools are requested, the agent executes them through the registry,
7. tool results are appended back into the conversation,
8. the loop continues until the model returns a final answer,
9. the frontend renders the final answer and any display items.

The crucial architectural point is that each step has a clear owner. Input handling belongs to the frontend, execution flow belongs to the runtime and agent, tool semantics belong to tools, and file mutation belongs to the editing layer.

### 3.3 Why this structure matters

This structure exists so that individual concerns can evolve independently.

For example:

- You can build a new frontend without rewriting the agent.
- You can add new tools without changing the protocol parser.
- You can add a new provider without changing CLI rendering.
- You can improve edit approval behavior without modifying the LLM clients.

---

## 4. Repository structure

This section describes the main directories and their responsibilities.

### 4.1 `config/`

Purpose:
- project-level paths
- `.env` loading
- locating provider configuration files

Current key file:
- `config/settings.py`

This package should not grow application logic. It exists to provide basic configuration primitives that the rest of the project can import safely.

### 4.2 `core/`

Purpose:
- core agent loop
- protocol parsing and validation
- tool registry and autodiscovery metadata
- message abstractions

Current important files:
- `core/agent.py`
- `core/protocol.py`
- `core/tool_registry.py`
- `core/messages.py`

This is the conceptual center of the system. It should stay stable, testable, and largely frontend-agnostic.

### 4.3 `editing/`

Purpose:
- represent proposed edits
- store pending edits
- apply or reject them
- generate diffs

Current important files:
- `editing/model.py`
- `editing/store.py`
- `editing/diff.py`

This package owns mutation workflow, not just helper functions. If something changes how proposed file writes work, this is the first place to look.

### 4.4 `llm/`

Purpose:
- define the client interface
- create concrete LLM clients
- load provider configuration
- support provider/model selection

Current important files:
- `llm/base.py`
- `llm/providers.py`
- `llm/openai_chat.py`
- `llm/openai_responses.py`

This package is where provider-specific complexity belongs. Other layers should not contain OpenAI-specific logic unless there is a very strong reason.

### 4.5 `tools/`

Purpose:
- define agent-callable local capabilities
- separate tool categories by function
- provide shared tool result and display abstractions

Current important files:
- `tools/_base.py`
- `tools/fs/read.py`
- `tools/fs/search.py`
- `tools/fs/edit.py`
- `tools/fs/analyze.py`
- `tools/fs/_shared.py`
- `tools/math/arithmetic.py`

Tools should stay focused and independent. A tool should do one thing well and return either a plain observation string or a `ToolResult` with display items.

### 4.6 `adapters/`

Purpose:
- frontend-specific input/output behavior
- rendering and user interaction
- adapter interfaces for swapping UI styles

Current important files:
- `adapters/base.py`
- `adapters/cli/*`
- `adapters/textual/app.py`

This package is intentionally “outside” the core. It should translate between the user experience and the reusable inner application logic.

### 4.7 `runtime/`

Purpose:
- initialize tools
- build state and clients
- create the agent
- host CLI and Textual composition roots
- build the system prompt

Current important files:
- `runtime/bootstrap.py`
- `runtime/cli_loop.py`
- `runtime/textual_loop.py`
- `runtime/prompt.py`
- `runtime/state.py`
- `runtime/loop.py`

This package is the main orchestration layer. It is allowed to depend broadly because that is exactly its role.

### 4.8 `tests/`

Purpose:
- verify subsystem behavior
- mirror major source areas
- keep architecture changes safe

Current structure includes tests for:
- core behavior
- editing behavior
- filesystem tools
- math tools

The test tree should generally mirror the source tree so contributors know where to place new tests.

### 4.9 Top-level entry points

Important top-level files:
- `main.py` — CLI startup entry point
- `main_textual.py` — Textual startup entry point
- `README.md` — project overview
- `DEVELOPER_REFERENCE.md` — contributor architecture reference

These files should stay thin. Most logic should live in packages, not in top-level scripts.

---

## 5. Dependency rules

The dependency rules are what preserve the modular architecture. If these boundaries erode, the codebase becomes harder to reason about and harder to change safely.

### 5.1 General rule

Dependencies should mostly point inward toward simpler, more reusable layers, while runtime and adapters sit at the edge and compose those layers.

In practice, that means:

- low-level configuration should not know about the app,
- core logic should not know about frontends,
- tools should not know about rendering,
- editing should not depend on UI or runtime,
- runtime is allowed to know about many parts because it assembles them.

### 5.2 Intended import direction

A simplified dependency model is:

```text
config/   → no project imports
core/     → no frontend/runtime/tool imports
editing/  → editing-local modules
llm/      → config/
tools/    → tools-local modules, editing/model.py, tools/_base.py
adapters/ → adapter-local modules, limited shared abstractions
runtime/  → may compose core, llm, tools, adapters, editing, config
main*.py  → entry points into runtime
```

This is a guideline, not a type system, but the closer the code stays to it, the healthier the architecture remains.

### 5.3 Why `core/` must stay isolated

`core/` contains the logic that should be reusable across frontends and runtime modes. If `core/` starts importing from `adapters/`, `runtime/`, or concrete tool modules, then the center of the system becomes tied to one execution environment.

That would make the codebase harder to test, harder to reuse, and harder to extend.

`core/` may define abstractions and call registry entries, but it should not become the place where frontend behavior or provider-specific integration leaks in.

### 5.4 Why `tools/` must stay UI-agnostic

A tool should express capability, not presentation policy.

That means:
- a tool may return a string observation,
- a tool may return a `ToolResult` with `display_items`,
- but it should not import CLI rendering or Textual widgets.

This separation allows the same tool to be used by multiple frontends without rewriting it.

### 5.5 Why `runtime/` is the composition root

`runtime/` is the one layer that is expected to know how pieces fit together. It creates the state, loads providers, initializes tools, builds the agent, and binds UI callbacks.

This broader visibility is intentional. Without a composition root, wiring code tends to leak across the entire repository.

### 5.6 Why `editing/` should remain centralized

Approval-based file mutation is a cross-cutting concern, so it is important that the rules for it stay in one package.

If tools, runtime code, and adapters all started implementing their own approval or write logic, behavior would diverge and subtle bugs would appear.

Centralizing edit lifecycle rules in `editing/` keeps the mutation model predictable.

### 5.7 Practical red flags

The following changes are usually signs that the architecture is drifting in the wrong direction:

- `core/` importing from `adapters/`
- `core/` importing from `runtime/`
- tools importing UI code directly
- frontend code reimplementing logic that should live in `core/` or `editing/`
- provider-specific code being added outside `llm/`
- direct file writes appearing in tools instead of going through the edit store
- top-level scripts gaining business logic that belongs in packages

### 5.8 Rule of thumb for contributors

Before adding an import, ask:

- Does this create a permanent architectural dependency or just solve a local convenience problem?
- Am I pulling presentation logic into a capability layer?
- Am I duplicating behavior that already has a clear owner elsewhere?
- Would this make it harder to replace the CLI, the Textual app, or the provider layer later?

If the answer is yes, the change probably belongs in a different layer.

---

## 6. Entry points and runtime modes

The project currently has two user-facing runtime modes:

- a classic CLI mode
- a Textual-based terminal UI mode

Both modes are built on the same underlying agent, tool system, runtime state, and provider infrastructure. That shared foundation is important: the frontends differ in interaction style, but they are not meant to fork the application into separate products.

### 6.1 `main.py`

`main.py` is the standard CLI entry point.

Its job is intentionally minimal. It imports `run_cli_agent` from `runtime.cli_loop` and starts the CLI application. The file should stay thin and should not accumulate initialization or business logic.

This is an architectural pattern used throughout the project: top-level entry scripts should only delegate into runtime code.

### 6.2 `main_textual.py`

`main_textual.py` is the Textual entry point.

It imports `create_textual_app()` from `runtime.textual_loop`, exposes the resulting `app`, and runs it when invoked as a script. It is also structured so that Textual can launch or serve the app directly.

Like `main.py`, this file should remain thin.

### 6.3 Why there are two entry points

The two entry points reflect two different frontend modes, not two different application architectures.

The system is intentionally arranged so that:
- CLI-specific interaction stays in CLI modules,
- Textual-specific interaction stays in Textual modules,
- shared state, tools, and agent logic remain below both of them.

That allows frontend evolution without forking the rest of the stack.

### 6.4 Runtime mode differences today

CLI mode currently:
- performs interactive provider selection,
- performs interactive model selection,
- exposes backslash commands through `adapters/cli/commands.py`,
- renders output through Rich panels and terminal helpers.

Textual mode currently:
- creates the app through `runtime/textual_loop.py`,
- selects the first configured provider and requires a configured `default_model`,
- exposes model selection and pending edits through in-app UI modes,
- runs agent work in a background thread to keep the UI responsive.

These are frontend differences, not differences in core semantics.

### 6.5 Where runtime mode logic should live

As a rule:

- startup orchestration belongs in `runtime/`
- rendering belongs in `adapters/`
- agent execution belongs in `core/`
- provider construction belongs in `llm/`

If a runtime mode needs custom behavior, that behavior should be added to its runtime/adapters boundary first, rather than pushing it into `core/`.

---

## 7. Shared bootstrap layer

The shared bootstrap layer lives in `runtime/bootstrap.py`.

Its role is to collect setup steps that both frontends need, while keeping those steps free of frontend-specific rendering or input behavior.

This module is important because it prevents duplication between CLI and Textual startup code.

### 7.1 What `runtime/bootstrap.py` currently owns

It provides shared helpers for:

- initializing tool autodiscovery
- building a `ModelConfig` and concrete LLM client from a selected provider/model
- creating the initial `AgentState`
- creating an `Agent` with optional callbacks

Those are all cross-frontend concerns, so they belong in a shared composition helper.

### 7.2 `initialize_tools()`

`initialize_tools()` calls `autodiscover("tools")`.

This imports all non-private modules under `tools/` so that `@tool` decorators execute and register their functions in the global registry.

This is an important startup boundary:
- tool definition happens in `tools/`
- tool registration metadata lives in `core/tool_registry.py`
- tool loading is triggered from `runtime/bootstrap.py`

That separation keeps tool modules independent while still giving the runtime a single place to initialize capabilities.

### 7.3 `build_model_config_and_client()`

This function converts a selected provider/model combination into two things:

- a `ModelConfig` object stored in runtime state
- a concrete LLM client returned by `llm.providers.create_llm_client()`

It also validates that the provider has an API key available and raises a helpful error otherwise.

This function is a good example of composition logic that should not leak into UI code. A frontend may trigger model selection, but the building of runtime model state belongs here.

### 7.4 `create_initial_state()`

This function creates the initial `AgentState` and currently sets:

- `cwd` to `Path.cwd()`
- `model_config` to the selected model configuration
- `edit_store` through the dataclass default factory in `runtime/state.py`

This is the correct level for creating default runtime state. It keeps state construction centralized and consistent across frontends.

### 7.5 `create_agent()`

This function creates the `Agent` and wires in callback hooks such as:

- `on_debug`
- `on_tool`
- `on_raw`
- `on_error`
- `on_display`

This matters architecturally because it keeps the `Agent` generic. The agent does not know whether output goes to the CLI, the Textual app, a future web UI, or tests. The bootstrap layer injects those behaviors from the outside.

### 7.6 Why the bootstrap layer matters

Without a shared bootstrap layer, both frontends would likely duplicate:
- tool initialization
- state creation
- agent construction
- provider/client wiring

That duplication would slowly create frontend-specific behavior where there should instead be one shared runtime policy.

---

## 8. Agent core

The agent core lives primarily in `core/agent.py`.

This file contains the loop that turns user input into either tool execution or a final answer. It is the operational center of the application.

The key architectural property of the `Agent` is that it owns control flow, but not presentation.

### 8.1 What the agent owns

The `Agent` is responsible for:

- storing conversation history
- injecting runtime context into model messages
- calling the LLM client
- parsing model responses through `core/protocol.py`
- executing tools through the registry
- collecting tool results back into the conversation
- retrying after invalid model responses
- enforcing per-step and batch limits

This is the right level of responsibility for the core execution engine.

### 8.2 What the agent does not own

The `Agent` does not own:

- provider selection UI
- terminal rendering
- Textual widgets
- direct filesystem implementation outside tool calls
- provider-specific API code
- direct file approval logic

Those concerns are intentionally delegated outward to tools, editing, adapters, and runtime composition.

### 8.3 Internal architecture of the agent

The main collaborators of `Agent` are:

- `self.llm` — the LLM client implementation
- `self.state` — runtime state such as cwd and model config
- `self.registry` — the tool registry
- callback hooks for debug/tool/raw/error/display output

This keeps the class compact in responsibility even though it coordinates several moving pieces.

### 8.4 Runtime context injection

The agent adds a runtime-context system message on each call via `_messages_with_context()`.

That context currently includes:
- current working directory
- selected provider
- selected model
- guidance such as using `pwd()` when the user asks for the current location

This is an important design choice: some state is not merely stored internally, but deliberately surfaced back to the model as execution context.

### 8.5 Step loop behavior

The public `step()` method processes one user message and continues until one of the following happens:

- the model returns a final answer
- the model repeatedly produces invalid responses and retry budget is exhausted
- step count exceeds the configured maximum

Current limits in `core/agent.py` are:
- `MAX_STEPS = 10`
- `MAX_RETRIES = 2`
- `MAX_BATCH_TOOL_CALLS = 5`
- `FAIL_FAST_BATCH = True`

These limits are important because they define operational safety boundaries around model behavior.

### 8.6 Tool execution boundary

The agent does not import specific tools directly. Instead, it resolves tools by name through the registry.

That means the agent knows:
- how to validate a requested tool exists,
- how to call registered functions,
- how to inject `state` when required,
- how to interpret `ToolResult` vs plain strings,

but it does not need hardcoded knowledge of `read_file`, `search_text`, `show_file`, or any other specific tool.

This is a major source of extensibility.

### 8.7 Callback-based output

The agent uses callback hooks for side-channel output:

- debug logging
- tool call logging
- raw model response logging
- error reporting
- display-item rendering

This pattern is what allows the same agent core to work with both CLI and Textual frontends. The core emits events; frontends decide how to present them.

### 8.8 Why the agent core should stay small in scope

It is tempting in projects like this to keep pushing behavior into the agent because it is “already in the middle.” That should be resisted.

The agent should remain the orchestrator of a turn, not the owner of every concern in the program. If new behavior belongs naturally to tools, editing, runtime composition, or adapters, it should live there.

---

## 9. Tool-call protocol

The tool-call protocol is defined by `core/protocol.py` and reinforced by the system prompt built in `runtime/prompt.py`.

Its job is to take raw model output and classify it as one of three things:

- a valid tool-call response
- a final answer
- an invalid response

### 9.1 Protocol goals

The protocol is intentionally strict. Its goals are:

- make model/tool interaction predictable,
- prevent prose from being confused with executable actions,
- keep parsing logic simple and testable,
- support both single and batch tool execution,
- remain provider-agnostic.

### 9.2 Response modes

The protocol recognizes two valid response styles from the model:

#### Tool call mode
The entire response must be one raw JSON object.

Valid root shapes are:
- single tool call: object with exactly `action` and `input`
- batch tool call: object with exactly `tool_calls`

#### Final answer mode
Any non-tool plain text response is treated as a final answer, unless it looks like a malformed or embedded tool call.

This distinction is critical to the whole system.

### 9.3 Single-tool and batch-tool structure

Single-call mode requires:
- an `action` string
- an `input` JSON object

Batch mode requires:
- a `tool_calls` array
- each item must itself be a valid single-tool-call object

The parser is intentionally strict about unsupported keys, missing keys, empty action names, and non-object inputs.

### 9.4 Embedded and malformed tool calls

The protocol explicitly rejects:
- tool-call JSON embedded inside explanatory text
- broken JSON that looks like an attempted tool call
- mixed root shapes combining `tool_calls` with `action` or `input`
- malformed arrays or malformed entries inside `tool_calls`

This is one of the most important implementation choices in the whole project. It prevents the model from mixing executable intent with narration in ways that would make the runtime ambiguous.

### 9.5 Parser limits vs runtime limits

One subtle but important implementation detail is that the parser and the agent enforce different limits.

In `core/protocol.py`:
- `MAX_TOOL_CALLS_PER_TURN = 10`

In `core/agent.py`:
- `MAX_BATCH_TOOL_CALLS = 5`

That means a model response may be syntactically valid at the protocol level but still be rejected by the agent for requesting too many tool calls in one executable batch.

This distinction is worth preserving in the documentation because it reflects layered responsibility:
- the protocol validates structure,
- the agent enforces runtime execution policy.

### 9.6 Why the protocol belongs in `core/`

The parser is not a frontend concern and not a provider concern. It is a core execution rule of the application.

Keeping it in `core/` ensures:
- consistent behavior across frontends,
- deterministic tests,
- a single place to change tool-call semantics,
- no duplication of parsing rules in CLI or Textual code.

---

## 10. Batch tool execution

Batch tool execution is implemented in the agent core, primarily through `_execute_tool_batch()` and `_format_batch_tool_report()` in `core/agent.py`.

This feature allows the model to request multiple tool calls in a single response while preserving deterministic execution behavior.

### 10.1 Why batch execution exists

Batch execution exists to let the model perform related steps efficiently in one turn.

Examples include:
- listing a directory and then reading a discovered file,
- locating files and then searching inside them,
- combining several lightweight information-gathering steps before giving a final answer.

This reduces unnecessary turn count, but it also increases the need for strict execution rules.

### 10.2 Execution order

Tool calls in a batch are executed in order.

This is important because later calls may depend on earlier ones. For example, changing directories before listing files is order-sensitive.

The agent preserves the original order from the parsed `tool_calls` array.

### 10.3 Fail-fast behavior

The current runtime policy is fail-fast:

- `FAIL_FAST_BATCH = True`

If one tool call fails, later calls in that same batch are marked as skipped instead of being executed.

This behavior is intentional. It prevents the runtime from continuing with assumptions that may no longer be valid after an earlier failure.

### 10.4 Record structure

Each call in a batch is represented internally by a `BatchToolRecord`, which includes:

- index and total
- action name
- tool input
- status (`success`, `failed`, or `skipped`)
- observation text
- error text if applicable
- display item count

This internal record structure makes reporting and debugging clearer and keeps the batch feature explicit rather than implicit.

### 10.5 Reporting format

After execution, the agent formats a batch report that includes:
- per-tool status lines
- observations or errors
- display counts when relevant
- summary totals for success, failure, skipped calls, and displayed items

This report is then appended back into the conversation as a `TOOL RESULT (batch)` message.

That means the model sees a structured textual summary of what happened and can decide what to do next.

### 10.6 Display-oriented tools in a batch

Some tools return `ToolResult` objects with display items rather than only plain text.

The agent handles this by:
- sending display items to the frontend callback,
- counting how many display items were shown,
- preserving a short textual observation for the model.

This is especially important for tools like `show_file` and `show_files`, where the user sees the actual rendered content but the model receives only a summarized observation.

### 10.7 Runtime rejection of oversized batches

Even if the parser accepts a batch structure, the agent rejects batches that exceed `MAX_BATCH_TOOL_CALLS`.

In that case, the batch is not executed. Instead, the agent appends an error result indicating that too many tool calls were requested.

This is a runtime safety policy rather than a parsing rule.

### 10.8 Implications for tool authors and prompt design

Batch execution means tools should be:
- predictable,
- side-effect-aware,
- usable in sequence,
- clear in their error messages.

It also means prompt wording matters: the model should understand that batches are possible, ordered, and fail-fast.

From an architectural perspective, batch execution belongs in the agent core because it is about orchestration policy, not about any one specific tool.

---

## 11. Tool registry and autodiscovery

The tool registry is the mechanism that turns plain Python functions into agent-available capabilities.

It lives in `core/tool_registry.py` and is one of the key architectural pieces that keeps tools modular. Instead of hardcoding tool knowledge into the agent, the system discovers and registers tools dynamically.

### 11.1 What the registry does

The registry stores `ToolSpec` objects, each of which describes:

- the tool name
- the callable function
- the human-readable description
- parameter metadata
- whether the tool requires runtime state
- an optional example

This means the system has a single source of truth for tool metadata.

### 11.2 Why the registry matters architecturally

Without a registry, there would be pressure to put tool knowledge directly into the agent or prompt-building code. That would make tool additions more invasive and would tightly couple the agent to a fixed tool set.

With the registry:
- the agent only needs a tool name and input
- the prompt builder only needs registry metadata
- tool modules remain self-contained
- adding a new tool usually does not require editing the agent core

This is one of the strongest examples of the project’s modular design.

### 11.3 `@tool` as the registration boundary

Tools are registered through the `@tool(...)` decorator.

That decorator captures metadata at definition time and stores the resulting `ToolSpec` in the global registry. The function itself remains an ordinary Python callable.

This design has two benefits:
- tool metadata stays close to the tool implementation
- registration is declarative rather than centralized in one giant list

### 11.4 Autodiscovery

Autodiscovery is triggered from runtime startup through `autodiscover("tools")`.

`core/tool_registry.py` walks the `tools` package with `pkgutil.walk_packages(...)` and imports each non-private module. Importing those modules causes the decorators to execute, which populates the global registry.

Private modules are skipped if their package/module name starts with `_`.

This matters because it lets the repository grow tool families naturally:
- `tools/fs/*`
- `tools/math/*`
- future packages such as `tools/git/*` or `tools/http/*`

without having to maintain a manual registration table.

### 11.5 Failure behavior during autodiscovery

If a tool module fails to import, autodiscovery warns instead of crashing startup immediately.

That tradeoff makes startup more resilient, though it also means broken tool modules may surface later when a tool is actually needed. This behavior should remain well understood because it affects debugging expectations.

### 11.6 `requires_state`

A key part of tool metadata is `requires_state`.

If `requires_state=True`, the agent injects the current `AgentState` as the first argument when executing the tool. This allows tools to access shared runtime data like:
- current working directory
- selected model information
- the edit store

This is preferable to letting tools import runtime globals directly.

### 11.7 The registry as a source of truth

The registry is not only used for execution. It is also used to build the system prompt. That means the same metadata drives both:
- what the model is told exists
- what the runtime can actually execute

That alignment is extremely valuable. It reduces drift between documentation, prompting, and runtime behavior.

---

## 12. System prompt generation

The system prompt is generated in `runtime/prompt.py`.

Rather than storing a completely static prompt, the project builds the tool portion dynamically from the registry. This keeps prompt content aligned with the actual installed tool set.

### 12.1 Why prompt generation is dynamic

A static prompt would quickly become stale whenever:
- tools were added,
- parameters changed,
- examples were updated,
- tool descriptions were improved.

By deriving the available-tools section from the registry, the runtime avoids manually duplicating tool documentation in multiple places.

### 12.2 What `runtime/prompt.py` does

The prompt builder:
- formats tool signatures,
- lists descriptions,
- includes parameter descriptions,
- includes example calls when available,
- embeds protocol rules and behavioral guardrails.

The result is a single system prompt string passed into the `Agent` during creation.

### 12.3 What is dynamic vs static

Dynamic content includes:
- tool names
- tool parameter names
- tool descriptions
- tool examples

Static content includes:
- response mode rules
- JSON formatting rules
- filesystem usage guidance
- general tool-use instructions
- protocol cautions such as no markdown around tool calls

This split is a good architectural compromise. The invariant execution protocol remains fixed, while the tool inventory is derived automatically.

### 12.4 Why prompt generation lives in `runtime/`

Prompt generation is close to composition rather than domain logic.

It depends on the registry, but it is not itself part of protocol parsing or tool execution. It is effectively runtime policy: how to present the current system’s capabilities to the model.

That makes `runtime/prompt.py` the right home.

### 12.5 Coupling considerations

Prompt wording can affect real runtime behavior because the model follows those instructions when deciding whether to call tools or return a final answer.

For that reason, changes in these areas often need coordinated thinking across:
- `runtime/prompt.py`
- `core/protocol.py`
- `core/agent.py`
- tests covering parser and agent behavior

The prompt is not just documentation. It is part of the operational behavior of the system.

---

## 13. Runtime state

Runtime state is defined in `runtime/state.py`.

This module provides the shared mutable context needed during agent execution without making the whole system depend on global variables.

### 13.1 `ModelConfig`

`ModelConfig` captures the currently selected model environment:

- `provider_key`
- `provider_label`
- `model`
- `api_key`
- `base_url`
- `api_type`

This structure gives the runtime and frontends a stable way to talk about the active model configuration without exposing provider internals everywhere.

### 13.2 `AgentState`

`AgentState` currently includes:

- `cwd`
- `model_config`
- `edit_store`

This is deliberately compact. The goal is not to store every possible concern in one giant mutable object, but to keep only the shared execution context that truly needs to persist across turns.

### 13.3 Why state is centralized

A centralized runtime state object is useful because several parts of the application need the same context:

- filesystem tools need `cwd`
- the agent needs model/provider context for prompt injection
- frontends need model and pending-edit information for display
- edit tools need access to the edit store

Using a shared state object is cleaner than passing many unrelated values through every function call.

### 13.4 Why state is not global

The state is passed into the agent and tools rather than being stored in a hidden global singleton.

That design improves:
- testability
- composability
- clarity of dependencies
- potential future multi-session support

It also makes it easier to reason about where mutable state comes from.

### 13.5 State ownership boundaries

Even though `AgentState` is shared, not every module should mutate it casually.

Typical ownership patterns are:
- tools like `cd()` update `cwd`
- runtime/frontends update `model_config` during model switching
- edit-related code interacts with `edit_store`

A good rule is that state should be changed by the layer that naturally owns the corresponding workflow.

### 13.6 Runtime state and model context

One especially important detail is that parts of runtime state are surfaced back into the model prompt through the agent’s runtime-context injection.

So runtime state is not only operational state for Python code; it also shapes model behavior.

That makes changes to state semantics architecturally significant.

---

## 14. Filesystem tools

The filesystem tools live under `tools/fs/` and are a major capability group in the project.

They are intentionally split into focused modules rather than one large file of unrelated functions.

### 14.1 Module split inside `tools/fs/`

Current responsibilities are roughly:

- `read.py` — cwd and file display/read tools
- `search.py` — file search and text search
- `edit.py` — edit proposal tools
- `analyze.py` — AST-based Python analysis tools
- `_shared.py` — internal helpers and safety limits

This split keeps tool families coherent and makes it easier to work on one part of filesystem behavior in isolation.

### 14.2 Path resolution

Filesystem tools resolve relative paths against `state.cwd` using `resolve_path(state, path)` from `_shared.py`.

This is the canonical path-resolution rule for tools. Contributors should prefer that helper over ad hoc path handling.

It ensures that:
- relative path behavior is consistent,
- frontend commands and model tool calls agree about cwd semantics,
- future path policy changes can stay centralized.

### 14.3 Model-visible vs user-visible file access

One of the most important design distinctions in the tool layer is the difference between:

- tools that return file contents to the model
- tools that display file contents directly to the user

Examples:
- `read_file()` returns content to the model
- `show_file()` and `show_files()` render content to the user and return only summarized observations to the model

This separation is central to both safety and prompt discipline.

### 14.4 Shared limits and traversal policy

`tools/fs/_shared.py` defines a set of limits and policies, including things like:
- ignored directories
- file size limits for reading
- display size limits
- line-range normalization
- limits for multi-file display and analysis

Centralizing these rules matters because otherwise each filesystem tool would implement slightly different policy.

### 14.5 Search and analysis tools

The filesystem package is not only about raw file reading. It also includes:

- recursive file finding
- exact text search
- Python AST analysis

This is an important architectural point: tools are not merely wrappers around OS commands. They are capability modules tailored for model-guided code exploration.

### 14.6 Why filesystem tools should stay in their own package

Filesystem access is a large enough concern that it deserves a dedicated package with shared helpers.

Keeping it separate:
- prevents duplication,
- keeps safety and policy rules centralized,
- makes the tooling easier to test,
- avoids mixing unrelated capabilities such as math and filesystem logic.

---

## 15. Pending edits and file creation

The pending-edit system lives in `editing/` and is exposed to the model primarily through tools in `tools/fs/edit.py`.

This subsystem is one of the project’s most important safety and workflow features.

### 15.1 Core idea

The model does not directly rewrite files.

Instead, it proposes a change. That proposal is stored as a `PendingEdit`, shown to the user, and only written to disk if the user explicitly approves it.

This keeps file mutation auditable and reversible at the decision stage.

### 15.2 Main components

The subsystem is split across:

- `editing/model.py` — data structures such as `FileEdit` and `PendingEdit`
- `editing/store.py` — lifecycle management
- `editing/diff.py` — unified diff generation

This is a strong modular split:
- data model
- stateful lifecycle logic
- diff formatting

### 15.3 Exact-match edit model

The `propose()` path in `EditStore` applies exact-match find/replace edits in memory before anything is written.

Each `find` block must match exactly once. If it matches zero times or multiple times, the proposal fails.

This is an intentional safety constraint. It makes proposals more explicit and reduces the chance of ambiguous edits being applied to the wrong part of a file.

### 15.4 File creation workflow

The system also supports pending file creation via `propose_create()`.

That means the same approval model applies to both:
- editing existing files
- creating entirely new files

This consistency is good architecture: mutation policy stays unified even though the underlying actions differ.

### 15.5 Approval and stale-checking

When an existing-file edit is approved, the store rereads the current file and compares it to the original content captured at proposal time.

If the file has changed in the meantime, the edit is treated as stale and will not be applied.

This protects against silently applying outdated edits on top of changed files.

### 15.6 Why tools should delegate to `editing/`

Tools like `propose_file_edit()` and `create_file()` should remain thin wrappers around the editing subsystem.

Their responsibilities are mainly:
- validate tool inputs
- resolve paths
- translate raw tool input into `FileEdit` objects
- call the edit store
- format a human-readable result

They should not duplicate lifecycle logic that already belongs in `EditStore`.

### 15.7 Architectural value of the pending-edit system

The pending-edit flow makes this project more than a simple tool runner. It introduces a controlled mutation workflow with clear ownership and review points.

That is a major architectural strength because it:
- separates proposal from application,
- reduces accidental destructive behavior,
- gives frontends a stable abstraction for displaying/editing pending work,
- creates a natural place for future expansion such as richer diff review or grouped changes.

---

## 16. LLM abstraction and providers

The LLM layer lives in `llm/` and is responsible for isolating provider-specific behavior from the rest of the application.

This is a crucial boundary. The agent should be able to ask for a chat completion without knowing whether the underlying provider is OpenAI Responses, OpenAI-compatible chat completions, or some future backend.

### 16.1 Interface-first design

`llm/base.py` defines the `LLMClient` protocol.

That protocol is intentionally small: a client must provide a `chat(messages: list[dict]) -> str` method.

This narrow interface is a strong design choice because it gives the rest of the application a stable contract. The agent only needs to know how to send messages and receive a string response.

### 16.2 Concrete clients

Current concrete implementations include:

- `llm/openai_chat.py`
- `llm/openai_responses.py`

These modules translate the shared message format into provider-specific API calls.

By isolating this code in dedicated client modules, the rest of the system stays free of provider-specific request formatting.

### 16.3 Provider configuration

Provider configuration is loaded in `llm/providers.py`.

That module owns:
- parsing `providers.toml`
- resolving API keys and environment-based overrides
- validating provider entries
- creating `ProviderConfig` objects
- constructing concrete clients
- interactive provider/model selection for CLI mode

This is a fairly broad module, but the responsibilities still fall under one coherent concern: provider management.

### 16.4 `ProviderConfig`

`ProviderConfig` is the structured representation of a configured provider. It includes values such as:

- provider key
- display label
- API key
- base URL
- API type
- default model
- model-listing support
- source environment variable names

This gives the runtime a clean handoff object instead of raw TOML dictionaries.

### 16.5 Factory-based client creation

`create_llm_client(provider, model)` is the main construction boundary between runtime and provider-specific code.

The runtime passes in a selected provider and model, and the factory returns the correct concrete client implementation.

This means:
- runtime does not need provider-specific branching everywhere
- the agent remains unaware of provider classes
- adding a provider is localized mostly to `llm/`

### 16.6 Model listing and selection

`llm/providers.py` also contains interactive CLI-oriented provider/model selection helpers such as:
- `choose_provider()`
- `choose_model()`
- `list_provider_models()`

Architecturally, this is slightly mixed because the module contains both provider loading and some interactive selection behavior. However, it still remains within the broader provider-management concern and is kept out of `core/`.

### 16.7 Why provider logic should stay out of `core/`

Provider APIs are unstable, external, and implementation-specific. If they leak into `core/`, then the most reusable part of the application becomes entangled with vendor-specific behavior.

Keeping provider logic in `llm/` protects the rest of the architecture from:
- API differences
- authentication details
- base URL differences
- provider-specific quirks

### 16.8 Extension implications

If a new provider is added, the main changes should usually stay inside:
- `llm/`
- provider configuration files
- tests for provider integration if added

The goal is that neither the agent core nor the tool layer needs to change just because a new LLM backend exists.

---

## 17. Frontend adapters

The frontend abstraction layer lives in `adapters/`.

Its purpose is to keep user interaction and rendering concerns separate from agent execution and tool behavior.

### 17.1 Adapter philosophy

The project treats frontends as replaceable outer layers.

That means the frontend is responsible for things like:
- collecting input
- rendering responses
- displaying logs or panels
- exposing frontend-specific commands or views

But it should not become the place where core agent semantics are implemented.

### 17.2 `IOAdapter` protocol

`adapters/base.py` defines the `IOAdapter` protocol.

It includes methods such as:
- `read_input()`
- `show_response()`
- `show_display_items()`
- `show_error()`
- `show_debug()`
- `show_tool()`
- `show_raw()`
- `show_processing()`

This protocol is what makes the classic CLI frontend replaceable in principle.

### 17.3 Callback flow from the agent

The agent emits debug/tool/raw/error/display information through callbacks, and the active frontend decides what to do with them.

That is a key architectural pattern in the codebase:
- the core emits events
- the frontend renders them

This is much healthier than having the agent directly print output.

### 17.4 Two current frontend families

At the moment, the repository has two main frontend families:
- `adapters/cli/`
- `adapters/textual/`

They are not symmetric yet in implementation style, but they both occupy the same conceptual outer layer.

### 17.5 Why adapters matter

Without an adapter layer, UI logic would leak into runtime and core modules. Over time that would make it much harder to:
- add a new frontend
- test the agent independently
- reuse tools in another interface
- keep presentation separate from behavior

The adapter layer prevents the outermost UX layer from becoming the real application center.

---

## 18. CLI frontend

The CLI frontend lives in `adapters/cli/` and is currently the more explicit implementation of the adapter pattern.

It is composed from several focused modules rather than one monolithic terminal script.

### 18.1 Main CLI modules

Important pieces include:

- `adapter.py` — adapter object wiring together CLI behavior
- `display.py` — Rich-based rendering helpers
- `input.py` — prompt_toolkit-based input handling
- `logger.py` — debug/raw/tool/error output helpers
- `commands.py` — backslash command handling

This internal split is good architecture in miniature: the frontend itself is modular.

### 18.2 `CLIAdapter`

`CLIAdapter` in `adapter.py` is the concrete adapter implementation that the runtime uses in CLI mode.

It delegates to input, display, and logger helpers rather than owning all terminal behavior directly.

This keeps the adapter itself thin and focused.

### 18.3 Display responsibilities

`adapters/cli/display.py` owns Rich-based presentation, including:
- startup banners
- help output
- state display
- pending diff rendering
- display-item rendering
- processing spinners

That means terminal formatting decisions stay outside `core/` and outside tool implementations.

### 18.4 Command handling

`adapters/cli/commands.py` handles user commands such as:
- `\help`
- `\reset`
- `\pwd`
- `\cd`
- `\pending`
- `\approve`
- `\reject`
- `\models`
- `\debug`
- `\exit`
- `\quit`

This is intentionally separate from the agent’s model-driven tool-calling loop. Some user actions are better handled directly and locally rather than routing them back through the LLM.

### 18.5 Controlled coupling in CLI commands

The CLI command layer mostly avoids direct imports from runtime and llm internals by receiving callbacks from `runtime/cli_loop.py`.

That is a subtle but important boundary. It prevents command-handling code from becoming tightly coupled to runtime composition details.

### 18.6 Input behavior

`adapters/cli/input.py` encapsulates prompt_toolkit behavior and history handling.

That makes input UX improvements a local change rather than something that must touch agent code.

### 18.7 Why the CLI frontend is a useful architectural reference

Even if Textual becomes the primary interface, the CLI code is still valuable as a clean example of how to keep:
- input
- rendering
- commands
- runtime wiring

as separate concerns.

---

## 19. Textual frontend

The Textual frontend lives primarily in `adapters/textual/app.py` and is launched through `runtime/textual_loop.py`.

It is a richer interaction layer than the CLI and is evolving toward a more app-like terminal experience.

### 19.1 Current role of the Textual app

The Textual app wraps the existing synchronous agent in a more interactive UI while preserving the same underlying execution model.

It currently provides:
- chat interaction
- model selection mode
- pending-edit selection mode
- theme toggling
- state display in the header
- background-thread execution of agent steps

### 19.2 UI modes

One notable implementation detail is that the Textual app explicitly tracks different modes:
- `chat`
- `model_select`
- `pending_select`

This is a useful architectural pattern because it keeps distinct interaction workflows from collapsing into one large event handler.

### 19.3 Background execution

The Textual app uses `@work(thread=True, exclusive=True)` to run agent steps and model-loading work without freezing the UI.

That is an important frontend-specific concern and exactly the kind of behavior that should stay in the frontend layer rather than moving into the agent.

### 19.4 Model selection behavior

The Textual app supports searchable model selection by:
- loading models per provider
- rendering them in a tree
- filtering them by query
- switching `state.model_config` and `agent.llm` when a new selection is confirmed

This is richer than the CLI selection flow, but it still builds on the same shared runtime state and provider infrastructure.

### 19.5 Pending edit behavior

The Textual app also exposes pending edits as a structured UI workflow:
- list pending edits
- search/filter them
- inspect diffs
- approve or reject selected edits

This is a good example of frontend specialization built on a shared backend abstraction. The pending-edit logic itself still lives in `editing/`; the Textual app just renders and drives it differently.

### 19.6 Logging and display callbacks

The current Textual app mainly logs debug/tool/raw/error/display callback output rather than rendering every callback stream as polished in-app UI.

That is a useful limitation to document because it shows where UI richness is still evolving.

### 19.7 Architectural significance of Textual

The Textual frontend demonstrates that the system architecture is flexible enough to support a significantly richer UI without replacing:
- the agent core
- the tool registry
- the pending edit system
- the provider abstraction

That is evidence that the modular layering is working.

---

## 20. How to work on one subsystem in isolation

One of the explicit goals of the project is that contributors should not need to understand the whole repository to make meaningful changes.

This section describes the minimum reading path for common types of work.

### 20.1 If you are working only on a tool

Usually read:
- `tools/_base.py`
- the relevant tool module
- `tools/fs/_shared.py` if it is a filesystem tool
- related tests in `tests/tools/...`

Usually ignore at first:
- frontend code
- provider code
- most of runtime

### 20.2 If you are working only on the protocol

Usually read:
- `core/protocol.py`
- `core/agent.py`
- `runtime/prompt.py`
- protocol-related tests

You usually do not need to understand CLI rendering or Textual widgets.

### 20.3 If you are working only on pending edits

Usually read:
- `editing/model.py`
- `editing/store.py`
- `editing/diff.py`
- `tools/fs/edit.py`
- pending-related frontend surfaces if needed

You usually do not need to understand provider loading or search tools.

### 20.4 If you are working only on the CLI

Usually read:
- `runtime/cli_loop.py`
- `adapters/cli/adapter.py`
- `adapters/cli/display.py`
- `adapters/cli/commands.py`
- `adapters/cli/input.py`

You usually do not need deep knowledge of the Textual app.

### 20.5 If you are working only on the Textual frontend

Usually read:
- `runtime/textual_loop.py`
- `adapters/textual/app.py`
- `runtime/bootstrap.py`
- `runtime/state.py`

You usually do not need to modify the core protocol unless the UI feature changes model-execution semantics.

### 20.6 If you are working only on providers

Usually read:
- `llm/base.py`
- `llm/providers.py`
- the relevant concrete client module
- configuration examples

You usually do not need to understand CLI commands, pending edits, or Rich rendering.

### 20.7 Rule of minimal context

Start from the narrowest subsystem that obviously owns the change.

Only widen the set of files you read if:
- tests point to another dependency,
- a boundary needs to change,
- the existing architecture clearly places the concern elsewhere.

That disciplined approach is one of the main benefits of the architecture.

---

## 21. Extension guides

This section summarizes how to extend the system without breaking the architecture.

The general rule is simple: add new behavior in the layer that already owns that kind of concern. Do not use extension work as an excuse to bypass boundaries.

### 21.1 Adding a new tool

Typical steps:

1. choose the right package under `tools/`
2. create the tool function
3. decorate it with `@tool(...)`
4. use `requires_state=True` only if runtime state is actually needed
5. return either a string or a `ToolResult`
6. add tests in the matching `tests/tools/...` area

The important architectural rule is that tool additions should usually not require edits to:
- `core/agent.py`
- the registry implementation
- frontend code

If they do, the design should be questioned.

### 21.2 Adding a new provider

Typical steps:

1. create a concrete client in `llm/`
2. extend the factory in `llm/providers.py`
3. add or document the provider configuration shape
4. test provider creation behavior if applicable

This work should largely remain inside `llm/` plus docs/config examples.

### 21.3 Adding a new frontend

Typical steps:

1. define the runtime entry path
2. implement rendering/input behavior in a new adapter package
3. reuse `runtime/bootstrap.py` where possible
4. keep agent execution in the existing core

A new frontend should consume the existing system, not replace it.

### 21.4 Adding a new CLI command

Typical steps:

1. add a branch in `adapters/cli/commands.py`
2. add any rendering support in `adapters/cli/display.py` if needed
3. keep command-specific behavior local unless it exposes a reusable backend concern

A command should not become a backdoor for bypassing architecture boundaries.

### 21.5 Adding a new pending-edit action

If a feature changes the lifecycle of proposed edits, start in `editing/` first.

Only after the backend lifecycle logic is clean should you expose it through:
- tools
- CLI commands
- Textual UI

This preserves backend/frontend separation.

### 21.6 When an extension should trigger redesign

If adding a feature requires touching many unrelated layers, pause and ask whether:
- the concern belongs in the wrong module
- a new abstraction is missing
- an existing boundary has become too weak

Healthy extension work usually has a narrow impact surface.

---

## 22. Testing strategy

The testing strategy follows the modular architecture: tests should usually live near the subsystem they validate.

### 22.1 Current test organization

The repository already has tests organized by subsystem, including:
- `tests/core/`
- `tests/editing/`
- `tests/tools/fs/`
- `tests/tools/math/`

This mirrors the structure of the source tree and makes it easier to discover where new coverage should go.

### 22.2 What to test by layer

#### Core
Test:
- protocol parsing
- invalid response handling
- batch behavior
- agent loop edge cases

#### Editing
Test:
- exact-match edits
- stale edit rejection
- create-file proposals
- approval/rejection lifecycle

#### Tools
Test:
- input validation
- path handling
- error reporting
- interaction with shared helpers

#### Frontends
Frontend tests can be more selective, but important interaction logic should still be covered where practical.

### 22.3 Why tests should stay local to the owning subsystem

A test should ideally fail because one subsystem broke, not because the entire application stack is entangled.

That is why focused subsystem tests are preferred over only broad end-to-end style testing.

### 22.4 Architecture and tests reinforce each other

A well-modularized codebase is easier to test, and a well-structured test tree helps preserve modularity.

If a feature is very difficult to test in isolation, that may be a sign that the boundaries around it are not clean enough.

---

## 23. Code review checklist

When reviewing a change, check not only whether it works, but whether it preserves the intended architecture.

### 23.1 Boundary checks

Ask questions like:
- Did `core/` gain a dependency on frontend code?
- Did a tool start importing rendering logic?
- Did provider-specific behavior leak outside `llm/`?
- Did mutation logic bypass `editing/`?

### 23.2 Ownership checks

Also check:
- Does the change live in the layer that naturally owns the concern?
- Is there duplicated logic that should have been centralized?
- Was a composition concern placed into `core/` unnecessarily?

### 23.3 Test checks

Verify that:
- tests were added in the correct subsystem area
- behavior changes have corresponding coverage
- architecture-sensitive logic is not left untested

### 23.4 Documentation checks

If a change affects architecture boundaries, extension points, or contributor expectations, this developer reference should be updated.

The main architectural failure mode in growing repositories is not just bad code, but undocumented drift.

---

## 24. Known architectural constraints

The architecture is intentionally strong in some places, but it is not perfect or finished.

### 24.1 Protocol strictness

The raw-JSON tool-call protocol is powerful and predictable, but also brittle with weaker models. This is a conscious tradeoff in favor of deterministic parsing.

### 24.2 No filesystem sandbox

Filesystem tools intentionally operate on the local machine without sandboxing. That is useful for local-agent workflows, but it is also a real trust boundary that contributors should remember.

### 24.3 CLI/Textual asymmetry

The CLI and Textual frontends currently share the same backend, but they are not feature-identical in implementation style or maturity. That is acceptable for now, but worth acknowledging.

### 24.4 Mixed responsibilities in some modules

Some modules, especially `llm/providers.py`, combine responsibilities that could be split further later. This is acceptable while the codebase is still evolving, but should stay visible as a potential refactor area.

### 24.5 Shared mutable state remains a design responsibility

`AgentState` is intentionally small, but as the project grows, it will need discipline to avoid turning into a catch-all container.

---

## 25. Future architecture direction

The long-term direction of the project should continue to strengthen modularity rather than weaken it.

### 25.1 Preserve replaceable frontends

The CLI and Textual apps should continue to share the same core rather than evolving into two separate backend implementations.

### 25.2 Keep the agent core small

New capabilities should continue to be pushed to tools, editing, providers, and adapters where appropriate instead of bloating `core/agent.py`.

### 25.3 Strengthen backend/frontend separation

As the Textual app grows, the backend contracts it depends on should become clearer rather than more implicit.

### 25.4 Expand capabilities through modules, not special cases

Future growth should mostly happen by:
- adding tools
- adding provider implementations
- improving editing workflows
- adding adapter/frontends

not by hardcoding one-off paths into the agent core.

### 25.5 Optimize for local reasoning

The most important architectural property to preserve is this: a contributor should be able to work productively on one part of the repository without understanding the whole system.

That is the standard this codebase should continue to protect.
