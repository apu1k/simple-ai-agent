from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest

from editing.store import EditStore


def test_concurrent_proposals_get_unique_ids_and_pending_snapshots(tmp_path):
    store = EditStore()
    barrier = Barrier(8)

    def propose(index):
        barrier.wait(timeout=3)
        proposal, _ = store.propose_create(tmp_path / f"{index}.txt", str(index))
        snapshot = store.pending()
        assert proposal.id in snapshot
        return proposal.id

    with ThreadPoolExecutor(max_workers=8) as pool:
        identities = list(pool.map(propose, range(8)))
    assert sorted(identities) == list(range(1, 9))
    assert len(store.pending()) == 8
    assert not list(tmp_path.iterdir())


def test_two_approvals_cannot_write_the_same_proposal_twice(tmp_path, monkeypatch):
    store = EditStore()
    target = tmp_path / "once.txt"
    proposal, _ = store.propose_create(target, "once")
    entered, release, attempted = Event(), Event(), Event()
    writes = []
    write_lock = Lock()
    original_write = Path.write_text

    def held_write(path, *args, **kwargs):
        if path == target:
            with write_lock:
                writes.append(path)
            entered.set()
            assert release.wait(5)
        return original_write(path, *args, **kwargs)

    def second_approval():
        attempted.set()
        return store.approve(proposal.id)

    monkeypatch.setattr(Path, "write_text", held_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(store.approve, proposal.id)
        try:
            assert entered.wait(2)
            second = pool.submit(second_approval)
            assert attempted.wait(2)
        finally:
            release.set()
        assert "Applied" in first.result(timeout=2)
        with pytest.raises(ValueError, match="already applied"):
            second.result(timeout=2)
    assert writes == [target]
    assert target.read_text(encoding="utf-8") == "once"
    assert not store.pending()
