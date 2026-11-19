"""Head-only Git commit and push proposals."""
from pathlib import Path

from editing.git_commit import MAX_FILES, prepare_commit
from tools._base import tool


@tool(
    description=(
        'Propose committing exactly the listed files and pushing the new commit to the '
        'branch’s configured upstream. Pending (F9) shows the commit message, destination '
        'and diff. No commit or push happens until accepted. This is not an elevated '
        'operation. Approve any pending file edits before proposing the commit.'
    ),
    params={
        'repo_path': 'Git worktree directory (or a subdirectory), absolute or relative to the agent working directory.',
        'files': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1,
                  'maxItems': MAX_FILES, 'description': 'Explicit file paths relative to the repository root; no directory selection.'},
        'message': 'The complete Git commit message.',
    },
    requires_state=True,
)
def propose_git_commit(state, repo_path: str, files: list[str], message: str) -> str:
    try:
        if not isinstance(repo_path, str) or not repo_path.strip():
            raise ValueError('Provide a Git worktree directory')
        root, plan, preview = prepare_commit(state.cwd / Path(repo_path).expanduser(), files, message)
        pending, _ = state.edit_store.propose_git_commit(root, plan, preview)
    except (OSError, ValueError) as exc:
        return f'Error: {exc}'
    return (f'Pending Git commit and push #{pending.id} for {root}. '
            'Review and accept or reject it in Pending (F9). Nothing has been committed or pushed.')
