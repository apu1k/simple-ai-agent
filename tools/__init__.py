from .math_tools import add, subtract, multiply, divide, power
from .file_tools import pwd, ls, cd, read_file, find_files, search_text


TOOLS = {
    "add": {
        "function": add,
        "requires_state": False,
    },
    "subtract": {
        "function": subtract,
        "requires_state": False,
    },
    "multiply": {
        "function": multiply,
        "requires_state": False,
    },
    "divide": {
        "function": divide,
        "requires_state": False,
    },
    "power": {
        "function": power,
        "requires_state": False,
    },
    "pwd": {
        "function": pwd,
        "requires_state": True,
    },
    "ls": {
        "function": ls,
        "requires_state": True,
    },
    "cd": {
        "function": cd,
        "requires_state": True,
    },
    "read_file": {
        "function": read_file,
        "requires_state": True,
    },
    "find_files": {
        "function": find_files,
        "requires_state": True,
    },
    "search_text": {
        "function": search_text,
        "requires_state": True,
    },
}