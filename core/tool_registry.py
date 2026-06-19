"""
core/tool_registry.py

Tool registration via @tool decorator + autodiscovery.

Usage in a tool file:
    from core.tool_registry import tool

    @tool(description="Add two numbers.", params={"a": "First", "b": "Second"})
    def add(a, b):
        return a + b

The registry is a singleton. Autodiscovery imports all modules under `tools/`
so their decorators fire. runtime/loop.py calls autodiscover() once at startup.

No I/O, no imports from this project beyond this file.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# ToolSpec — what the registry stores per tool
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSpec:
    name: str
    function: Callable
    description: str
    parameters: dict[str, str]          # param_name → description
    requires_state: bool = False
    example: dict | None = None


# ---------------------------------------------------------------------------
# Registry — singleton
# ---------------------------------------------------------------------------

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool '{spec.name}' is already registered.")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self) -> dict[str, ToolSpec]:
        return dict(self._tools)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools


# The global singleton every tool module registers into.
registry = ToolRegistry()


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------

def tool(
    *,
    description: str,
    params: dict[str, str] | None = None,
    requires_state: bool = False,
    example: dict | None = None,
):
    """
    Decorator that registers a function as an agent tool.

    Args:
        description:     What the tool does (shown in the system prompt).
        params:          Mapping of parameter name → description.
        requires_state:  If True, AgentState is injected as the first argument.
        example:         Optional example tool call dict for the system prompt.

    Example:
        @tool(
            description="Get the current price of a stock.",
            params={"ticker": "Stock ticker symbol, e.g. AAPL"},
        )
        def get_price(ticker: str) -> str:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        spec = ToolSpec(
            name=fn.__name__,
            function=fn,
            description=description,
            parameters=params or {},
            requires_state=requires_state,
            example=example,
        )
        registry.register(spec)
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Autodiscovery
# ---------------------------------------------------------------------------

def autodiscover(package_name: str = "tools") -> None:
    """
    Walk the given package and import every module so @tool decorators fire.

    Call once at startup in runtime/loop.py:
        from core.tool_registry import autodiscover
        autodiscover()
    """
    # Guard: skip autodiscovery when running tests to avoid
    # pkgutil.walk_packages() hanging in some environments.
    if "pytest" in sys.modules:
        return

    try:
        package = importlib.import_module(package_name)
    except ImportError as e:
        raise ImportError(f"Could not import tools package '{package_name}': {e}") from e

    for finder, module_name, is_pkg in pkgutil.walk_packages(
        package.__path__,
        prefix=package.__name__ + ".",
    ):
        # Skip private/internal modules (prefixed with _)
        parts = module_name.split(".")
        if any(part.startswith("_") for part in parts[1:]):
            continue

        try:
            importlib.import_module(module_name)
        except Exception as e:
            # Don't crash startup if one tool module fails to import.
            # The error will surface when the tool is called.
            import warnings
            warnings.warn(f"Could not import tool module '{module_name}': {e}")
