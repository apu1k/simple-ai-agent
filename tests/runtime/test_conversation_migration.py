"""Migration rollback must preserve the legacy database, including its schema."""
import json
import sqlite3

import pytest

from runtime.chat_store import ChatStore
from runtime.conversation_store import ConversationStorage
from runtime.persistence import PersistenceError, RuntimeStore
from tests.runtime.conversation_helpers import make_manager
from tests.runtime_helpers import make_runtime


@pytest.mark.parametrize("failure", ["malformed", "delete_denied"])
def test_failed_migration_rolls_back_schema_data_and_version_and_releases_writer(tmp_path, failure):
    path = tmp_path / "state.sqlite3"
    runtime, _ = make_runtime(tmp_path, persistence_path=path)
    runtime.submit("legacy state must survive")
    assert runtime.wait_for_idle(2)
    runtime.close()
    with sqlite3.connect(path) as db:
        if failure == "malformed":
            db.execute("UPDATE checkpoint SET payload='{}'")
        else:
            db.execute("CREATE TRIGGER deny_delete BEFORE DELETE ON checkpoint BEGIN SELECT RAISE(ABORT,'offline migration failure'); END")
        before = db.execute("SELECT payload FROM checkpoint").fetchone()[0]
    with pytest.raises(PersistenceError):
        ConversationStorage(path, ChatStore(tmp_path / "history"))
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT payload FROM checkpoint").fetchone()[0] == before
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_meta'").fetchone()
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='chat_checkpoints'").fetchone()
    store = RuntimeStore(path)
    try:
        assert store.load() == json.loads(before)
    finally:
        store.close()


def test_migrated_database_refuses_single_runtime_downgrade(tmp_path):
    manager, _ = make_manager(tmp_path, durable=True)
    manager.close()
    store = RuntimeStore(tmp_path / "state.sqlite3")
    try:
        with pytest.raises(PersistenceError) as refused:
            store.load()
        assert "single-chat downgrade" in str(refused.value.__cause__)
    finally:
        store.close()
