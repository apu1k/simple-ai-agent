from pathlib import Path


def read_file(path):
    file_path = Path(path)

    try:
        if not file_path.exists():
            return f"Error: File does not exist: {path}"

        if not file_path.is_file():
            return f"Error: Path is not a file: {path}"

        with file_path.open("r", encoding="utf-8") as f:
            return f.read()

    except UnicodeDecodeError:
        return f"Error: File is not a valid UTF-8 text file: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error: Failed to read file '{path}': {e}"