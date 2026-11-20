"""Browser arming and local review contracts, with no real GUI or UAC."""
from __future__ import annotations

from pathlib import Path
import sys
from threading import Event, Thread
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from runtime.chat_store import ChatStore
from runtime.conversations import ConversationManager
import runtime.desktop_approval as desktop
from runtime.elevated_commands import await_approval
from runtime.privileged_turn import ELEVATED_OPERATION
from runtime.remote import RemoteRuntimeClient
from runtime.server import create_server
from tests.runtime_helpers import make_runtime


_TOKEN = 'desktop fixture ' + 'x' * 32


@pytest.mark.parametrize(('reviewer_answer', 'revoke', 'expected'), [
    (True, False, 'accepted'),
    (False, False, 'rejected'),
    (True, True, 'expired'),
])
def test_shared_web_chat_can_arm_but_only_desktop_can_decide(tmp_path, monkeypatch, reviewer_answer, revoke, expected):
    started, finish = Event(), Event()
    observed = []
    agents = {}

    class FixtureReview(desktop.DesktopApproval):
        def ask(self, display, digest, cancelled):
            observed.append((display, digest))
            started.set()
            assert finish.wait(5), 'review fixture was not released'
            return reviewer_answer  # Even a late positive result must not resurrect a revoked request.

    reviewer = FixtureReview()
    history = ChatStore(tmp_path / 'shared-history')

    def factory(identity, store, source):
        runtime, agent = make_runtime(tmp_path, desktop_review=reviewer)
        runtime.state.chat_session_id = identity
        runtime.state.chat_store = history
        agents[identity] = agent
        return runtime

    desktop_unlocked = [False]
    monkeypatch.setattr('runtime.service.desktop_ready', lambda: desktop_unlocked[0])
    manager = ConversationManager(history=history, runtime_factory=factory)
    session = manager.default_chat_id
    second_chat = manager.new_chat()
    runtime = manager.get(session)

    def step(_):
        gate = runtime.state.privileged_turn
        claim = gate.claim(ELEVATED_OPERATION)
        request, decision = await_approval(gate, claim, {'script': '# SHOW_ONLY_FIXTURE\n', 'timeout': 15})
        if decision == 'accepted':
            gate.require_accepted(request)  # Validates binding; no actual launcher call.
        return decision

    agents[session].behavior = step
    app = create_server(manager, token=_TOKEN)
    assert app.state.server_id
    with TestClient(app, base_url='http://127.0.0.1', headers={'Authorization': f'Bearer {_TOKEN}'}) as client:
        def command(operation, arguments):
            return client.post('/v1/commands', json={
                'operation': operation, 'arguments': arguments, 'server_id': app.state.server_id,
                'request_id': uuid4().hex, 'session_id': session,
            })

        def frame(identity=session):
            return client.get('/v1/snapshot', params={'session_id': identity}).json()

        try:
            assert command('set_desktop_elevation', {'enabled': True}).status_code == 403
            desktop_unlocked[0] = True
            assert command('set_desktop_elevation', {'enabled': True, 'approve': True}).status_code == 422
            assert command('set_desktop_elevation', {'enabled': True}).status_code == 200
            assert frame()['state']['desktop_elevation']['armed_operation'] == ELEVATED_OPERATION
            assert frame(second_chat)['state']['desktop_elevation']['armed_operation'] is None
            assert command('submit', {'text': 'request desktop review'}).status_code == 200
            assert started.wait(2)
            assert runtime.snapshot().processing
            assert len(observed) == 1
            display, digest = observed[0]
            request, = runtime.state.privileged_turn.pending().values()
            assert digest == request.review_sha256
            assert '# SHOW_ONLY_FIXTURE' in display and digest in display
            assert frame()['pending'] == []
            assert 'SHOW_ONLY_FIXTURE' not in str(frame())
            assert command('decide_pending', {
                'identity': request.id, 'accept': True, 'revision': digest,
            }).status_code == 422
            assert runtime.snapshot().processing
            if revoke:
                assert command('set_desktop_elevation', {'enabled': False}).status_code == 200
        finally:
            finish.set()
        assert runtime.wait_for_idle(4)
        assert runtime.snapshot().run.reply == expected
        assert runtime.state.privileged_turn.status == 'disabled'


def test_desktop_reviewer_refuses_busy_locked_expired_and_malformed(tmp_path, monkeypatch):
    reviewer = desktop.DesktopApproval()
    ready = [False]
    entered, release = Event(), Event()
    result = []
    digest = 'a' * 64
    monkeypatch.setattr(desktop, 'desktop_ready', lambda: ready[0])

    def native_fixture(data, expected, cancelled):
        assert b'fixture text' in data and expected == digest
        assert not cancelled()
        entered.set()
        assert release.wait(4)
        return True

    monkeypatch.setattr(reviewer, '_prompt', native_fixture)
    assert not reviewer.ask('fixture text', digest, lambda: False)
    ready[0] = True
    assert not reviewer.ask('fixture text', 'not a digest', lambda: False)
    assert not reviewer.ask('fixture text', digest, lambda: True)
    worker = Thread(target=lambda: result.append(reviewer.ask('fixture text', digest, lambda: False)))
    worker.start()
    try:
        assert entered.wait(2)
        assert not reviewer.ask('fixture text', digest, lambda: False)
    finally:
        release.set()
        worker.join(4)
    assert result == [True]


@pytest.mark.parametrize(('mode', 'accepted'), [('exact', True), ('extra', False), ('cancelled', False)])
def test_native_pipe_result_binds_digest_and_cancels_owned_process(monkeypatch, mode, accepted):
    digest = 'a' * 64
    start = desktop.subprocess.Popen
    children = []
    source = (
        'import sys,time; data=sys.stdin.buffer.read(); '
        'assert data == b"x" * (128 * 1024); '
        + ('time.sleep(15); ' if mode == 'cancelled' else '')
        + f'sys.stdout.buffer.write({digest.encode()!r}'
        + (' + b"\\n")' if mode == 'extra' else ')')
    )

    def fixture(argv, **kwargs):
        assert argv[:4] == [sys._base_executable, '-I', '-S', '-B']
        assert Path(argv[4]).name == 'desktop_approval.py' and argv[5:] == ['--review']
        assert 'PYTHONPATH' not in kwargs['env']
        child = start([*argv[:4], '-c', source], **kwargs)
        children.append(child)
        return child

    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return mode == 'cancelled' and checks >= 3

    monkeypatch.setattr(desktop.subprocess, 'Popen', fixture)
    monkeypatch.setattr(desktop, 'desktop_ready', lambda: True)
    assert desktop.DesktopApproval._prompt(b'x' * (128 * 1024), digest, cancelled) is accepted
    child, = children
    assert child.poll() is not None


def test_remote_client_never_claims_approval_capability(monkeypatch):
    client = RemoteRuntimeClient('http://127.0.0.1:8765', _TOKEN)
    calls = []
    monkeypatch.setattr(client, '_command', lambda operation, **args: calls.append((operation, args)))
    with pytest.raises(PermissionError):
        client.set_model_setting('elevated_commands', True)
    client.state.desktop_approval_enabled = True
    client.set_model_setting('elevated_commands', True)
    assert calls == [('set_desktop_elevation', {'enabled': True})]
    with pytest.raises(PermissionError):
        client.attach_client(can_approve=True)
    with pytest.raises(PermissionError):
        client.decide_pending('E' + 'a' * 32, accept=True, revision='a' * 64)
