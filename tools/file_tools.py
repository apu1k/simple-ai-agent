from pathlib import Path


def resolve_path(state, path):
    file_path = Path(path).expanduser()

    if not file_path.is_absolute():
        file_path = state.cwd / file_path

    return file_path.resolve()


def pwd(state):
    return str(state.cwd)


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