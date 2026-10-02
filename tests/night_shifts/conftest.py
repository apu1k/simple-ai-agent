"""Explicit ACL-model substitution only for the four fake preparation modules."""

from __future__ import annotations

import pytest

_FAKE_PREPARATION_MODULES = frozenset({
    "test_ubuntu_image_preparation.py", "test_ubuntu_seed_attachment.py",
    "test_ubuntu_preparation_launch.py", "test_ubuntu_preparation_retirement.py",
})


@pytest.fixture(autouse=True)
def fake_preparation_acl_model(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic files/fake hosts do not constitute native Windows ACL evidence.

    No substitution for the control-policy/native-reader tests or real-host
    opt-in module. Production code never selects this model from a runner.
    """
    if request.node.path.name in _FAKE_PREPARATION_MODULES:
        monkeypatch.setattr(
            "night_shifts.ubuntu_preparation_control._check_control_permissions",
            lambda path: None,
        )
