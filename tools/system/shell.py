"""
tools/system/shell.py

Safe shell command execution tool.
Uses subprocess.run(..., shell=False) so shell metacharacters are impossible.
"""

import json
import os
import shutil
import subprocess

from tools._base import tool

MAX_TIMEOUT = 30
MAX_OUTPUT_BYTES = 50_000

if os.name == "nt":
    STANDALONE_COMMANDS = frozenset([
        "python", "python3",
        "pip", "pip3",
        "ruff", "mypy", "pytest",
        "where",
    ])
else:
    STANDALONE_COMMANDS = frozenset([
        "python", "python3",
        "pip", "pip3",
        "ruff", "mypy", "pytest",
        "cat", "head", "tail", "wc", "which",
        "echo", "env", "date", "df", "free",
    ])

COMMANDS_WITH_SUBCOMMANDS = {
    "git": frozenset(["status", "diff", "log", "show"]),
}

ARGS_ERROR = "Error: 'args' must be a list of strings or a JSON-encoded list of strings."


def _build_shell_tool_description() -> str:
    """Build the shell tool description from the active command whitelist.

    The whitelist is OS-dependent, so generate this at module import time from
    the same constants used by validation. This keeps the model-facing tool
    description in sync with the actual allowed commands.
    """
    system_name = "Windows" if os.name == "nt" else "Linux/macOS"
    standalone = ", ".join(sorted(STANDALONE_COMMANDS)) or "none"

    subcommand_parts = []
    for command, subcommands in sorted(COMMANDS_WITH_SUBCOMMANDS.items()):
        allowed_subcommands = ", ".join(sorted(subcommands)) or "none"
        subcommand_parts.append(f"{command}: {allowed_subcommands}")
    subcommands_text = "; ".join(subcommand_parts) or "none"

    return (
        f"Execute a safe, whitelisted shell command on {system_name}. "
        f"Allowed standalone commands: {standalone}. "
        f"Allowed command subcommands: {subcommands_text}. "
        "Runs in the current working directory with no shell parsing. "
        "Arguments must be passed as a list of strings. "
        "A JSON-encoded list string is also accepted for compatibility. "
        f"Output is limited to {MAX_OUTPUT_BYTES} bytes. "
        f"Timeout must be 1-{MAX_TIMEOUT} seconds."
    )


def _normalize_args(args) -> list[str] | str:
    """Return normalized args, or an error string.

    The tool schema expects args as a native JSON array/list of strings.
    Some models occasionally pass a JSON-encoded list string instead, e.g.
    '["status", "--short"]'. Accept that compatibility form, but do
    not split arbitrary shell-like strings because execution intentionally uses
    shell=False.
    """
    if args is None:
        return []

    if isinstance(args, list) and all(isinstance(a, str) for a in args):
        return args

    if isinstance(args, str):
        try:
            decoded = json.loads(args)
        except json.JSONDecodeError:
            return ARGS_ERROR
        if isinstance(decoded, list) and all(isinstance(a, str) for a in decoded):
            return decoded

    return ARGS_ERROR


@tool(
    description=_build_shell_tool_description(),
    params={
        "command": "The command to run (e.g. 'git', 'ruff', 'pytest').",
        "args": "Arguments to pass as a list of strings. A JSON-encoded list string is also accepted for compatibility.",
        "timeout": "Maximum execution time in seconds (1-30). Defaults to 30.",
    },
    requires_state=True,
    example={
        "action": "run_shell_command",
        "input": {"command": "git", "args": ["status"], "timeout": 10},
    },
)
def run_shell_command(state, command: str, args: list[str] = None, timeout: int = 30) -> str:
    if not isinstance(command, str) or not command.strip():
        return "Error: 'command' must be a non-empty string."

    normalized_args = _normalize_args(args)
    if isinstance(normalized_args, str):
        return normalized_args
    args = normalized_args

    cmd_base = command.strip()

    # 1. Validate against whitelist
    if cmd_base in COMMANDS_WITH_SUBCOMMANDS:
        # e.g. 'git status' -> 'status'
        subcommand = args[0] if args else None
        if subcommand is None:
            allowed = ", ".join(sorted(COMMANDS_WITH_SUBCOMMANDS[cmd_base]))
            return f"Error: Command '{cmd_base}' requires a subcommand. Allowed: {allowed}"
        if subcommand not in COMMANDS_WITH_SUBCOMMANDS[cmd_base]:
            allowed = ", ".join(sorted(COMMANDS_WITH_SUBCOMMANDS[cmd_base]))
            return f"Error: Subcommand '{subcommand}' not allowed for '{cmd_base}'. Allowed: {allowed}"
    elif cmd_base not in STANDALONE_COMMANDS:
        all_allowed = sorted(STANDALONE_COMMANDS)
        all_allowed.extend(list(COMMANDS_WITH_SUBCOMMANDS.keys()))
        return f"Error: Command '{cmd_base}' not whitelisted. Allowed: {', '.join(all_allowed)}"

    # 2. Validate timeout
    try:
        timeout = int(timeout)
        if not (1 <= timeout <= MAX_TIMEOUT):
            return f"Error: Timeout must be between 1 and {MAX_TIMEOUT} seconds."
    except (TypeError, ValueError):
        return "Error: Timeout must be an integer."

    # 3. Execute
    display_command = [cmd_base] + args

    executable = shutil.which(cmd_base)
    if executable is None:
        return f"Error: Command '{cmd_base}' not found in PATH."

    run_command = [executable] + args

    # Prevent interactive prompts and pagers from hanging the tool.
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_ASKPASS", "")
    env.setdefault("SSH_ASKPASS", "")
    env.setdefault("PAGER", "")
    env.setdefault("GIT_PAGER", "")

    if cmd_base == "git":
        # Git may invoke a pager for commands like log/show. --no-pager keeps
        # output connected directly to stdout/stderr and avoids interactive hangs.
        run_command = [executable, "--no-pager"] + args

    try:
        result = subprocess.run(
            run_command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=False,
            timeout=timeout,
            cwd=str(state.cwd),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Error: Command '{' '.join(display_command)}' timed out after {timeout}s."
    except FileNotFoundError:
        return f"Error: Command '{cmd_base}' not found in PATH."
    except PermissionError:
        return f"Error: Permission denied running '{cmd_base}'."
    except Exception as e:
        return f"Error: Failed to run command: {e}"

    # 4. Combine and check size
    output_parts = []
    if result.stdout:
        output_parts.append(result.stdout)
    if result.stderr:
        if output_parts:
            output_parts.append(b"\n")
        output_parts.append(result.stderr)

    raw_output_bytes = b"".join(output_parts)
    raw_bytes = len(raw_output_bytes)

    if raw_bytes > MAX_OUTPUT_BYTES:
        shown_bytes = raw_output_bytes[:MAX_OUTPUT_BYTES]
        truncated = True
    else:
        shown_bytes = raw_output_bytes
        truncated = False

    returned_output = shown_bytes.decode("utf-8", errors="replace")
    if truncated:
        returned_output += "\n...\n[Output truncated: exceeded 50KB limit.]"

    returned_bytes = len(shown_bytes)

    # 5. Format result
    lines = [
        f"Command: {' '.join(display_command)}",
        f"Return code: {result.returncode}",
    ]
    if returned_output:
        lines.append(f"Raw size: {raw_bytes} bytes | Returned size: {returned_bytes} bytes")
        lines.append("Output:")
        lines.append(returned_output)
    return "\n".join(lines)
