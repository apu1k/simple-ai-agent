from pathlib import Path

import pytest

from night_shifts.artifacts import ArtifactCollector, ArtifactRetrievalError
from night_shifts.guest.artifacts import ArtifactWriter
from night_shifts.storage import ArtifactStore


def collector(tmp_path: Path, **limits: int) -> ArtifactCollector:
    return ArtifactCollector(
        tmp_path / "trusted-artifacts",
        ArtifactStore(tmp_path / "operations.sqlite3"),
        **limits,
    )


def test_collector_copies_hashes_and_records_guest_artifact(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    staged = ArtifactWriter(staging).write_text(
        name="pytest.txt",
        kind="test-log",
        content="2 passed\n",
    )
    store = ArtifactStore(tmp_path / "operations.sqlite3")
    artifacts = ArtifactCollector(tmp_path / "trusted-artifacts", store)

    records = artifacts.collect(
        job_id="a" * 32,
        staging_root=staging,
        references=[staged.reference],
    )

    assert len(records) == 1
    assert Path(records[0].path).read_text(encoding="utf-8") == "2 passed\n"
    assert records[0].sha256 == staged.sha256
    assert store.list("a" * 32) == list(records)


@pytest.mark.parametrize(
    "reference",
    ["../escape", "guest-artifact/../escape", "guest-artifact/a/b", "/absolute"],
)
def test_collector_rejects_untrusted_references(tmp_path: Path, reference: str) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(ArtifactRetrievalError, match="reference"):
        collector(tmp_path).collect(
            job_id="b" * 32,
            staging_root=staging,
            references=[reference],
        )


def test_collector_rejects_symlinks_when_supported(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("secret", encoding="utf-8")
    link = staging / "report.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("test account cannot create symlinks")

    with pytest.raises(ArtifactRetrievalError, match="regular file"):
        collector(tmp_path).collect(
            job_id="c" * 32,
            staging_root=staging,
            references=["guest-artifact/report.txt"],
        )


def test_collector_enforces_file_and_total_limits(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "one.txt").write_text("1234", encoding="utf-8")
    (staging / "two.txt").write_text("5678", encoding="utf-8")
    store = ArtifactStore(tmp_path / "operations.sqlite3")
    artifacts = ArtifactCollector(
        tmp_path / "trusted-artifacts",
        store,
        max_files=2,
        max_file_bytes=5,
        max_total_bytes=6,
    )

    with pytest.raises(ArtifactRetrievalError, match="total size"):
        artifacts.collect(
            job_id="d" * 32,
            staging_root=staging,
            references=["guest-artifact/one.txt", "guest-artifact/two.txt"],
        )

    assert store.list("d" * 32) == []
    assert not (tmp_path / "trusted-artifacts" / ("d" * 32)).exists()
