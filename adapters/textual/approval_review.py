"""Readable, width-aware views of frozen approvals; never alter authorization."""
from __future__ import annotations

import json

from rich.text import Text

from runtime.privileged_turn import PendingPrivilege

WARNING_STYLE = 'bold #E3A35C'


def _visible_script(value: str) -> str:
    """Preserve LF; expose controls, tabs and invisible formatting characters."""
    return ''.join(
        char if char == '\n' or char.isprintable() else f'<U+{ord(char):04X}>'
        for char in value
    )


def render_privileged_review(request: PendingPrivilege) -> Text:
    """Format a display only; approval still binds the original review_json bytes."""
    review = Text(no_wrap=False, overflow='fold')
    review.append(
        f'ADMINISTRATOR request #{request.id}\n'
        'Enter accepts this exact request and requests Windows UAC. Delete rejects.\n'
        'Not sandboxed. Referenced dependencies may change. No rollback or automatic retry.\n'
        f'Review SHA-256: {request.review_sha256}\n\n',
        style=WARNING_STYLE,
    )
    review.append(
        'Display only: long lines soft-wrap; non-printing characters other than LF '
        'use <U+XXXX> markers. Approval binds the unchanged original request.\n\n'
    )
    try:
        details = json.loads(request.review_json)
    except (ValueError, TypeError):
        details = None

    if isinstance(details, dict) and isinstance(details.get('script'), str):
        review.append('Request metadata (script shown separately below):\n', style='bold')
        metadata = {key: value for key, value in details.items() if key != 'script'}
        review.append(json.dumps(metadata, sort_keys=True, ensure_ascii=True, indent=2))
        review.append('\n\n[BEGIN POWERSHELL SCRIPT]\n', style=WARNING_STYLE)
        script = details['script']
        review.append(_visible_script(script))
        if not script.endswith('\n'):
            review.append('\n')
        review.append('[END POWERSHELL SCRIPT]\n', style=WARNING_STYLE)
    else:
        # Fixed helper reviews have no script. Keep their complete frozen payload;
        # malformed/non-dict fixtures also remain visible rather than disappearing.
        review.append('Frozen request JSON:\n', style='bold')
        review.append(_visible_script(request.review_json))
    return review
