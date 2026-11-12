"""Reject inconsistent receipts and expire approvals without privileged work."""
import copy

import pytest

from runtime.elevated_commands import validate_receipt
from runtime.privileged_host import PrivilegedHostError
from runtime.privileged_turn import ELEVATED_OPERATION, PrivilegedClaim, PrivilegedTurn

ID = 'a' * 32


def receipt():
    return dict(version=1, request_id=ID, operation=ELEVATED_OPERATION,
                request_sha256='b' * 64, helper_sha256='c' * 64, status='completed',
                executed=True, effects_verified=False, exit_code=0,
                stdout='fixture', stderr='', output_truncated=False, retry_authorized=False)


@pytest.mark.parametrize('field,value', [
    ('version', True), ('request_id', 'd' * 32), ('operation', 'inspect_image_copy'),
    ('request_sha256', 'd' * 64), ('helper_sha256', 'd' * 64), ('executed', None),
    ('effects_verified', True), ('exit_code', 7), ('exit_code', False),
    ('output_truncated', 1), ('retry_authorized', True), ('stdout', []),
])
def test_invalid_receipt_cannot_claim_completion(field, value):
    data = receipt()
    data[field] = value
    with pytest.raises(PrivilegedHostError):
        validate_receipt(data, PrivilegedClaim(ID, 1000, ELEVATED_OPERATION), 'b' * 64, 'c' * 64)


def test_unknown_execution_and_timeout_remain_unverified():
    claim = PrivilegedClaim(ID, 1000, ELEVATED_OPERATION)
    data = receipt()
    validate_receipt(data, claim, 'b' * 64, 'c' * 64)
    data.update(status='outcome_unknown', executed=None, exit_code=None)
    validate_receipt(data, claim, 'b' * 64, 'c' * 64)
    data.update(status='timeout_outcome_unknown', executed=True, exit_code=124)
    validate_receipt(data, claim, 'b' * 64, 'c' * 64)
    broken = copy.deepcopy(data)
    broken['exit_code'] = 0
    with pytest.raises(PrivilegedHostError):
        validate_receipt(broken, claim, 'b' * 64, 'c' * 64)


@pytest.mark.parametrize('status,executed,code', [
    ('completed', True, 0), ('failed', True, 7), ('timeout_outcome_unknown', True, 124),
    ('outcome_unknown', None, None),
])
@pytest.mark.parametrize('observed', ['absent', True, False, None, 1, 'true'])
def test_new_tree_observation_is_strict_and_legacy_data_never_implies_it(status, executed, code, observed):
    claim = PrivilegedClaim(ID, 1000, ELEVATED_OPERATION)
    data = receipt()
    data.update(status=status, executed=executed, exit_code=code)
    if observed != 'absent':
        data['process_tree_observed'] = observed
    valid = observed == 'absent' or (observed is False if status == 'outcome_unknown' else observed is True)
    if valid:
        validate_receipt(data, claim, 'b' * 64, 'c' * 64)
        assert ('process_tree_observed' in data) == (observed != 'absent')
    else:
        with pytest.raises(PrivilegedHostError, match='observation|receipt'):
            validate_receipt(data, claim, 'b' * 64, 'c' * 64)


def test_accepted_request_expires_and_changed_review_cannot_execute():
    now = [0.0]
    permit = PrivilegedTurn(clock=lambda: now[0], wall_clock=lambda: 1000.0)
    permit.arm(ELEVATED_OPERATION)
    with permit.turn('head'):
        request = permit.submit(permit.claim(ELEVATED_OPERATION), {'script': 'fixture'})
        permit.decide(request.id, accept=True)
        from dataclasses import replace
        with pytest.raises(PermissionError):
            permit.require_accepted(replace(request, review_json='different'))
        now[0] += 1800
        assert permit.wait(request) == 'expired'
        with pytest.raises(PermissionError):
            permit.require_accepted(request)
    assert permit.status == 'disabled'
