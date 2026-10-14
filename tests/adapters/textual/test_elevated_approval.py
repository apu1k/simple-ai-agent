"""Live pending UI with a waiting fixture worker; no UAC or host operations."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.events import Mount
from textual.widgets import Input, Static

from adapters.textual.app import AgentTextualApp
from core.tool_progress import tool_progress_listener
from editing.store import EditStore
from runtime.elevated_commands import await_approval
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedTurn
from runtime.state import ModelSettings


class ApprovalTestApp(AgentTextualApp):
    CSS_PATH = [Path(__file__).resolve().parents[3] / 'adapters' / 'textual' / path
                for path in AgentTextualApp.CSS_PATH]

    def on_mount(self, event: Mount) -> None:
        event.prevent_default()
        self._refresh_state()
        self.query_one('#input', Input).focus()


@pytest.mark.parametrize('action,expected', [('enter', 'accepted'), ('delete', 'rejected'), ('revoke', 'expired')])
def test_pending_command_approval_is_responsive_and_separate_from_file_edits(tmp_path, monkeypatch, action, expected):
    monkeypatch.setattr('adapters.textual.app.record_final_turn', lambda *args: None)
    async def run():
        permit = PrivilegedTurn()
        permit.arm(ELEVATED_OPERATION)
        state = SimpleNamespace(cwd=tmp_path, privileged_turn=permit, edit_store=EditStore(),
                                model_settings=ModelSettings(), chat_session_id=None,
                                model_config=SimpleNamespace(provider_label='Fixture', model='Fixture', api_type='responses'))
        # A normal file proposal shares the view but not the approval namespace.
        state.edit_store.propose_create(tmp_path / 'fixture.txt', 'not yet written')
        app = ApprovalTestApp(state=state, llm=SimpleNamespace())
        async with app.run_test(size=(150, 40)) as pilot:
            def step(text):
                with permit.turn('head'), tool_progress_listener(app._on_tool):
                    request, decision = await_approval(permit, permit.claim(ELEVATED_OPERATION),
                                                       {'script': 'Write-Output "[not markup]"', 'timeout': 60})
                    if decision == 'accepted':
                        permit.require_accepted(request)
                    return decision
            app.agent = SimpleNamespace(step=step)
            app._start_agent_step('fixture only')
            for _ in range(40):
                await pilot.pause()
                if permit.pending():
                    break
                await asyncio.sleep(0.025)
            assert permit.pending() and app._processing
            assert any(role == 'Approval' and 'Nothing has executed' in text for role, text in app._messages)
            assert app._message_renderable('Approval', 'notice').style == 'bold #E3A35C'
            app.query_one('#input', Input).value = '\\pending'
            await pilot.press('enter')
            await pilot.pause()
            assert app._mode == 'pending_select'
            assert len(app._visible_pending_ids) == 2
            app._select_pending_index(1)
            assert 'ADMINISTRATOR request' in str(app.query_one('#pending_diff', Static).render())
            if action == 'revoke':
                await pilot.press('ctrl+g')
                app.query_one('#input', Input).value = '\\settings'
                await pilot.press('enter')
                await pilot.pause()
                app._set_model_setting('elevated_commands', False)
            else:
                await pilot.press(action)
            for _ in range(40):
                await pilot.pause()
                if not app._processing:
                    break
                await asyncio.sleep(0.025)
            assert not app._processing
            assert ('AI', expected) in app._messages
            assert permit.status == 'disabled'
            assert len(state.edit_store.pending()) == 1
            assert not (tmp_path / 'fixture.txt').exists()
    asyncio.run(run())
