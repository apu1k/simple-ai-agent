# AI Agent

A simple Python-based AI agent for experimenting with LLMs, tool usage, and basic agent loops.

The project currently runs as an interactive command-line application. The agent communicates with an OpenAI-compatible LLM API and can call predefined Python tools.

## Features

- OpenAI-compatible LLM client
- JSON-based tool calls
- Multi-step tool usage
- Basic math tools
- File reading tool
- Colored console output for debugging

## Setup

Create a virtual environment:

```bash
python -m venv .venv
```

Activate the virtual environment:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root.

Example:

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=your_api_base_url_here
```

The model name is currently configured in `config.py`.

## Usage

Start the agent:

```bash
python main.py
```

or on Windows:

```bash
py main.py
```

After startup, you can chat with the agent in the terminal:

```text
Du: what is 3**8?
AI: 6561
```

## Available Tools

The agent currently has access to the following tools:

- `add(a, b)`
- `subtract(a, b)`
- `multiply(a, b)`
- `divide(a, b)`
- `power(a, b)`
- `read_file(path)`

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

The model is instructed to respond with JSON.

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

The agent parses the model response, executes the requested tool if needed, adds the tool result back into the conversation, and continues until a final answer is returned.

## Security Note

The `read_file(path)` tool can read local files from the machine running the agent.  
This project is intended for local experimentation and should not be exposed as a public service without additional security checks.

API keys and local configuration files should never be committed to the repository.

## License

This project is licensed under the MIT License.