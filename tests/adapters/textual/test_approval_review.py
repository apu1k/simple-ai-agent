"""Approval-display regressions only: no decisions, UAC, commands or host writes."""
import asyncio
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console
from textual.containers import VerticalScroll
from textual.events import Mount
from textual.widgets import Input, Static

from adapters.textual.app import AgentTextualApp
from adapters.textual.approval_review import render_privileged_review
from editing.store import EditStore
from runtime.privileged_turn import ELEVATED_OPERATION, PendingPrivilege, PrivilegedClaim
from runtime.state import ModelSettings


def frozen_request(details):
    raw = json.dumps(details, sort_keys=True, ensure_ascii=True, indent=2)
    return PendingPrivilege(
        'E' + 'a' * 32, PrivilegedClaim('a' * 32, 0, ELEVATED_OPERATION),
        raw, hashlib.sha256(raw.encode('utf-8')).hexdigest(),
    )


def test_multiline_script_and_all_metadata_are_visible_without_changing_approval():
    script = 'Write-Output "[red]literal[/red]"\nWrite-Output "Gr\u00fc\u00dfe \U0001f680"\n'
    metadata = {'reason': 'display fixture', 'cwd': 'C:\\fixture', 'timeout': 60,
                'helper_sha256': 'b' * 64, 'policy': {'future_field': 'retained'}}
    request = frozen_request(dict(metadata, script=script))
    before = (request.review_json, request.review_sha256)
    review = render_privileged_review(request)
    assert script in review.plain
    assert '[BEGIN POWERSHELL SCRIPT]\n' + script + '[END POWERSHELL SCRIPT]' in review.plain
    assert json.dumps(metadata, sort_keys=True, ensure_ascii=True, indent=2) in review.plain
    assert '"script":' not in review.plain
    assert request.review_sha256 in review.plain
    assert review.no_wrap is False and review.overflow == 'fold'
    assert (request.review_json, request.review_sha256) == before
    assert hashlib.sha256(request.review_json.encode('utf-8')).hexdigest() == request.review_sha256


def test_literal_backslash_escapes_are_not_decoded_twice():
    script = r'Write-Output "literal \n and \u001b"' + '\n'
    assert script in render_privileged_review(frozen_request({'script': script})).plain


def test_nonprinting_characters_cannot_hide_or_reorder_script_text():
    script = '\tWrite-Output "safe"\r\n# \x1b[31m\x08\u202e\u200b\u2028\x7f'
    plain = render_privileged_review(frozen_request({'script': script})).plain
    for char in ('\t', '\r', '\x1b', '\x08', '\u202e', '\u200b', '\u2028', '\x7f'):
        assert char not in plain
        assert f'<U+{ord(char):04X}>' in plain
    assert 'Write-Output "safe"<U+000D>\n# ' in plain


def test_maximum_size_unbroken_script_is_folded_without_losing_characters():
    script = 'z' * 32768
    review = render_privileged_review(frozen_request({'script': script}))
    start = review.plain.index('[BEGIN POWERSHELL SCRIPT]\n') + len('[BEGIN POWERSHELL SCRIPT]\n')
    end = review.plain.index('[END POWERSHELL SCRIPT]', start)
    output = io.StringIO()
    console = Console(file=output, width=23, force_terminal=False, color_system=None)
    console.print(review[start:end], end='', no_wrap=False, overflow='fold')
    assert output.getvalue().replace('\n', '') == script


@pytest.mark.parametrize('details', [
    {'operation': 'inspect_image_copy', 'policy': {'source': 'D:\\fixture.vhdx'}},
    {'script': ['not a string'], 'future_field': 'retained'},
    ['non-dict fixture', 'RAW_END_MARKER'],
])
def test_fixed_helpers_and_non_script_payloads_keep_the_entire_frozen_json(details):
    request = frozen_request(details)
    review = render_privileged_review(request)
    assert request.review_json in review.plain
    assert 'Frozen request JSON:' in review.plain
    assert '[BEGIN POWERSHELL SCRIPT]' not in review.plain


def test_invalid_json_is_not_hidden_or_interpreted_as_markup():
    raw = '{invalid [red] RAW_END_MARKER'
    request = PendingPrivilege('Efixture', PrivilegedClaim('a' * 32, 0), raw, 'f' * 64)
    assert raw in render_privileged_review(request).plain


class ReadOnlyGate:
    """Display fixture with no approval or execution API."""
    def __init__(self, entries):
        self.entries = dict(entries)

    def pending(self):
        return dict(self.entries)

    def revoke(self):
        self.entries.clear()


class ReviewTestApp(AgentTextualApp):
    CSS_PATH = [Path(__file__).resolve().parents[3] / 'adapters' / 'textual' / path
                for path in AgentTextualApp.CSS_PATH]

    def on_mount(self, event: Mount) -> None:
        event.prevent_default()  # No production startup/model/background work.
        self.screen.add_class('theme-dark' if self._theme_dark else 'theme-light')
        self.query_one('#input', Input).focus()


def fixture_app(tmp_path, entries, *, theme_dark=True):
    state = SimpleNamespace(
        cwd=tmp_path, edit_store=EditStore(), privileged_turn=ReadOnlyGate(entries),
        model_settings=ModelSettings(), chat_session_id=None,
        model_config=SimpleNamespace(provider_label='Fixture', model='Fixture', api_type='responses'),
    )
    app = ReviewTestApp(state=state, llm=SimpleNamespace())
    app._theme_dark = theme_dark
    return app


def screen_text(app):
    return '\n'.join(strip.text for strip in app.screen._compositor.render_strips())


@pytest.mark.parametrize('theme_dark', [True, False])
def test_pending_script_wraps_scrolls_and_remains_reachable_after_resize(tmp_path, theme_dark):
    async def run():
        script = ('Write-Output "FIRST_LINE"\nWrite-Output "' + 'x' * 400 + 'TOKEN_TAIL"\n'
                  + ''.join(f'# row {index}\n' for index in range(40))
                  + 'Write-Output "LAST_MARKER"\n')
        request = frozen_request({'script': script, 'reason': 'r' * 300, 'timeout': 10,
                                  'cwd': 'C:\\fixture'})
        before = (request.review_json, request.review_sha256)
        app = fixture_app(tmp_path, {request.id: request}, theme_dark=theme_dark)
        async with app.run_test(size=(120, 40)) as pilot:
            app._enter_pending_select_mode()
            await pilot.pause()
            widget = app.query_one('#pending_diff', Static)
            pane = app.query_one('#pending_diff_scroll', VerticalScroll)
            assert '[BEGIN POWERSHELL SCRIPT]' in str(widget.render())
            for width in (120, 80, 60, 160):
                await pilot.resize_terminal(width, 40)
                await pilot.pause()
                assert widget.size.width <= pane.content_size.width
                assert pane.virtual_size.width <= pane.content_size.width
                assert pane.max_scroll_x == 0
                pane.scroll_home(animate=False)
                await pilot.pause()
                await pilot.press('pagedown')
                await pilot.pause()
                assert pane.scroll_y > 0
                pane.scroll_end(animate=False)
                await pilot.pause()
                assert pane.scroll_y == pane.max_scroll_y
                assert 'LAST_MARKER' in screen_text(app)
                assert (request.review_json, request.review_sha256) == before
                assert app.state.privileged_turn.pending() == {request.id: request}
    asyncio.run(run())


def test_shared_review_width_still_displays_the_end_of_file_diffs(tmp_path):
    async def run():
        app = fixture_app(tmp_path, {})
        path = tmp_path / 'not-created.txt'
        content = 'x' * 400 + '\n' + 'row\n' * 60 + 'FILE_DIFF_LAST_MARKER\n'
        app.state.edit_store.propose_create(path, content)
        async with app.run_test(size=(80, 40)) as pilot:
            app._enter_pending_select_mode()
            await pilot.pause()
            widget = app.query_one('#pending_diff', Static)
            pane = app.query_one('#pending_diff_scroll', VerticalScroll)
            assert widget.size.width <= pane.content_size.width
            assert pane.max_scroll_x == 0
            pane.scroll_end(animate=False)
            await pilot.pause()
            assert 'FILE_DIFF_LAST_MARKER' in screen_text(app)
            assert not path.exists()
            assert len(app.state.edit_store.pending()) == 1
    asyncio.run(run())
