"""Approval integration on disposable local repositories; no network or UAC."""
import os
import shutil
import subprocess

import pytest

from editing.git_commit import GitError, apply_commit, prepare_commit
from runtime.wire import public_frame
from tests.runtime_helpers import make_runtime
from tools.system.git_commit import propose_git_commit

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='Git required')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, timeout=10).strip()


@pytest.fixture
def repositories(tmp_path, monkeypatch):
    for name in os.environ:
        if name.upper().startswith('GIT_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    repo, bare = tmp_path / 'work tree', tmp_path / 'remote.git'
    repo.mkdir()
    bare.mkdir()
    git(bare, 'init', '--bare', '-b', 'main')
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.name', 'Fixture')
    git(repo, 'config', 'user.email', 'fixture@example.invalid')
    git(repo, 'config', 'commit.gpgSign', 'false')
    git(repo, 'config', 'core.autocrlf', 'false')
    for name in ('selected.txt', 'other.txt', 'deleted.txt'):
        (repo / name).write_bytes(b'base\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'Base')
    git(repo, 'remote', 'add', 'origin', bare.as_posix())
    git(repo, 'push', '-u', 'origin', 'main')
    return repo, bare


def test_pending_revision_acceptance_commits_and_pushes_only_explicit_files(tmp_path, repositories):
    repo, remote = repositories
    rt, _ = make_runtime(tmp_path, persistence_path=tmp_path / 'state.sqlite3')
    try:
        base = git(repo, 'rev-parse', 'HEAD')
        (repo / 'selected.txt').write_bytes(b'reviewed\n')
        (repo / '-new [file].txt').write_bytes(b'new\n')
        (repo / 'deleted.txt').unlink()
        (repo / 'other.txt').write_bytes(b'unrelated staged work\n')
        git(repo, 'add', 'other.txt')
        before = (repo / '.git' / 'index').read_bytes()
        answer = propose_git_commit(rt.state, repo.name, ['selected.txt', '-new [file].txt', 'deleted.txt'],
                                    'Commit the reviewed files\n\nMore details')
        assert 'Pending Git commit and push' in answer, answer
        [entry] = public_frame(rt, 'server')['pending']
        assert entry['kind'] == 'git_commit'
        assert 'origin → refs/heads/main' in entry['diff']
        assert '+reviewed' in entry['diff'] and 'unrelated staged work' not in entry['diff']
        assert 'More details' in entry['diff']
        assert (repo / '.git' / 'index').read_bytes() == before
        assert git(repo, 'rev-parse', 'HEAD') == git(remote, 'rev-parse', 'main') == base
        with pytest.raises(ValueError, match='review it again'):
            rt.decide_file_pending(entry['id'], accept=True, revision='stale')
        assert 'accepted' in rt.decide_file_pending(entry['id'], accept=True, revision=entry['revision'])
        assert not rt.pending()
        with pytest.raises(ValueError, match='no longer pending'):
            rt.decide_file_pending(entry['id'], accept=True, revision=entry['revision'])
    finally:
        rt.close()
    result = rt.state.edit_store.all()[entry['id']]
    assert result.status == 'applied', rt.snapshot().messages
    assert git(repo, 'rev-parse', 'HEAD') == git(remote, 'rev-parse', 'main')
    assert git(repo, 'diff', '--cached', '--name-only') == 'other.txt'
    assert git(repo, 'show', 'HEAD:selected.txt') == 'reviewed'
    assert git(repo, 'show', 'HEAD:other.txt') == 'base'
    assert git(repo, 'ls-tree', '--name-only', 'HEAD').splitlines() == ['-new [file].txt', 'other.txt', 'selected.txt']


def test_reject_does_not_commit_push_or_discard_other_staged_files(tmp_path, repositories):
    repo, remote = repositories
    rt, _ = make_runtime(tmp_path)
    try:
        base = git(repo, 'rev-parse', 'HEAD')
        (repo / 'selected.txt').write_bytes(b'reviewed\n')
        assert 'Pending Git' in propose_git_commit(rt.state, str(repo), ['selected.txt'], 'Rejected fixture')
        [entry] = public_frame(rt, 'server')['pending']
        rt.decide_file_pending(entry['id'], accept=False, revision=entry['revision'])
        assert not rt.pending()
        assert git(repo, 'rev-parse', 'HEAD') == git(remote, 'rev-parse', 'main') == base
        assert git(repo, 'diff', '--cached', '--name-only') == ''
    finally:
        rt.close()


def test_changed_file_or_push_destination_is_not_approved(repositories):
    repo, remote = repositories
    base = git(repo, 'rev-parse', 'HEAD')
    changed = repo / 'selected.txt'
    changed.write_bytes(b'proposed\n')
    root, plan, _ = prepare_commit(repo, [changed.name], 'Stale fixture')
    changed.write_bytes(b'changed after review\n')
    status, detail = apply_commit(root, plan)
    assert status == 'rejected' and 'changed after review' in detail
    assert not (repo / '.git' / 'index.lock').exists()
    git(repo, 'remote', 'set-url', '--push', 'origin', (repo.parent / 'other.git').as_posix())
    status, detail = apply_commit(root, plan)
    assert status == 'rejected' and 'push destination changed' in detail
    assert git(repo, 'rev-parse', 'HEAD') == git(remote, 'rev-parse', 'main') == base


def test_partial_staging_and_wildcard_selection_are_refused(repositories):
    repo, _ = repositories
    file = repo / 'selected.txt'
    file.write_bytes(b'staged\n')
    git(repo, 'add', file.name)
    file.write_bytes(b'working\n')
    root, plan, _ = prepare_commit(repo, [file.name], 'Partial staging fixture')
    status, detail = apply_commit(root, plan)
    assert status == 'rejected' and 'partial staging' in detail
    assert git(repo, 'show', ':selected.txt') == 'staged'
    with pytest.raises(GitError):
        prepare_commit(repo, ['*.txt'], 'Not a glob')
