from pathlib import Path

import pytest

from night_shifts.guest.artifacts import ArtifactPolicyError, ArtifactWriter


def writer(tmp_path: Path, **limits: int) -> ArtifactWriter:
    root = tmp_path / "artifacts"
    root.mkdir()
    return ArtifactWriter(root, **limits)


def test_artifact_writer_stages_bounded_hashed_exclusive_files(tmp_path: Path) -> None:
    artifacts = writer(tmp_path)

    artifact = artifacts.write_text(
        name="pytest.txt",
        kind="test-log",
        content="1 passed\n",
    )

    assert artifact.reference == "guest-artifact/pytest.txt"
    assert artifact.size_bytes == 9
    assert len(artifact.sha256) == 64
    assert (tmp_path / "artifacts" / "pytest.txt").read_text(encoding="utf-8") == "1 passed\n"
    assert artifacts.artifacts == (artifact,)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "UPPER", "a/b", "a\\b", ""])
def test_artifact_writer_rejects_untrusted_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ArtifactPolicyError, match="name"):
        writer(tmp_path).write_text(name=name, kind="report", content="content")


def test_artifact_writer_enforces_kind_size_total_count_and_uniqueness(tmp_path: Path) -> None:
    artifacts = writer(tmp_path, max_files=2, max_file_bytes=5, max_total_bytes=8)

    with pytest.raises(ArtifactPolicyError, match="kind"):
        artifacts.write_text(name="bad.txt", kind="patch", content="x")
    with pytest.raises(ArtifactPolicyError, match="file size"):
        artifacts.write_text(name="large.txt", kind="report", content="123456")

    artifacts.write_text(name="one.txt", kind="report", content="1234")
    with pytest.raises(ArtifactPolicyError, match="unique"):
        artifacts.write_text(name="one.txt", kind="report", content="x")
    artifacts.write_text(name="two.txt", kind="analysis", content="1234")
    with pytest.raises(ArtifactPolicyError, match="count"):
        artifacts.write_text(name="three.txt", kind="metadata", content="")
