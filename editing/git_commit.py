"""Prepare reviewed Git commits without touching the real index or refs."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from editing.model import EditStatus, GitCommitPlan

MAX_FILES = 100
MAX_REVIEW_BYTES = 100_000
_NETWORK_TIMEOUT = 60


class GitError(ValueError):
    pass


def _git(repo: Path, *args: str, env: dict[str, str] | None = None,
         data: bytes | None = None, timeout: int = 20, config: tuple[str, ...] = ()) -> bytes:
    # Do not let inherited GIT_DIR, GIT_INDEX_FILE, etc. redirect this operation.
    proc_env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    proc_env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never', GIT_OPTIONAL_LOCKS='0',
                    GIT_ALLOW_PROTOCOL='file:http:https:ssh:git', GIT_NO_LAZY_FETCH='1',
                    GIT_NO_REPLACE_OBJECTS='1')
    proc_env.update(env or {})
    command = ['git', '--no-pager', '--literal-pathspecs', '-c', 'core.fsmonitor=false',
               '-c', 'core.splitIndex=false', *config, *args]
    try:
        result = subprocess.run(command, cwd=repo, env=proc_env, input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise GitError(f'Git {args[0]} timed out') from exc
    except OSError as exc:
        raise GitError(f'Could not start Git ({args[0]})') from exc
    if result.returncode != 0:
        # Do not echo remote output or URL credentials into pending/chat records.
        raise GitError(f'Git {args[0]} failed (exit {result.returncode})')
    return result.stdout


def _path(repo: Path, name: str) -> Path:
    raw = _git(repo, 'rev-parse', '--path-format=absolute', '--git-path', name)
    return Path(os.fsdecode(raw.rstrip(b'\r\n')))


def _root(location: Path) -> Path:
    value = _git(location.resolve(), 'rev-parse', '--show-toplevel').rstrip(b'\r\n')
    return Path(os.fsdecode(value)).resolve(strict=True)


def _branch(repo: Path) -> tuple[str, str, str, str, str]:
    try:
        branch = _git(repo, 'symbolic-ref', '--quiet', 'HEAD').decode().strip()
        base = _git(repo, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    except GitError as exc:
        raise GitError('Use a checked-out branch with an existing commit (not detached HEAD)') from exc
    upstream = _git(repo, 'for-each-ref',
                    '--format=%(upstream:remotename)%00%(upstream:remoteref)%00%(upstream)', branch)
    fields = upstream.decode().rstrip('\r\n').split('\0')
    if (not branch.startswith('refs/heads/') or len(fields) != 3
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', fields[0])
            or not fields[1].startswith('refs/heads/') or not fields[2].startswith('refs/remotes/')):
        raise GitError('Configure a remote upstream branch before proposing a commit')
    return branch, base, fields[0], fields[1], fields[2]


def _push_url(repo: Path, remote: str) -> str:
    urls = _git(repo, 'remote', 'get-url', '--push', '--all', '--', remote).decode().splitlines()
    if len(urls) != 1 or not urls[0] or not all(char.isprintable() for char in urls[0]):
        raise GitError('The upstream must have exactly one printable push URL')
    return urls[0]


def _display_url(url: str) -> str:
    if '://' not in url:
        return url  # A local path or scp-style SSH address.
    parts = urlsplit(url)
    return f'{parts.scheme}://{parts.netloc.rsplit("@", 1)[-1]}{parts.path}'


def _file_list(repo: Path, files: list[str]) -> list[str]:
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise GitError(f'List 1–{MAX_FILES} explicit repository-relative files')
    result = []
    for name in files:
        if not isinstance(name, str) or not name or not all(c.isprintable() for c in name) or ':' in name:
            raise GitError('Use printable repository-relative file names (no drive prefixes)')
        parts = name.replace('\\', '/').split('/')
        if any(part.lower() in ('', '.', '..', '.git') for part in parts):
            raise GitError('Use explicit file paths under the repository root')
        path = repo
        for i, part in enumerate(parts):
            path /= part
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                break  # A tracked deletion can be selected.
            except OSError as exc:
                # Windows rejects wildcard characters and other invalid names at lstat.
                raise GitError(f'Cannot inspect the selected file path: {name}') from exc
            expected = stat.S_ISREG if i == len(parts) - 1 else stat.S_ISDIR
            if not expected(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & 0x400:
                raise GitError(f'Expected a regular file with no symlink/reparse components: {name}')
        result.append('/'.join(parts))
    if len({os.path.normcase(name) for name in result}) != len(result):
        raise GitError('List each file only once')
    return result


def _repo_ready(repo: Path) -> None:
    for marker in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply',
                   'sequencer', 'info/sparse-checkout'):
        if _path(repo, marker).exists():
            raise GitError('Finish any merge/rebase/sequencer operation or leave sparse checkout first')
    if _git(repo, 'ls-files', '--unmerged'):
        raise GitError('Resolve index conflicts before proposing a commit')


def _snapshot(repo: Path, base: str, files: list[str], env: dict[str, str]) -> str:
    _git(repo, 'read-tree', base, env=env)
    # Custom clean filters can run external code during a preview. Decline
    # these files rather than silently bypassing conversion (e.g. Git LFS).
    attrs = _git(repo, 'check-attr', '-z', 'filter', '--', *files, env=env).split(b'\0')
    if any(value not in (b'unspecified', b'unset', b'set') for value in attrs[2::3]):
        raise GitError('Files with custom Git clean filters (including Git LFS) are not supported')
    _git(repo, 'add', '-A', '--', *files, env=env,
         config=tuple(token for name in ('unspecified', 'unset', 'set') for token in (
             '-c', f'filter.{name}.clean=', '-c', f'filter.{name}.process=', '-c', f'filter.{name}.required=false',
         )))
    tree = _git(repo, 'write-tree', env=env).decode().strip()
    names = _git(repo, 'diff', '--name-only', '--no-renames', '-z', base, tree, '--', env=env)
    if {os.fsdecode(name) for name in names.split(b'\0') if name} != set(files):
        raise GitError('Each selected file must have a committable change; only exact file paths are supported')
    return tree


def _visible(text: str) -> str:
    return ''.join(c if c == '\n' or c.isprintable() else f'<U+{ord(c):04X}>' for c in text)


def prepare_commit(location: Path, files: list[str], message: str) -> tuple[Path, GitCommitPlan, str]:
    if (not isinstance(message, str) or not message.strip() or len(message) > 4000
            or any(c not in '\r\n\t' and not c.isprintable() for c in message)):
        raise GitError('Provide a nonempty commit message of at most 4000 characters')
    message = message.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n') + '\n'
    repo = _root(location)
    selected = _file_list(repo, files)
    _repo_ready(repo)
    branch, base, remote, ref, upstream = _branch(repo)
    if _git(repo, 'rev-parse', '--verify', upstream).decode().strip() != base:
        raise GitError('Synchronize the local branch with its upstream first; other commits will not be pushed')
    url = _push_url(repo, remote)
    with TemporaryDirectory(prefix='agent-git-preview-') as tmp:
        temp = Path(tmp)
        objects = temp / 'objects'
        (objects / 'info').mkdir(parents=True)
        (objects / 'info' / 'alternates').write_bytes(os.fsencode(_path(repo, 'objects').as_posix()) + b'\n')
        env = {'GIT_INDEX_FILE': str(temp / 'index'), 'GIT_OBJECT_DIRECTORY': str(objects)}
        tree = _snapshot(repo, base, selected, env)
        patch = _git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames',
                     '--full-index', '--patch', base, tree, '--', env=env)
    if len(patch) > MAX_REVIEW_BYTES:
        raise GitError('Diff exceeds the pending review limit; select fewer files')
    plan = GitCommitPlan(selected, message, branch, remote, ref, hashlib.sha256(url.encode()).hexdigest(), base, tree)
    preview = (f'COMMIT AND PUSH — approval runs Git with the backend account’s credentials.\n'
               f'Local branch: {branch}\nPush to: {remote} → {ref}\nRemote: {_display_url(url)}\n'
               f'Base: {base}\nReviewed tree: {tree}\n\nFiles:\n'
               + ''.join(f'  {name}\n' for name in selected)
               + '\nCommit message:\n' + message + '\nReviewed diff:\n'
               + patch.decode('utf-8', errors='backslashreplace'))
    return repo, plan, _visible(preview)


def _target(repo: Path, plan: GitCommitPlan, local_tip: str) -> str:
    branch, tip, remote, ref, _ = _branch(repo)
    url = _push_url(repo, remote)
    if ((branch, tip, remote, ref) != (plan.branch, local_tip, plan.remote, plan.remote_ref)
            or hashlib.sha256(url.encode()).hexdigest() != plan.url_sha256):
        raise GitError('Branch, HEAD or push destination changed after review')
    return url


def _changed_in_index(repo: Path, tree: str, files: list[str]) -> set[bytes]:
    diff = _git(repo, 'diff', '--cached', '--name-only', '--no-renames', '-z', tree, '--', *files)
    return set(diff.split(b'\0')) - {b''}


def _verify_commit(repo: Path, plan: GitCommitPlan, commit: str) -> None:
    raw = _git(repo, 'cat-file', 'commit', commit)
    head, _, message = raw.partition(b'\n\n')
    fields = [row for row in head.splitlines() if row.startswith((b'tree ', b'parent '))]
    if fields != [f'tree {plan.tree}'.encode(), f'parent {plan.base}'.encode()] or message != plan.message.encode():
        raise GitError('Local commit does not match the reviewed tree, parent or message (possibly due to a Git hook)')


def apply_commit(repo: Path, plan: GitCommitPlan) -> tuple[EditStatus, str]:
    """Execute one approved plan. Never retry or roll back a local commit."""
    commit: str | None = None
    commit_started = False
    push_started = False
    try:
        if _root(repo) != repo or _file_list(repo, plan.files) != plan.files:
            raise GitError('Repository or file paths changed after review')
        _repo_ready(repo)
        url = _target(repo, plan, plan.base)
        remote_tip = _git(repo, 'ls-remote', '--refs', '--exit-code', '--', url, plan.remote_ref,
                          timeout=_NETWORK_TIMEOUT)
        if remote_tip.splitlines() != [f'{plan.base}\t{plan.remote_ref}'.encode()]:
            raise GitError('Remote branch does not match the reviewed base; fetch and review again')
        index = _path(repo, 'index')
        lock = index.with_name('index.lock')
        try:
            # Honor the same exclusive lock as Git while preserving the actual
            # index. Unrelated staged files are neither reset nor committed.
            lock.touch(exist_ok=False)
        except FileExistsError as exc:
            raise GitError('Git index is locked by another operation') from exc
        lock_owned = True
        try:
            with TemporaryDirectory(prefix='agent-git-commit-', dir=index.parent) as tmp:
                temp = Path(tmp)
                env = {'GIT_INDEX_FILE': str(temp / 'review-index')}
                tree = _snapshot(repo, plan.base, plan.files, env)
                if tree != plan.tree:
                    raise GitError('Selected file content or modes changed after review; propose again')
                if _changed_in_index(repo, plan.base, plan.files) & _changed_in_index(repo, tree, plan.files):
                    raise GitError('Selected files have different staged and working-tree changes; resolve partial staging first')
                preserved = temp / 'real-index'
                sync_env = {'GIT_INDEX_FILE': str(preserved)}
                if index.exists():
                    shutil.copyfile(index, preserved)
                else:
                    _git(repo, 'read-tree', plan.base, env=sync_env)
                _git(repo, 'reset', '-q', tree, '--', *plan.files, env=sync_env)
                _target(repo, plan, plan.base)
                commit_started = True
                _git(repo, 'commit', '--file=-', '--cleanup=verbatim', env=env, data=plan.message.encode())
                commit = _git(repo, 'rev-parse', '--verify', plan.branch).decode().strip()
                _verify_commit(repo, plan, commit)
                shutil.copyfile(preserved, lock)
                if index.exists():
                    shutil.copymode(index, lock)
                os.replace(lock, index)
                lock_owned = False
        finally:
            if lock_owned:
                lock.unlink(missing_ok=True)
        _target(repo, plan, commit)
        push_started = True
        # The lease demands the exact reviewed remote base; _verify_commit
        # proved that base is the new commit's sole parent, so this only allows
        # a fast-forward and never a history rewrite, even if the remote raced.
        _git(repo, 'push', '--porcelain', '--no-follow-tags', '--recurse-submodules=no',
             f'--force-with-lease={plan.remote_ref}:{plan.base}', '--', plan.remote, f'{commit}:{plan.remote_ref}',
             timeout=_NETWORK_TIMEOUT, config=('-c', f'remote.{plan.remote}.mirror=false'))
        return 'applied', f'Committed {commit} and pushed it to {plan.remote}:{plan.remote_ref}.'
    except (OSError, ValueError) as exc:
        if push_started:
            return 'outcome_unknown', f'Commit {commit} is local. Push not confirmed: {exc}. Check the remote; no retry was attempted.'
        if commit_started:
            return 'outcome_unknown', f'Commit may have been made locally ({commit or "check Git history"}); no push was attempted: {exc}.'
        return 'rejected', f'No commit or push: {exc}.'
