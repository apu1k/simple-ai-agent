# AI Agent

A simple local Python AI agent for experimenting with LLMs, tool usage, filesystem access, and basic agent loops.

The project runs as an interactive command-line app. The agent can use different LLM providers and call local Python tools through JSON-based tool calls.

## Features

- Interactive CLI agent
- Hybrid LLM provider support:
  - GWDG via Chat Completions
  - UPB AI Gateway via Chat Completions
  - Personal OpenAI via Responses API
- Provider and model selection on startup
- JSON-based tool calls
- Multi-step tool usage
- Runtime agent state
- Math tools
- Filesystem navigation
- File reading
- File and text search
- Colored debug output

## Setup

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

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root.

Example:

```env
# GWDG
GWDG_API_KEY=your_gwdg_or_university_key_here
GWDG_BASE_URL=your_gwdg_base_url_here
GWDG_DEFAULT_MODEL=gwdg.qwen3-30b-a3b-instruct-2507

# UPB AI Gateway
UPB_API_KEY=your_upb_key_here
UPB_BASE_URL=https://ai-gateway.uni-paderborn.de/v1
UPB_DEFAULT_MODEL=

# Personal OpenAI
OPENAI_PERSONAL_API_KEY=your_personal_openai_key_here
OPENAI_PERSONAL_DEFAULT_MODEL=gpt-4.1-mini
```

If GWDG and UPB use the same key, you can set the same key for both.

For backwards compatibility, GWDG can also fall back to:

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=your_api_base_url_here
```

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
[1] GWDG
[2] UPB AI Gateway
[3] Personal OpenAI
```

Then chat with the agent:

```text
You: what is 3**8?
AI: 6561
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
- `find_files(pattern, path=".", max_results=100)`
- `search_text(query, path=".", file_pattern="*", max_results=100)`

Relative paths are resolved against the agent's current working directory. Absolute paths are allowed.

## CLI Commands

Reset the conversation context:

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

## How It Works

The model is instructed to respond with JSON only.

Tool call format:

```json
{
  "action": "tool_name",
  "input": {"param": "value"}
}
```

Final answer format:

```json
{
  "final": "answer text"
}
```

The agent parses the model response, executes tools if needed, adds tool results back into the conversation, and continues until a final answer is returned.

## Security Note

This agent intentionally has access to the local filesystem.

It can read files and browse directories that the Python process can access. File contents may be sent to the selected LLM provider as part of the conversation context.

Do not use it with sensitive data unless you understand the risks. Never commit API keys or `.env` files.

## Roadmap

Possible next steps:

- Improve model selection and filtering
- Generate prompts from the tool registry
- Add native tool/function calling
- Add file editing proposals
- Add user approval for file changes
- Add Gemini support
- Add tests

## License

MIT License