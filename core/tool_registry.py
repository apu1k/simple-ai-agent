"""
core/tool_registry.py

Tool registration via @tool decorator + autodiscovery.

Usage in a tool file:
    from core.tool_registry import tool

    @tool(description="Add two numbers.", params={"a": "First", "b": "Second"})
    def add(a, b):
        return a + b

Tool decorators register discovered tools in a source registry. Agent runtimes
must derive an explicit capability registry from that source before execution.

No I/O, no imports from this project beyond this file.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from dataclasses import dataclass
from typing import Callable


# ---------------------------------------------------------------------------
# ToolSpec — what the registry stores per tool
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSpec:
    name: str
    function: Callable
    description: str
    # Values may be a plain description or an explicit JSON Schema fragment.
    parameters: dict[str, str | dict]
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

    def select(self, names: list[str] | tuple[str, ...], *, strict: bool = True) -> "ToolRegistry":
        """Return an independent registry containing only the named tools.

        ``strict=True`` makes capability profiles fail closed when a configured
        tool was not discovered, rather than silently granting an incomplete or
        unexpected set of capabilities.
        """
        selected = ToolRegistry()
        missing: list[str] = []
        for name in names:
            spec = self.get(name)
            if spec is None:
                missing.append(name)
                continue
            selected.register(spec)

        if strict and missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"Unknown tool(s) in capability profile: {missing_list}")
        return selected

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
    params: dict[str, str | dict] | None = None,
    requires_state: bool = False,
    example: dict | None = None,
):
    """
    Decorator that registers a function as an agent tool.

    Args:
        description:     What the tool does (shown in the system prompt).
        params:          Mapping of parameter name → description or JSON Schema.
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
