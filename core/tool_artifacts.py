"""
core/tool_artifacts.py

Helpers for recognizing internal tool-loop artifacts that should not be
shown to the user or persisted as final assistant answers.
"""


def is_internal_tool_artifact(text: str) -> bool:
    """Return True if text looks like an internal tool-loop artifact."""
    stripped = (text or "").strip()
    return (
        stripped.startswith("NATIVE TOOL CALL REQUEST:")
        or stripped.startswith("TOOL RESULT")
        or stripped.startswith('{"action":')
        or stripped.startswith('{"tool_calls":')
    )
