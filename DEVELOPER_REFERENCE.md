# Developer Reference

Everything you need to know to work in this codebase without reading files you don't care about.

---

## Project map (one line each)

```
config/settings.py       — loads .env, defines PROJECT_ROOT and file paths
core/protocol.py         — parses raw LLM strings → tool call / final answer / invalid
core/tool_registry.py    — @tool decorator, registry singleton, autodiscover()
core/agent.py            — the agent loop (send message → call tools → return answer)
editing/model.py         — FileEdit and PendingEdit dataclasses
editing/store.py         — propose / approve / reject edits (owns the pending-edit lifecycle)
editing/diff.py          — unified diff generation
llm/base.py              — LLMClient protocol (abstract interface)
llm/openai_chat.py       — OpenAI chat completions implementation
llm/openai_responses.py  — OpenAI responses API implementation
llm/providers.py         — loads providers.toml, builds LLM clients
tools/_base.py           — @tool re-export, ToolResult, DisplayItem
tools/fs/_shared.py      — internal helpers for fs tools (never import outside tools/fs/)
tools/fs/read.py         — pwd, ls, cd, read_file, show_file, show_files
tools/fs/search.py       — find_files, search_text
tools/fs/edit.py         — propose_file_edit
tools/fs/analyze.py      — analyze_python_file, analyze_python_files
tools/math/arithmetic.py — add, subtract, multiply, divide, power
io/base.py               — IOAdapter protocol
io/cli/adapter.py        — CLIAdapter (wires logger + display + input)
io/cli/commands.py       — backslash command handlers (\help, \approve, etc.)
io/cli/display.py        — Rich panels, file display, banners, spinners
io/cli/input.py          — prompt_toolkit input with history + multiline
io/cli/logger.py         — debug / tool / raw / error / ai_response logging
runtime/state.py         — AgentState (cwd + model_config + edit_store)
runtime/prompt.py        — builds system prompt from the tool registry
runtime/loop.py          — entry point, wires everything together
main.py                  — one line: run_agent()
```

---

## Dependency rules — never break these

```
Direction of allowed imports (→ means "may import from"):

config/          → nothing from this project
core/            → nothing from this project
editing/         → core/ only
llm/             → config/  (for file paths)
tools/           → tools/_base.py, editing/model.py only
                   (tools/fs/* also imports from tools/fs/_shared.py)
io/              → tools/_base.py  (for DisplayItem type only)
                   io/cli/commands.py also imports from tools/fs/read.py and llm/providers.py
runtime/         → everything (this is the only composition root)
```

**Red flags — if you see these, something is wrong:**
- Any file in `core/` importing from `tools/`, `io/`, `runtime/`, `editing/`, or `llm/`
- Any file in `tools/` importing from `io/`, `runtime/`, or `core/` (except `core/tool_registry.py` via `tools/_base.py`)
- Any file in `editing/` importing from `tools/`, `io/`, `runtime/`, or `llm/`
- Any file importing from `runtime/` except `main.py`

---

## How to add a new tool

**This is the most common task. It touches exactly two things: one new file, and nothing else.**

1. Create a file in an appropriate subfolder of `tools/`:
   ```
   tools/finance/market.py
   ```

2. Create an `__init__.py` if it's a new subfolder:
   ```
   tools/finance/__init__.py    ← empty, just a package marker
   ```

3. Write the tool:
   ```python
   from tools._base import tool, ToolResult   # only import you need

   @tool(
       description="Get the current stock price.",
       params={"ticker": "Stock ticker symbol, e.g. AAPL"},
       example={"action": "get_price", "input": {"ticker": "AAPL"}},
   )
   def get_price(ticker: str) -> str:
       # ... your logic here
       return f"AAPL: $189.42"
   ```

4. That's it. Autodiscovery picks it up on next startup. Nothing else changes.

**Rules for tool functions:**
- Return a plain `str` for simple text results.
- Return a `ToolResult(observation=..., display_items=[...])` if you want to show the user a rendered panel (like a file view) while keeping the LLM observation separate and short.
- If the tool needs to read `state.cwd` or `state.edit_store`, add `requires_state=True` to `@tool` and accept `state` as the first parameter.
- Never import from `io/`, `runtime/`, or `core/agent.py` inside a tool.
- Never write to disk directly — use `state.edit_store.propose()` and let the user approve.

---

## How to add a new LLM provider

1. Create `llm/myprovider.py`:
   ```python
   from llm.providers import ProviderConfig

   class MyProviderClient:
       def __init__(self, provider: ProviderConfig):
           self._model = provider.default_model
           # ... set up API client

       def chat(self, messages: list[dict]) -> str:
           # ... call your API
           return response_text
   ```

2. Register it in `llm/providers.py` inside `create_llm_client()`:
   ```python
   if provider.api_type == "myprovider":
       from llm.myprovider import MyProviderClient
       return MyProviderClient(effective)
   ```

3. Add an entry to `providers.toml`:
   ```toml
   [[providers]]
   key = "myprovider"
   label = "My Provider"
   api_type = "myprovider"
   api_key_env = "MY_PROVIDER_API_KEY"
   default_model = "my-model-v1"
   supports_model_listing = false
   ```

---

## How to add a new IO mode (voice, web API, etc.)

1. Create `io/mymode/adapter.py` implementing the `IOAdapter` protocol from `io/base.py`.

2. In `runtime/loop.py`, replace `CLIAdapter()` with `MyModeAdapter()`.

The agent, tools, LLM clients, and editing — none of them change.

---

## How to add a new backslash command

Add a branch in `io/cli/commands.py` inside `handle_command()`:

```python
if command == "\\mycommand":
    _handle_mycommand(state, argument)
    return True, False
```

Add the handler function at the bottom of the same file:

```python
def _handle_mycommand(state, argument: str) -> None:
    display.show_command_message("Hello from mycommand.", title="My Command", border_style="cyan")
```

Also add it to the help table in `io/cli/display.py` inside `show_help()`.

---

## AgentState — what's on it and when to use it

```python
state.cwd           # pathlib.Path — current working directory
                    # Updated by cd() and \cd command.
                    # Always use resolve_path(state, path) — never Path(path) directly.

state.model_config  # ModelConfig — currently selected provider + model
                    # provider_key, provider_label, model, api_key, base_url, api_type

state.edit_store    # EditStore — owns all pending file edits
                    # state.edit_store.propose(path, edits)   → (PendingEdit, diff_str)
                    # state.edit_store.approve(edit_id)       → message str
                    # state.edit_store.reject(edit_id)        → message str
                    # state.edit_store.pending()              → dict[int, PendingEdit]
```

---

## The pending-edit workflow

The agent **never writes files directly**. It proposes edits:

1. Agent calls `propose_file_edit` tool → `state.edit_store.propose()` creates a `PendingEdit` and returns a diff. The file is **not touched**.
2. User runs `\pending` to see pending edits.
3. User runs `\approve <id>` → `state.edit_store.approve()` checks the file hasn't changed, then writes it.
4. Or user runs `\reject <id>` → marked rejected, file untouched.

If you're adding a new file-writing tool, follow this same pattern: call `state.edit_store.propose()`, never write directly.

---

## Bugs fixed in this refactor

### Bug: `propose_file_edit` always crashed
**Original code** in `tools/file_tools.py`:
```python
resolved_path = resolve_path(state.cwd, path)  # WRONG: passes a Path, not state
```
`resolve_path` expects an object with a `.cwd` attribute. Passing `state.cwd` (a raw `Path`) caused `AttributeError: 'PosixPath' object has no attribute 'cwd'`.

**Fixed** in `tools/fs/edit.py`:
```python
resolved_path = resolve_path(state, path)  # CORRECT: passes state
```

---

## Running tests

```bash
python -m pytest tests/ -v
```

No install needed — `conftest.py` adds the project root to `sys.path`.

Test structure mirrors source structure:
```
tests/core/        → tests for core/
tests/editing/     → tests for editing/
tests/tools/fs/    → tests for tools/fs/
tests/tools/math/  → tests for tools/math/
```

When you add a new tool file `tools/finance/market.py`, add `tests/tools/finance/test_market.py`.

---

## What to check before committing

1. `python -m pytest tests/ -v` — all green.
2. No import from `runtime/` anywhere except `main.py`.
3. No import from `io/` or `core/agent.py` inside any `tools/` file.
4. New tools use `@tool` from `tools._base` (not directly from `core.tool_registry`).
5. New tools don't write files directly — they use `state.edit_store.propose()`.
6. New `__init__.py` files exist for any new subpackage.

---

## Git workflow

```bash
# Start new work
git checkout main && git pull
git checkout -b feature/my-feature

# During work
git add .
git commit -m "tools/finance: add get_price and get_holdings"

# Done
git checkout main
git merge feature/my-feature
# or: git rebase feature/my-feature  (cleaner history)
```

Branch naming:
- `feature/finance-tools` — new capability
- `fix/propose-edit-crash` — bug fix
- `refactor/structure` — structural change (this branch)