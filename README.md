# simple-ai-agent

A simple local Python AI agent for experimenting with LLMs, JSON-based tool usage, filesystem access, and basic agent loops.

The project runs as an interactive command-line app. The agent can use different LLM providers and call local Python tools through a strict raw-JSON tool-call protocol.

## Features

- Interactive local CLI agent
- Configurable LLM provider support via `providers.toml`
- Supports:
  - OpenAI via Responses API
  - OpenAI-compatible APIs via Chat Completions
  - Local OpenAI-compatible servers such as LM Studio, vLLM, llama.cpp, or similar setups
- Provider and model selection on startup
- Strict JSON-based tool calls
- Multi-step tool usage
- Runtime agent state with current working directory and selected model config
- Tool registry as the single source of truth
- System prompt generated from the tool registry
- Math tools
- Filesystem navigation
- File reading
- File and text search
- Direct file display tools for showing files to the user without sending their contents back to the model
- Rich-based CLI output
- prompt_toolkit-based input with multiline editing and history, with fallback to normal `input()`
- Debug mode
- Parser tests
- File-tool tests

## Setup

Requires Python 3.11 or newer.

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install runtime dependencies:

```bash
python -m pip install -r requirements.txt
```

For development and tests:

```bash
python -m pip install -r requirements-dev.txt
```

## Configuration

Provider configuration is stored in `providers.toml`.

Copy the example file:

```bash
cp providers.example.toml providers.toml
```

On Windows PowerShell:

```powershell
Copy-Item providers.example.toml providers.toml
```

Then edit `providers.toml` and define the providers you want to use.

API keys should usually be stored in `.env`, not directly in `providers.toml`.

Copy the example environment file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then edit `.env` and add your API keys.

Example provider entry:

```toml
[[providers]]
key = "openai"
label = "Personal OpenAI"
api_type = "responses"
api_key_env = "OPENAI_API_KEY"
default_model = "gpt-4.1-mini"
supports_model_listing = true
```

Example `.env` entry:

```env
OPENAI_API_KEY=your_api_key_here
```

For OpenAI-compatible APIs, set a `base_url`:

```toml
[[providers]]
key = "local_openai_compatible"
label = "Local OpenAI-Compatible API"
api_type = "chat_completions"
api_key_env = "LOCAL_OPENAI_API_KEY"
base_url = "http://localhost:1234/v1"
default_model = ""
supports_model_listing = true
```

For local servers that do not require an API key, use any placeholder value in `.env`:

```env
LOCAL_OPENAI_API_KEY=not-needed
```

The provider config supports:

```toml
api_key_env = "OPENAI_API_KEY"
```

or multiple fallback env vars:

```toml
api_key_envs = ["OPENAI_API_KEY", "OPENAI_PERSONAL_API_KEY"]
```

It also supports env-based base URLs and default models:

```toml
base_url_env = "GWDG_BASE_URL"
default_model_env = "GWDG_DEFAULT_MODEL"
```

Never commit your `.env` or `providers.toml` files.

## Usage

Start the agent:

```bash
python main.py
```

or on Windows:

```bash
py main.py
```

Choose a provider and model on startup:

```text
Choose provider:
[1] Personal OpenAI
[2] OpenAI-Compatible API
[3] Local OpenAI-Compatible API
```

Then chat with the agent:

```text
You: what is 3**8?
AI: 6561
```

## CLI Commands

Show help:

```text
\help
```

Show current agent state:

```text
\state
```

Show current working directory:

```text
\pwd
```

Change current working directory without using the LLM:

```text
\cd <path>
```

Select a different provider/model without restarting:

```text
\models
```

Show debug status:

```text
\debug
```

Enable debug output:

```text
\debug on
```

Disable debug output:

```text
\debug off
```

Reset the conversation context while keeping the current state:

```text
\reset
```

Exit the program:

```text
\exit
```

or:

```text
\quit
```

## Available Tools

### Math

- `add(a, b)`
- `subtract(a, b)`
- `multiply(a, b)`
- `divide(a, b)`
- `power(a, b)`

### Filesystem

- `pwd()`
- `ls(path=".")`
- `cd(path)`
- `read_file(path)`
- `show_file(path, start_line=None, end_line=None)`
- `find_files(pattern, path=".", max_results=100)`
- `show_files(pattern, path=".", max_files=30)`
- `search_text(query, path=".", file_pattern="*", max_results=100)`

Relative paths are resolved against the agent's current working directory. Absolute paths are allowed by design.

## File Tools: `read_file` vs `show_file` vs `show_files`

The project distinguishes between tools that give file contents to the model and tools that display file contents directly to the user.

### `read_file`

Use `read_file` when the model needs to inspect, reason about, explain, summarize, or modify file contents.

The file contents are returned to the model as a tool observation.

### `show_file`

Use `show_file` when the user wants to see one file or a line range.

The file contents are rendered directly in the local CLI for the user. The model receives only a short confirmation, not the file contents.

Example tool call:

```json
{"action": "show_file", "input": {"path": "main.py"}}
```

For a line range:

```json
{"action": "show_file", "input": {"path": "agent/agent.py", "start_line": 20, "end_line": 60}}
```

### `show_files`

Use `show_files` when the user wants to see many matching files, for example all Python files in the project.

The matching files are rendered directly in the local CLI for the user. The model receives only a short confirmation and a list of displayed files, not the file contents.

Example tool call:

```json
{"action": "show_files", "input": {"pattern": "*.py", "path": ".", "max_files": 30}}
```

## Tool-Call Protocol

The model has two response modes.

### 1. Tool call mode

If the model wants to call tools, the entire model response must be exactly one valid raw JSON object in one of these root shapes.

Single tool call:

```json
{"action": "tool_name", "input": {"param": "value"}}
```

Batch tool calls:

```json
{
  "tool_calls": [
    {"action": "tool_name_1", "input": {}},
    {"action": "tool_name_2", "input": {"x": 1}}
  ]
}
```

Rules:

- The whole response must be raw JSON.
- No Markdown.
- No code fences.
- No prose before or after the JSON.
- No comments.
- No extra keys.
- The JSON root must be an object.
- Valid root shapes are exactly one of:
  - single-call object with exactly `"action"` and `"input"`, or
  - batch object with exactly `"tool_calls"`.
- In single-call mode:
  - `"action"` must be a non-empty string.
  - `"input"` must be a JSON object.
- In batch mode:
  - `"tool_calls"` must be a non-empty array.
  - each item must be an object with exactly `"action"` and `"input"`.
  - each `"action"` must be a non-empty string.
  - each `"input"` must be a JSON object.
- Mixed root shapes are invalid (for example using both `"action"` and `"tool_calls"` in one object).
- Batch calls are executed in order with fail-fast behavior.

### 2. Final answer mode

If the model is done, it answers normally in plain text or Markdown.

Final answers are **not JSON**.

Correct final answer:

```text
I displayed all matching Python files above.
```

## Invalid Embedded Tool Calls

Tool calls embedded inside normal text are rejected.

Invalid:

```text
I would call: {"action": "pwd", "input": {}}
```

Invalid:

````text
```json
{"action": "pwd", "input": {}}
```
````

Valid:

```json
{"action": "pwd", "input": {}}
```

This strict parsing rule keeps the protocol predictable and prevents the model from mixing explanations with executable tool calls.

## How It Works

1. The agent builds a system prompt from the tool registry.
2. The user sends a message.
3. The model either:
   - returns a raw JSON tool call, or
   - returns a normal final answer.
4. The parser validates the model response.
5. If a tool call is valid, the agent executes the selected local tool.
6. Tool results are returned as observations.
7. The loop continues until the model returns a final answer.

For `show_file` and `show_files`, file contents are displayed directly to the user via the local CLI. The model receives only a short observation.

## Tests

Install dev dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run all tests:

```bash
python -m pytest -q
```

Run parser tests only:

```bash
python -m pytest tests/test_parser.py -q
```

Run file-tool tests only:

```bash
python -m pytest tests/test_file_tools.py -q
```

## Security Note

This agent intentionally has access to the local filesystem.

There is no filesystem sandbox by design. Relative paths are resolved against the agent's current working directory, and absolute paths are allowed.

The agent can read files and browse directories that the Python process can access. File contents returned by tools such as `read_file` may be sent to the selected LLM provider as part of the conversation context.

Use caution with sensitive data. Never commit API keys, `.env`, `providers.toml`, or private credentials.

## Roadmap

Possible next steps:

- Add approval-based file editing with pending changes
- Add AST-based Python file analysis
- Improve provider configuration UX
- Add optional CLI commands for managing providers
- Improve model filtering
- Add more tests for agent loop behavior
- Add optional native provider tool/function calling
- Add a future full terminal UI with Textual

## License

MIT License