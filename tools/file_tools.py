from pathlib import Path


def resolve_path(state, path="."):
    target_path = Path(path).expanduser()

    if not target_path.is_absolute():
        target_path = state.cwd / target_path

    return target_path.resolve()


def pwd(state):
    return str(state.cwd)


def ls(state, path="."):
    directory_path = resolve_path(state, path)

    try:
        if not directory_path.exists():
            return f"Error: Path does not exist: {directory_path}"

        if not directory_path.is_dir():
            return f"Error: Path is not a directory: {directory_path}"

        entries = sorted(
            directory_path.iterdir(),
            key=lambda entry: (not entry.is_dir(), entry.name.lower())
        )

        if not entries:
            return f"Directory is empty: {directory_path}"

        lines = [f"Directory: {directory_path}", ""]

        for entry in entries:
            if entry.is_dir():
                lines.append(f"[DIR]  {entry.name}")
            elif entry.is_file():
                lines.append(f"[FILE] {entry.name}")
            else:
                lines.append(f"[OTHER] {entry.name}")

        return "\n".join(lines)

    except PermissionError:
        return f"Error: Permission denied: {directory_path}"
    except Exception as e:
        return f"Error: Failed to list directory '{directory_path}': {e}"


def cd(state, path):
    directory_path = resolve_path(state, path)

    try:
        if not directory_path.exists():
            return f"Error: Path does not exist: {directory_path}"

        if not directory_path.is_dir():
            return f"Error: Path is not a directory: {directory_path}"

        state.cwd = directory_path
        return f"Changed directory to: {state.cwd}"

    except PermissionError:
        return f"Error: Permission denied: {directory_path}"
    except Exception as e:
        return f"Error: Failed to change directory to '{directory_path}': {e}"


def read_file(state, path):
    file_path = resolve_path(state, path)

    try:
        if not file_path.exists():
            return f"Error: File does not exist: {file_path}"

        if not file_path.is_file():
            return f"Error: Path is not a file: {file_path}"

        with file_path.open("r", encoding="utf-8") as f:
            return f.read()

    except UnicodeDecodeError:
        return f"Error: File is not a valid UTF-8 text file: {file_path}"
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error: Failed to read file '{file_path}': {e}"