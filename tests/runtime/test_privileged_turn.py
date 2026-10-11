"""No UAC or real Hyper-V operations: grant lifecycle and tool isolation."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace

import pytest

from core.agent import Agent
from runtime.privileged_turn import ARM_SECONDS, TURN_SECONDS, PrivilegedTurn
from runtime.tool_profiles import AgentProfile, profile_tool_names
from tools.system import privileged_host as tool_module


@pytest.fixture
def gate():
    now = [10.0]
    return PrivilegedTurn(clock=lambda: now[0], wall_clock=lambda: 1000.0), now


def test_default_denied_and_only_one_claim(gate):
    permit, _ = gate
    with pytest.raises(PermissionError):
        permit.claim()
    with permit.turn('head'), pytest.raises(PermissionError):
        permit.claim()
    permit.arm()
    with pytest.raises(PermissionError):
        permit.claim()
    with permit.turn('head'):
        assert permit.status.startswith('active')
        claim = permit.claim()
        assert len(claim.request_id) == 32 and claim.deadline_unix == 1000 + TURN_SECONDS
        assert permit.status == 'consumed'
        with pytest.raises(PermissionError):
            permit.claim()
    assert permit.status == 'disabled'
    with permit.turn('head'), pytest.raises(PermissionError):
        permit.claim()


def test_expiry_and_unused_turn_revoke(gate):
    permit, now = gate
    permit.arm()
    now[0] += ARM_SECONDS
    assert permit.status == 'disabled'
    with permit.turn('head'), pytest.raises(PermissionError):
        permit.claim()
    permit.arm()
    with permit.turn('head'):
        now[0] += TURN_SECONDS
        assert permit.status == 'expired'
        with pytest.raises(PermissionError):
            permit.claim()
    permit.arm()
    with permit.turn('head'):
        pass
    assert permit.status == 'disabled'
    assert PrivilegedTurn().status == 'disabled'


def test_revoke_exception_and_worker_no_inheritance(gate):
    permit, _ = gate
    permit.arm()
    with permit.turn('coding-worker'), pytest.raises(PermissionError):
        permit.claim()
    assert permit.status == 'armed for next turn'
    with pytest.raises(RuntimeError, match='test failure'):
        with permit.turn('head'):
            with permit.turn('review-worker'), pytest.raises(PermissionError):
                permit.claim()
            raise RuntimeError('test failure')
    assert permit.status == 'disabled'
    permit.arm()
    with permit.turn('head'):
        permit.revoke()
        with pytest.raises(PermissionError):
            permit.claim()
        with pytest.raises(RuntimeError):
            permit.arm()
        with pytest.raises(RuntimeError):
            with permit.turn('head'):
                pass


def test_parallel_claims_cannot_expand_budget(gate):
    permit, _ = gate
    permit.arm()
    def attempt():
        try:
            permit.claim()
            return True
        except PermissionError:
            return False
    with permit.turn('head'), ThreadPoolExecutor(max_workers=10) as pool:
        contexts = [copy_context() for _ in range(100)]
        futures = [pool.submit(ctx.run, attempt) for ctx in contexts]
        assert sum(f.result() for f in futures) == 1


def test_external_thread_without_context_is_denied(gate):
    permit, _ = gate
    permit.arm()
    with permit.turn('head'), ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(PermissionError):
            pool.submit(permit.claim).result()
        permit.claim()


@pytest.mark.parametrize('failure', [False, True])
def test_tool_failure_is_not_refunded_or_leaked(gate, monkeypatch, failure):
    permit, _ = gate
    calls = []
    def collect(claim):
        calls.append(claim)
        if failure:
            raise RuntimeError('PRIVATE_CANARY')
        return {'status': 'uac_cancelled', 'launch_authorized': False}
    monkeypatch.setattr(tool_module, 'collect_installed_evidence', collect)
    state = SimpleNamespace(privileged_turn=permit)
    assert tool_module.collect_privileged_host_evidence(state).startswith('Error:')
    permit.arm()
    with permit.turn('head'):
        result = tool_module.collect_privileged_host_evidence(state)
        assert 'PRIVATE_CANARY' not in result
        assert 'false' in result
        assert tool_module.collect_privileged_host_evidence(state).startswith('Error:')
    assert len(calls) == 1
    assert permit.status == 'disabled'
    with pytest.raises(TypeError):
        tool_module.collect_privileged_host_evidence(state, command='Remove-VM')


def test_head_only_profile():
    assert 'collect_privileged_host_evidence' in profile_tool_names(AgentProfile.HEAD)
    for profile in AgentProfile:
        if profile != AgentProfile.HEAD:
            assert 'collect_privileged_host_evidence' not in profile_tool_names(profile)


@pytest.mark.parametrize('failure', [False, True])
def test_agent_wrapper_releases_grant_on_all_exits(gate, failure):
    permit, _ = gate
    agent = Agent.__new__(Agent)
    agent.state = SimpleNamespace(privileged_turn=permit)
    agent.agent_profile = 'head'
    def fake_step(text):
        assert permit.status.startswith('active')
        assert text == 'test'
        if failure:
            raise RuntimeError('fake model failure')
        return 'done'
    agent._step = fake_step
    permit.arm()
    if failure:
        with pytest.raises(RuntimeError):
            agent.step('test')
    else:
        assert agent.step('test') == 'done'
    assert permit.status == 'disabled'
