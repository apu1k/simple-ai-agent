# simple-ai-agent

A local AI agent with a modern terminal UI, pluggable LLM providers, JSON-based tool use, and approval-based file editing.

The project is designed as a local-first agent runtime: chat with an LLM, let it use tools on your machine, review pending file edits safely, and switch providers or models without rebuilding the app.

![Chat UI](docs/screenshots/chat.png)

## Why this project is interesting

- Local AI agent with a real terminal app experience
- Textual UI with model selection and pending edit review
- Supports OpenAI and OpenAI-compatible backends
- Strict tool execution through raw JSON tool calls
- Approval-based file editing instead of silent direct writes
- Built to stay modular and extensible

## Interface

### Model selection

Switch providers and models from inside the app.

![Model selection](docs/screenshots/models.png)

### Pending edit review

Review proposed file edits before applying them.

![Pending edits](docs/screenshots/pending.png)

## Features

### Core experience

- Local AI chat application
- Modern Textual-based terminal UI
- Classic CLI mode also available
- Provider and model switching
- Multi-step tool use
- Runtime state with working directory and active model config

### Tools

- Filesystem navigation
- File reading and direct file display
- File and text search
- Python AST analysis
- Basic math tools

### Safety and workflow

- Pending edits instead of direct file mutation
- Explicit approve/reject workflow
- Diff-based review before applying changes
- Fail-fast batched tool execution

### Providers

- OpenAI via Responses API
- OpenAI-compatible APIs via Chat Completions
- Local OpenAI-compatible servers such as LM Studio, vLLM, llama.cpp, or similar setups

## Quick start

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

API keys should usually be stored in `.env`, not directly in `providers.toml`.

Copy the example environment file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Then edit both files and add your provider settings and API keys.

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

The provider config also supports fallback env vars and env-based overrides such as:

```toml
api_key_envs = ["OPENAI_API_KEY", "OPENAI_PERSONAL_API_KEY"]
base_url_env = "GWDG_BASE_URL"
default_model_env = "GWDG_DEFAULT_MODEL"
```

### Important note for Textual mode

The current Textual startup flow selects the first configured provider and expects that provider to have a `default_model` configured.

Never commit your `.env` or `providers.toml` files.

## Running the app

### Recommended: Textual UI

```bash
python main_textual.py
```

This is the recommended way to use the app.

### Classic CLI mode

```bash
python main.py
```

Use this if you prefer the simpler command-line workflow.

On Windows, you can also use:

```bash
py main.py
py main_textual.py
```

## Example workflows

### Switch models

Use the model selection UI to switch providers or models without restarting the app.

### Explore code

Ask the agent to inspect files, search through the repository, or analyze Python modules with the built-in filesystem and AST tools.

### Review changes safely

Let the agent propose a file edit, inspect the diff in the pending view, and approve only the changes you want to apply.

## Commands

### Session

- `\help`
- `\reset`
- `\exit`
- `\quit`

### State and navigation

- `\state`
- `\pwd`
- `\cd <path>`

### Models

- `\models`

### Pending edits

- `\pending`
- `\approve <id>`
- `\reject <id>`

### Debug

- `\debug`
- `\debug on`
- `\debug off`

## Tool overview

The agent includes tools for:

- math
- filesystem navigation
- file reading and display
- file and text search
- Python AST analysis
- pending file edits and file creation

Relative paths are resolved against the agent's current working directory. Absolute paths are allowed by design.

## How it works

At a high level:

1. you send a message
2. the model either answers normally or requests tools
3. tools run locally inside the agent runtime
4. tool results are returned to the model
5. the loop continues until the model returns a final answer
6. file changes go through a pending approval workflow instead of being written immediately

## Documentation

- `README.md` — overview, setup, and usage
- `DEVELOPER_REFERENCE.md` — architecture, extension points, and implementation details

## Tests

Install dev dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run the full test suite:

```bash
python -m pytest -q
```

## Security note

This agent intentionally has access to the local filesystem.

There is no filesystem sandbox by design. Relative paths are resolved against the agent's current working directory, and absolute paths are allowed.

The agent can read files and browse directories that the Python process can access. File contents returned by tools such as `read_file` may be sent to the selected LLM provider as part of the conversation context.

Use caution with sensitive data. Never commit API keys, `.env`, `providers.toml`, or private credentials.

## License

MIT License