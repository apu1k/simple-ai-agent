from .math_tools import add, subtract, multiply, divide, power
from .file_tools import pwd, ls, cd, read_file, find_files, search_text


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
        "description": "List files and directories in a local directory. Relative paths are resolved against the current working directory.",
        "parameters": {
            "path": "Directory path to list. Defaults to '.'. Relative and absolute paths are allowed.",
        },
        "example": {
            "action": "ls",
            "input": {"path": "."},
        },
    },
    "cd": {
        "function": cd,
        "requires_state": True,
        "description": "Change the current local working directory. Relative and absolute paths are allowed.",
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
        "description": "Read a UTF-8 text file from the local filesystem. Relative paths are resolved against the current working directory.",
        "parameters": {
            "path": "File path to read. Relative and absolute paths are allowed.",
        },
        "example": {
            "action": "read_file",
            "input": {"path": "main.py"},
        },
    },
    "find_files": {
        "function": find_files,
        "requires_state": True,
        "description": "Recursively find files by filename pattern.",
        "parameters": {
            "pattern": "Filename pattern to search for, for example '*.py', '*.md', or 'config*'.",
            "path": "Directory to search in. Defaults to '.'. Relative and absolute paths are allowed.",
            "max_results": "Maximum number of results to return. Defaults to 100.",
        },
        "example": {
            "action": "find_files",
            "input": {"pattern": "*.py", "path": ".", "max_results": 100},
        },
    },
    "search_text": {
        "function": search_text,
        "requires_state": True,
        "description": "Recursively search for exact text in files.",
        "parameters": {
            "query": "Exact text to search for.",
            "path": "Directory to search in. Defaults to '.'. Relative and absolute paths are allowed.",
            "file_pattern": "Filename pattern used to limit searched files. Defaults to '*'. Example: '*.py'.",
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
}