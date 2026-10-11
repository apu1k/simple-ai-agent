"""UI progress is context-local and cannot replace tool results or permission."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from core.agent import Agent
from core.tool_progress import PRIVILEGED_EVIDENCE_PREFIX, evidence_progress, tool_progress_listener
from core.tool_registry import ToolRegistry, ToolSpec
from runtime import privileged_host
from runtime.privileged_turn import PrivilegedClaim


def test_listener_restored_on_exception_and_not_shared_with_unrelated_threads():
    messages = []
    with tool_progress_listener(messages.append):
        evidence_progress('outer')
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(evidence_progress, 'unrelated').result()
        with pytest.raises(RuntimeError), tool_progress_listener(lambda text: None):
            evidence_progress('inner')
            raise RuntimeError('fixture')
        evidence_progress('restored')
    evidence_progress('outside')
    assert messages == [PRIVILEGED_EVIDENCE_PREFIX + 'outer', PRIVILEGED_EVIDENCE_PREFIX + 'restored']


def test_broken_ui_callback_is_not_an_execution_failure():
    def broken(message):
        raise RuntimeError('UI unavailable')
    with tool_progress_listener(broken):
        evidence_progress('still read-only')


@pytest.mark.parametrize('failure', [False, True])
def test_agent_passes_live_progress_but_only_returns_actual_tool_result(failure):
    messages = []
    def fixture():
        evidence_progress('working, not complete')
        if failure:
            raise RuntimeError('tool failed')
        return 'actual result'
    agent = Agent.__new__(Agent)
    agent.state = SimpleNamespace()
    agent._tool = messages.append
    agent._error = lambda message: None
    agent.registry = ToolRegistry()
    agent.registry.register(ToolSpec('fixture', fixture, 'test', {}))
    status, observation, error = agent._execute_one_tool_call('fixture', {})
    assert status == ('failed' if failure else 'success')
    assert 'working' not in observation
    assert (error is not None) is failure
    if not failure:
        assert observation == 'actual result'
    assert messages == [PRIVILEGED_EVIDENCE_PREFIX + 'working, not complete']
    evidence_progress('must not leak')
    assert len(messages) == 1


@pytest.mark.parametrize('outcome', [0, 0xffffffff, 'deadline'])
def test_short_waits_emit_elapsed_progress_without_retry_or_early_completion(monkeypatch, tmp_path, outcome):
    clock = [100.0]
    waits = []
    messages = []
    monkeypatch.setattr(privileged_host.time, 'time', lambda: clock[0])
    monkeypatch.setattr(privileged_host.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(privileged_host, '_observed_phase', lambda root, identity: 'Hashing source VHDX')
    def wait(handle, milliseconds):
        waits.append(milliseconds)
        clock[0] += milliseconds / 1000
        if outcome != 'deadline' and len(waits) == 8:
            return outcome
        return 0x102
    kernel = SimpleNamespace(WaitForSingleObject=wait)
    with tool_progress_listener(messages.append):
        result = privileged_host._wait_for_helper(kernel, 42, tmp_path, PrivilegedClaim('a' * 32, 110))
    assert result == (0x102 if outcome == 'deadline' else outcome)
    assert all(0 < duration <= 1000 for duration in waits)
    assert any('0s elapsed' in text for text in messages)
    assert any('5s elapsed' in text for text in messages)
    assert not any('success' in text.lower() for text in messages)
    assert list(tmp_path.iterdir()) == []
