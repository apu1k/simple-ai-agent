import os

from tools.system.shell import run_shell_command


class _State:
    def __init__(self, cwd):
        self.cwd = cwd


def test_shell_rejects_empty_command(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "   ")
    assert out == "Error: 'command' must be a non-empty string."


def test_shell_rejects_non_list_args(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "python", args="-V")
    assert out == "Error: 'args' must be a list of strings."


def test_shell_rejects_non_string_arg_item(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "python", args=["-V", 1])
    assert out == "Error: 'args' must be a list of strings."


def test_shell_rejects_non_whitelisted_command(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "not_a_real_allowed_cmd")
    assert out.startswith("Error: Command 'not_a_real_allowed_cmd' not whitelisted.")


def test_shell_git_requires_subcommand(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "git", args=[])
    assert out.startswith("Error: Command 'git' requires a subcommand.")


def test_shell_git_rejects_subcommand(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "git", args=["clone"])
    assert out.startswith("Error: Subcommand 'clone' not allowed for 'git'.")


def test_shell_rejects_invalid_timeout(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "python", args=["-V"], timeout=0)
    assert out == "Error: Timeout must be between 1 and 30 seconds."


def test_shell_accepts_timeout_as_string_int(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "python", args=["-V"], timeout="5")
    assert "Command: python -V" in out
    assert "Return code: 0" in out


def test_shell_handles_missing_executable(tmp_path, monkeypatch):
    state = _State(tmp_path)

    monkeypatch.setattr("tools.system.shell.shutil.which", lambda _: None)
    out = run_shell_command(state, "python", args=["-V"])
    assert out == "Error: Command 'python' not found in PATH."


def test_shell_success_python_version(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "python", args=["-V"], timeout=5)
    assert "Command: python -V" in out
    assert "Return code: 0" in out


def test_shell_truncates_large_output(tmp_path):
    state = _State(tmp_path)

    py = "import sys; sys.stdout.write('a'*60000)"
    out = run_shell_command(state, "python", args=["-c", py], timeout=5)

    assert "Return code: 0" in out
    assert "Raw size:" in out
    assert "Returned size:" in out
    assert "[Output truncated: exceeded 50KB limit.]" in out


def test_shell_uses_state_cwd(tmp_path):
    state = _State(tmp_path)

    py = "import os; print(os.getcwd())"
    out = run_shell_command(state, "python", args=["-c", py], timeout=5)

    assert "Return code: 0" in out
    assert str(tmp_path) in out


def test_shell_windows_no_echo_in_whitelist_if_nt(tmp_path):
    state = _State(tmp_path)
    out = run_shell_command(state, "echo", args=["hi"])
    if os.name == "nt":
        assert out.startswith("Error: Command 'echo' not whitelisted.")
    else:
        # On non-Windows, echo is allowed in whitelist.
        assert "Command: echo hi" in out
