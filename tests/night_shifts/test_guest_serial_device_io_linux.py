"""Native Linux PTY tests plus portable exact-child supervisor regressions.

Windows skips are NOT native Linux passes. All actual tty operations run in a
fresh child and target only its newly created PTY, never /dev/ttyS0.
"""
from __future__ import annotations

import json
import sys
import time

import pytest

from tests.night_shifts.linux_serial_native_fixture import (
    SERIAL_CASES,
    decode_receipt,
    run_case,
)


@pytest.mark.skipif(sys.platform != "linux", reason="native Linux disposable PTY required")
@pytest.mark.parametrize("case", SERIAL_CASES)
def test_native_linux_pty_serial_case(case):
    report = run_case(case)
    assert report["native"] is True
    assert report["released"] is True and report["restored"] is True
    if case in ("silent_read", "stalled_write", "cancel_read", "cancel_write", "shared_deadline"):
        assert report["polls"] > 0
    if case in ("stalled_write", "cancel_write"):
        assert 0 < report["accepted"] < 1024 * 1024


def test_fixture_supervisor_receives_only_after_normal_exact_child_exit():
    report = run_case("fixture_ok")
    assert report == dict(case="fixture_ok", state="passed", native=False, released=True,
                          restored=True, polls=0, accepted=0)


@pytest.mark.parametrize("case,label", [
    ("fixture_failure", "fixture_receipt_invalid"),
    ("fixture_malformed", "fixture_receipt_invalid"),
    ("fixture_missing", "fixture_receipt_missing"),
])
def test_fixture_supervisor_refuses_failure_bad_or_missing_receipt(case, label):
    with pytest.raises(RuntimeError, match=f"^{label}$"):
        run_case(case)


def test_fixture_supervisor_forced_termination_never_counts_as_native_success():
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="^fixture_required_termination$"):
        run_case("fixture_hang", timeout=0.5)
    assert time.monotonic() - started < 7


@pytest.mark.parametrize("fault", [
    "extra", "case", "state", "native", "released", "restored", "polls_bool", "polls_limit",
    "accepted_bool", "accepted_limit", "duplicate", "oversize", "encoding", "array",
])
def test_fixture_receipt_schema_refuses_ambiguity_and_unverified_success(fault):
    value = dict(case="fixture_ok", state="passed", native=False, released=True, restored=True,
                 polls=0, accepted=0)
    if fault in ("case", "state"):
        value[fault] = "unexpected"
    elif fault == "extra":
        value["unexpected"] = True
    elif fault == "native":
        value["native"] = True
    elif fault in ("released", "restored"):
        value[fault] = False
    elif fault == "polls_bool":
        value["polls"] = True
    elif fault == "polls_limit":
        value["polls"] = 10001
    elif fault == "accepted_bool":
        value["accepted"] = True
    elif fault == "accepted_limit":
        value["accepted"] = 4 * 1024 * 1024 + 1
    raw = json.dumps(value).encode("ascii")
    if fault == "duplicate":
        raw = b'{"case":"fixture_ok",' + raw[1:]
    elif fault == "oversize":
        raw = b" " * 1025
    elif fault == "encoding":
        raw = b"\xff"
    elif fault == "array":
        raw = b"[]"
    with pytest.raises(RuntimeError, match="^fixture_receipt_invalid$"):
        decode_receipt(raw, "fixture_ok")


@pytest.mark.parametrize("case,timeout", [
    ("not_a_case", 1), ("fixture_ok", True), ("fixture_ok", 0),
    ("fixture_ok", 16), ("fixture_ok", float("nan")),
])
def test_fixture_invalid_inputs_refuse_before_spawn(case, timeout):
    with pytest.raises(ValueError):
        run_case(case, timeout=timeout)
