"""
tools/math/arithmetic.py

Basic arithmetic tools.
"""

from tools._base import tool


@tool(
    description="Add two numbers.",
    params={"a": "First number.", "b": "Second number."},
    example={"action": "add", "input": {"a": 2, "b": 3}},
)
def add(a, b):
    return a + b


@tool(
    description="Subtract b from a.",
    params={"a": "Number to subtract from.", "b": "Number to subtract."},
    example={"action": "subtract", "input": {"a": 10, "b": 4}},
)
def subtract(a, b):
    return a - b


@tool(
    description="Multiply two numbers.",
    params={"a": "First number.", "b": "Second number."},
    example={"action": "multiply", "input": {"a": 6, "b": 7}},
)
def multiply(a, b):
    return a * b


@tool(
    description="Divide a by b.",
    params={"a": "Dividend.", "b": "Divisor."},
    example={"action": "divide", "input": {"a": 10, "b": 2}},
)
def divide(a, b):
    if b == 0:
        return "Error: Division by zero."
    return a / b


@tool(
    description="Raise a to the power of b.",
    params={"a": "Base number.", "b": "Exponent."},
    example={"action": "power", "input": {"a": 3, "b": 4}},
)
def power(a, b):
    return a ** b
