"""Tests for explicit, fail-closed agent capability profiles."""

import pytest

from core.tool_registry import ToolRegistry, ToolSpec
from runtime.prompt import build_system_prompt
from runtime.tool_profiles import (
    AgentProfile,
    build_profile_registry,
    profile_tool_names,
)


def _source_registry() -> ToolRegistry:
    source = ToolRegistry()
    names = {
        name
        for profile in AgentProfile
        for name in profile_tool_names(profile)
    }
    for name in sorted(names):
        source.register(
            ToolSpec(
                name=name,
                function=lambda: None,
                description=f"Description for {name}",
                parameters={},
            )
        )
    return source


def test_registry_select_returns_independent_allowlist():
    source = _source_registry()

    selected = source.select(("pwd", "read_file"))

    assert selected.names() == ["pwd", "read_file"]
    assert "search_text" not in selected
    assert len(source.names()) > len(selected.names())


def test_registry_select_fails_closed_for_unknown_tool():
    with pytest.raises(ValueError, match="unknown_tool"):
        _source_registry().select(("pwd", "unknown_tool"))


def test_worker_profiles_do_not_receive_head_only_or_mutation_tools():
    source = _source_registry()
    read_only = build_profile_registry(
        AgentProfile.READ_ONLY_WORKER,
        source_registry=source,
    )
    reviewer = build_profile_registry(
        AgentProfile.REVIEW_WORKER,
        source_registry=source,
    )

    for restricted in (read_only, reviewer):
        assert "propose_file_edit" not in restricted
        assert "create_file" not in restricted
        assert "delete_path" not in restricted
        assert "http_get" not in restricted

    assert "knowledge_search" in read_only
    assert "run_shell_command" not in read_only
    assert "run_shell_command" in reviewer


def test_coding_worker_has_code_tools_but_not_head_network_tools():
    coding = build_profile_registry(
        AgentProfile.CODING_WORKER,
        source_registry=_source_registry(),
    )

    assert "read_file" in coding
    assert "propose_file_edit" in coding
    assert "run_shell_command" in coding
    assert "knowledge_search" not in coding
    assert "http_get" not in coding


def test_prompt_describes_only_tools_in_assigned_registry():
    selected = _source_registry().select(("pwd", "read_file"))

    prompt = build_system_prompt(
        use_native_tools=True,
        tool_registry=selected,
    )

    assert "- pwd()" in prompt
    assert "- read_file()" in prompt
    assert "knowledge_search" not in prompt
    assert "Knowledge response-mode policy" not in prompt


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="Unknown agent profile"):
        profile_tool_names("administrator")
