from .math_tools import add, subtract, multiply, divide, power
from .file_tools import (
    pwd,
    ls,
    cd,
    read_file,
    analyze_python_file,
    analyze_python_files,
    show_file,
    find_files,
    show_files,
    search_text,
    propose_file_edit
)

TOOLS = {
    "add": {
        "function": add,
        "requires_state": False,
        "description": "Add two numbers.",
        "parameters": {
            "a": "First number.",
            "b": "Second number.",
        },
        "example": {
            "action": "add",
            "input": {"a": 2, "b": 3},
        },
    },
    "subtract": {
        "function": subtract,
        "requires_state": False,
        "description": "Subtract b from a.",
        "parameters": {
            "a": "Number to subtract from.",
            "b": "Number to subtract.",
        },
        "example": {
            "action": "subtract",
            "input": {"a": 10, "b": 4},
        },
    },
    "multiply": {
        "function": multiply,
        "requires_state": False,
        "description": "Multiply two numbers.",
        "parameters": {
            "a": "First number.",
            "b": "Second number.",
        },
        "example": {
            "action": "multiply",
            "input": {"a": 6, "b": 7},
        },
    },
    "divide": {
        "function": divide,
        "requires_state": False,
        "description": "Divide a by b.",
        "parameters": {
            "a": "Dividend.",
            "b": "Divisor.",
        },
        "example": {
            "action": "divide",
            "input": {"a": 10, "b": 2},
        },
    },
    "power": {
        "function": power,
        "requires_state": False,
        "description": "Raise a to the power of b.",
        "parameters": {
            "a": "Base number.",
            "b": "Exponent.",
        },
        "example": {
            "action": "power",
            "input": {"a": 3, "b": 4},
        },
    },
    "pwd": {
        "function": pwd,
        "requires_state": True,
        "description": "Show the current local working directory of the agent.",
        "parameters": {},
        "example": {
            "action": "pwd",
            "input": {},
        },
    },
    "ls": {
        "function": ls,
        "requires_state": True,
        "description": (
            "List files and directories in a local directory. "
            "Relative paths are resolved against the current working directory."
        ),
        "parameters": {
            "path": (
                "Directory path to list. Defaults to '.'. "
                "Relative and absolute paths are allowed."
            ),
        },
        "example": {
            "action": "ls",
            "input": {"path": "."},
        },
    },
    "cd": {
        "function": cd,
        "requires_state": True,
        "description": (
            "Change the current local working directory. "
            "Relative and absolute paths are allowed."
        ),
        "parameters": {
            "path": "Directory path to change into.",
        },
        "example": {
            "action": "cd",
            "input": {"path": "tools"},
        },
    },
    "read_file": {
        "function": read_file,
        "requires_state": True,
        "description": (
            "Read a UTF-8 text file from the local filesystem and return its contents "
            "to the model for analysis. Use this when you need to inspect, reason about, "
            "summarize, or modify file contents."
        ),
        "parameters": {
            "path": (
                "File path to read. Relative and absolute paths are allowed."
            ),
        },
        "example": {
            "action": "read_file",
            "input": {"path": "main.py"},
        },
    },
    "analyze_python_file": {
        "function": analyze_python_file,
        "requires_state": True,
        "description": (
            "Analyze a Python file using the ast module and return structured information "
            "such as imports, module docstring status, top-level assignments, functions, "
            "classes, class variables, and methods without returning code bodies."
        ),
        "parameters": {
            "path": (
                "Python file path to analyze. Relative and absolute paths are allowed."
            ),
        },
    },
    "analyze_python_files": {
        "function": analyze_python_files,
        "requires_state": True,
        "description": (
            "Recursively analyze matching Python files using the ast module and return "
            "structured information without returning code bodies."
        ),
        "parameters": {
            "pattern": (
                "Filename pattern to search for. Defaults to '*.py'."
            ),
            "path": (
                "Directory to search in. Defaults to '.'. "
                "Relative and absolute paths are allowed."
            ),
            "max_files": (
                "Maximum number of Python files to analyze. "
                "A hard safety limit is still enforced."
            ),
        },
    },
    "show_file": {
        "function": show_file,
        "requires_state": True,
        "description": (
            "Display a UTF-8 text file, or a line range from a file, directly to the user "
            "in the CLI. The file contents are not returned to the model; the model receives "
            "only a short confirmation. Use this when the user asks to see a file."
            "Do not use this tool unless the user explicitly requests a file to be shown,"
            "because the tool provides no useful information to the agent itself."
            "dont call this during code analysis task."
        ),
        "parameters": {
            "path": (
                "File path to display. Relative and absolute paths are allowed."
            ),
            "start_line": (
                "Optional 1-based start line for displaying only part of the file."
            ),
            "end_line": (
                "Optional 1-based inclusive end line for displaying only part of the file."
            ),
        },
        "example": {
            "action": "show_file",
            "input": {"path": "main.py"},
        },
    },
    "find_files": {
        "function": find_files,
        "requires_state": True,
        "description": "Recursively find files by filename pattern.",
        "parameters": {
            "pattern": (
                "Filename pattern to search for, for example '*.py', '*.md', or 'config*'."
            ),
            "path": (
                "Directory to search in. Defaults to '.'. "
                "Relative and absolute paths are allowed."
            ),
            "max_results": "Maximum number of results to return. Defaults to 100.",
        },
        "example": {
            "action": "find_files",
            "input": {"pattern": "*.py", "path": ".", "max_results": 100},
        },
    },
    "show_files": {
        "function": show_files,
        "requires_state": True,
        "description": (
            "Recursively find matching UTF-8 text files and display their complete contents "
            "directly to the user in the CLI. The file contents are not returned to the model; "
            "the model receives only a short confirmation and a list of displayed files. "
            "Use this when the user asks to receive or see many files, for example: show all Python files."
            "Do not use this tool unless the user explicitly requests a file to be shown,"
            "because the tool provides no useful information to the agent itself."
            "dont call this during code analysis task."
        ),
        "parameters": {
            "pattern": (
                "Filename pattern to display, for example '*.py', '*.md', or 'config*'."
            ),
            "path": (
                "Directory to search in. Defaults to '.'. "
                "Relative and absolute paths are allowed."
            ),
            "max_files": (
                "Maximum number of files to display. Defaults to the tool limit. "
                "A hard safety limit is still enforced."
            ),
        },
        "example": {
            "action": "show_files",
            "input": {"pattern": "*.py", "path": ".", "max_files": 30},
        },
    },
    "search_text": {
        "function": search_text,
        "requires_state": True,
        "description": "Recursively search for exact text in files.",
        "parameters": {
            "query": "Exact text to search for.",
            "path": (
                "Directory to search in. Defaults to '.'. "
                "Relative and absolute paths are allowed."
            ),
            "file_pattern": (
                "Filename pattern used to limit searched files. "
                "Defaults to '*'. Example: '*.py'."
            ),
            "max_results": "Maximum number of matches to return. Defaults to 100.",
        },
        "example": {
            "action": "search_text",
            "input": {
                "query": "def parse_action",
                "path": ".",
                "file_pattern": "*.py",
                "max_results": 100,
            },
        },
    },
    "propose_file_edit": {
        "function": propose_file_edit,
        "requires_state": True,
        "description": (
            "Propose exact-match file edits without directly modifying the file. "
            "The edit becomes pending until user approval."
        ),
        "parameters": {
            "path": "Path to the file.",
            "edits": (
                "List of exact-match edits. "
                "Each edit must contain 'find' and 'replace'."
            ),
        },
        "example": {
            "action": "propose_file_edit",
            "input": {
                "path": "main.py",
                "edits": [
                    {
                        "find": "print('hello')",
                        "replace": "print('hello world')",
                    }
                ],
            },
        },
    },
}