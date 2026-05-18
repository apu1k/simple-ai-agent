"""
tools/fs/analyze.py

Python AST analysis tools: analyze_python_file, analyze_python_files.
"""

import ast
from pathlib import Path

from tools._base import tool
from tools.fs._shared import (
    MAX_ANALYZE_FILES,
    MAX_FILE_SIZE_BYTES,
    build_display_path,
    resolve_path,
    should_skip_path,
)


# ---------------------------------------------------------------------------
# AST helpers (internal)
# ---------------------------------------------------------------------------

ASSIGNMENT_NODES = (ast.Assign, ast.AnnAssign, ast.AugAssign)


def _safe_unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def _format_alias(alias) -> str:
    return f"{alias.name} as {alias.asname}" if alias.asname else alias.name


def _format_import(node) -> str | None:
    if isinstance(node, ast.Import):
        return "import " + ", ".join(_format_alias(a) for a in node.names)
    if isinstance(node, ast.ImportFrom):
        prefix = "." * node.level
        module = f"{prefix}{node.module or ''}" or "."
        names = ", ".join(_format_alias(a) for a in node.names)
        return f"from {module} import {names}"
    return None


def _line_range(node) -> str:
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if start is None:
        return "line unknown"
    if end is not None and end != start:
        return f"lines {start}-{end}"
    return f"line {start}"


def _collect_target_names(target) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names = []
        for el in target.elts:
            names.extend(_collect_target_names(el))
        return names
    if isinstance(target, ast.Starred):
        return _collect_target_names(target.value)
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        return [_safe_unparse(target)]
    return []


def _collect_assignment_names(node) -> list[str]:
    names = []
    if isinstance(node, ast.Assign):
        for t in node.targets:
            names.extend(_collect_target_names(t))
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        names.extend(_collect_target_names(node.target))
    return list(dict.fromkeys(names))


def _format_assignment(node) -> str | None:
    names = _collect_assignment_names(node)
    if not names:
        return None
    return f"{', '.join(names)}, {_line_range(node)}"


def _format_function_signature(node) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:
        args = "..."
    ret = f" -> {_safe_unparse(node.returns)}" if node.returns is not None else ""
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}({args}){ret}"


def _format_function_summary(node) -> str:
    return f"{_format_function_signature(node)}, {_line_range(node)}"


def _format_class_bases(node) -> list[str]:
    bases = [_safe_unparse(b) for b in node.bases]
    for kw in node.keywords:
        if kw.arg is None:
            bases.append(f"**{_safe_unparse(kw.value)}")
        else:
            bases.append(f"{kw.arg}={_safe_unparse(kw.value)}")
    return bases


def _module_docstring_line(tree) -> int | None:
    if not tree.body:
        return None
    first = tree.body[0]
    if not isinstance(first, ast.Expr):
        return None
    if isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return getattr(first, "lineno", None)
    return None


def _analyze_tree(state, file_path: Path, source: str, tree) -> str:
    display_path = build_display_path(state, file_path)
    lines = [f"File: {display_path}", f"Lines: {len(source.splitlines())}"]

    # Docstring
    ds_line = _module_docstring_line(tree)
    lines += ["", "Module docstring:"]
    lines.append(f"- present, line {ds_line}" if ds_line else "- none")

    # Imports
    imports = [
        f"{_format_import(n)}, {_line_range(n)}"
        for n in tree.body
        if _format_import(n)
    ]
    lines += ["", "Imports:"]
    lines.extend(f"- {i}" for i in imports) if imports else lines.append("- none")

    # Top-level assignments
    assignments = [
        _format_assignment(n)
        for n in tree.body
        if isinstance(n, ASSIGNMENT_NODES) and _format_assignment(n)
    ]
    lines += ["", "Top-level constants/assignments:"]
    lines.extend(f"- {a}" for a in assignments) if assignments else lines.append("- none")

    # Top-level functions
    functions = [
        _format_function_summary(n)
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    lines += ["", "Top-level functions:"]
    lines.extend(f"- {f}" for f in functions) if functions else lines.append("- none")

    # Classes
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    lines += ["", "Classes:"]
    if not classes:
        lines.append("- none")
        return "\n".join(lines)

    for cls in classes:
        lines.append(f"- {cls.name}, {_line_range(cls)}")
        bases = _format_class_bases(cls)
        lines.append(f"  Bases: {', '.join(bases)}" if bases else "  Bases: none")

        cls_assignments = [
            _format_assignment(c)
            for c in cls.body
            if isinstance(c, ASSIGNMENT_NODES) and _format_assignment(c)
        ]
        lines.append("  Class variables:")
        lines.extend(f"  - {a}" for a in cls_assignments) if cls_assignments else lines.append("  - none")

        methods = [
            _format_function_summary(c)
            for c in cls.body
            if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        lines.append("  Methods:")
        lines.extend(f"  - {m}" for m in methods) if methods else lines.append("  - none")

    return "\n".join(lines)


def _analyze_file_path(state, file_path: Path) -> str:
    if not file_path.exists():
        return f"Error: File does not exist: {file_path}"
    if not file_path.is_file():
        return f"Error: Path is not a file: {file_path}"
    if file_path.suffix.lower() != ".py":
        return f"Error: Path is not a Python file: {file_path}"
    if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
        return f"Error: File is too large to analyze: {file_path}"

    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: File is not valid UTF-8: {file_path}"
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error: Failed to read file '{file_path}': {e}"

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        parts = []
        if e.lineno is not None:
            parts.append(f"line {e.lineno}")
        if e.offset is not None:
            parts.append(f"column {e.offset}")
        location = ", ".join(parts) or "unknown location"
        display_path = build_display_path(state, file_path)
        return "\n".join([f"File: {display_path}", "", "Syntax error:", f"- {location}: {e.msg}"])

    return _analyze_tree(state, file_path, source, tree)


# ---------------------------------------------------------------------------
# Registered tools
# ---------------------------------------------------------------------------

@tool(
    description=(
        "Analyze a Python file using the AST and return structured information: "
        "imports, docstring status, top-level assignments, functions, classes, "
        "class variables, and methods — without returning code bodies."
    ),
    params={"path": "Python file path to analyze."},
    requires_state=True,
)
def analyze_python_file(state, path: str) -> str:
    file_path = resolve_path(state, path)
    try:
        return _analyze_file_path(state, file_path)
    except PermissionError:
        return f"Error: Permission denied: {file_path}"
    except Exception as e:
        return f"Error: Failed to analyze '{file_path}': {e}"


@tool(
    description=(
        "Recursively analyze matching Python files using the AST and return "
        "structured information without returning code bodies."
    ),
    params={
        "pattern": "Filename pattern. Defaults to '*.py'.",
        "path": "Directory to search in. Defaults to '.'.",
        "max_files": "Maximum number of files to analyze.",
    },
    requires_state=True,
)
def analyze_python_files(state, pattern="*.py", path=".", max_files=MAX_ANALYZE_FILES) -> str:
    search_root = resolve_path(state, path)

    try:
        max_files = int(max_files)
        if max_files < 1:
            return "Error: max_files must be at least 1."

        effective_max = min(max_files, MAX_ANALYZE_FILES)

        if not search_root.exists():
            return f"Error: Path does not exist: {search_root}"
        if not search_root.is_dir():
            return f"Error: Path is not a directory: {search_root}"

        candidates = sorted(search_root.rglob(pattern), key=lambda p: str(p).lower())
        analyzed = []
        skipped_non_python = 0
        limit_reached = False

        for file_path in candidates:
            if should_skip_path(file_path) or not file_path.is_file():
                continue
            if file_path.suffix.lower() != ".py":
                skipped_non_python += 1
                continue
            if len(analyzed) >= effective_max:
                limit_reached = True
                break
            analyzed.append(_analyze_file_path(state, file_path))

        if not analyzed:
            return f"No Python files were analyzed for pattern '{pattern}' in {search_root}."

        result = [f"Analyzed {len(analyzed)} Python file(s) matching '{pattern}' in {search_root}."]
        if skipped_non_python:
            result.append(f"Skipped non-Python files: {skipped_non_python}.")
        if limit_reached:
            result.append(f"Result limit reached: analyzed at most {effective_max} file(s).")
        if max_files > MAX_ANALYZE_FILES:
            result.append(f"Requested max_files={max_files} exceeds hard limit {MAX_ANALYZE_FILES}.")

        result += ["", "---", "", "\n\n---\n\n".join(analyzed)]
        return "\n".join(result)

    except ValueError:
        return "Error: max_files must be an integer."
    except PermissionError:
        return f"Error: Permission denied while analyzing files in: {search_root}"
    except Exception as e:
        return f"Error: Failed to analyze Python files in '{search_root}': {e}"
