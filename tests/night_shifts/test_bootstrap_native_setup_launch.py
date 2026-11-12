"""Fixed snapshot/reconciliation models; all observed pins are TEST data only."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import struct
from pathlib import Path

import pytest

from night_shifts import bootstrap_native_setup as setup
from night_shifts import bootstrap_native_setup_launch as launch
from tests.night_shifts.test_bootstrap_native_setup import references
from tests.night_shifts.test_bootstrap_native_setup_build import profile

ROOT = Path(__file__).resolve().parents[2]
ID = 'c' * 32


def review(*, publish=False):
    template = (ROOT / 'scripts/native_validator_setup_handoff.ps1').read_bytes()
    return {'version': 1, 'scope': launch.SCOPE, 'host_profile': profile(publish=publish),
        'host_pin': {'bytes': 123, 'sha256': 'a' * 64}, 'watchdog_pin': {'bytes': 456, 'sha256': 'b' * 64},
        'template_pin': {'bytes': len(template), 'sha256': hashlib.sha256(template).hexdigest()},
        'outer_helper_sha256': 'd' * 64}, template


def observation(p):
    hp = p['host_profile']
    _, digest = launch._policy(p)
    raw = b'NVSR0001' + bytes([int(hp['operation'] == 'publish')]) + bytes.fromhex(digest)
    raw += struct.pack('<7Q', *(references()['indices'][n] for n in setup.ANCHORS))
    receipt = dict(version=1, scope=launch.RECEIPT_SCOPE, attempt_id=hp['attempt_id'], profile_sha256=digest,
        empty_job_observed=True, end='RootExited', exit_code=0, process_id=7,
        result_sha256=hashlib.sha256(raw).hexdigest(), result_valid=True)
    outer = dict(version=1, operation='elevated_commands', request_id=ID, helper_sha256=p['outer_helper_sha256'],
        status='completed', executed=True, effects_verified=False, retry_authorized=False, output_truncated=False,
        exit_code=0, stderr='', process_tree_observed=True)
    return outer, raw, receipt


def frame(outer, raw, receipt):
    data = receipt if type(receipt) is bytes else json.dumps(receipt, separators=(',', ':')).encode('ascii')
    return dict(outer, stdout='NVSO0001|' + base64.b64encode(raw).decode('ascii') + '|' + base64.b64encode(data).decode('ascii') + '\n')


@pytest.mark.parametrize('publish', [False, True])
def test_complete_snapshot_has_fixed_inputs_original_transport_and_permanent_claim(publish):
    p, template = review(publish=publish)
    frozen = launch.prepare_setup_handoff(p, template=template, request_id=ID, deadline_unix=1500)
    assert frozen.seconds == 20 and frozen.working_directory == r'C:\SetupHost'
    assert '__REVIEW_DATA__' not in frozen.script and len(frozen.script.encode('utf-8')) <= 32768
    start = "FromBase64String('"
    encoded = frozen.script.split(start, 1)[1].split("')", 1)[0]
    data = json.loads(base64.b64decode(encoded))
    assert data['request_id'] == ID and data['deadline_unix'] == 1500
    assert data['files']['validator-setup-watchdog.exe'] == p['watchdog_pin']
    assert ('setup.packet' in data['files']) == publish
    assert set(data['files']) == {'policy.json', 'validator-setup-host.exe', 'validator-setup-host.exe.config',
        'validator-setup-watchdog.exe', 'validator-setup-watchdog.exe.config', *(['setup.packet'] if publish else [])}
    claim = json.loads(base64.b64decode(data['outer_claim']))
    assert claim['scope'] == 'setup_outer_attempt_consumed_not_acceptance'
    assert claim['policy_sha256'] == data['files']['policy.json']['sha256']
    assert frozen == launch.prepare_setup_handoff(copy.deepcopy(p), template=template, request_id=ID, deadline_unix=1500)


@pytest.mark.parametrize('fault', ['template_bytes', 'template_pin', 'host_pin', 'watchdog_pin', 'helper', 'extra',
    'request', 'deadline_bool', 'deadline_zero', 'scope', 'version', 'profile'])
def test_invalid_review_cannot_emit_a_script(fault):
    p, template = review()
    identity, until = ID, 1500
    if fault == 'template_bytes':
        template += b'changed'
    elif fault == 'template_pin':
        p['template_pin']['sha256'] = '0' * 64
    elif fault in ('host_pin', 'watchdog_pin'):
        p[fault]['bytes'] = True
    elif fault == 'helper':
        p['outer_helper_sha256'] = 'D' * 64
    elif fault == 'extra':
        p['command'] = 'injected'
    elif fault == 'request':
        identity = 'A' * 32
    elif fault == 'deadline_bool':
        until = True
    elif fault == 'deadline_zero':
        until = 0
    elif fault == 'scope':
        p['scope'] = 'authorized'
    elif fault == 'version':
        p['version'] = True
    else:
        p['host_profile']['operation'] = 'shell'
    with pytest.raises(launch.SetupLaunchRefused):
        launch.prepare_setup_handoff(p, template=template, request_id=identity, deadline_unix=until)


@pytest.mark.parametrize('publish', [False, True])
def test_success_is_only_a_bound_observation_never_acceptance_or_provisioning(publish):
    p, _ = review(publish=publish)
    outer, raw, receipt = observation(p)
    result = launch.reconcile_setup_handoff(p, request_id=ID, outer=frame(outer, raw, receipt))
    assert result['status'] == 'setup_observed_not_accepted'
    assert result['references'] == references()
    assert result['accepted'] is result['provisioning_authorized'] is result['retry_authorized'] is False
    assert result['gate_a'] == 'unrun'


@pytest.mark.parametrize('field,bad', [('version', True), ('request_id', 'e' * 32), ('operation', 'inspect_image_copy'),
    ('helper_sha256', 'e' * 64), ('status', 'timeout_outcome_unknown'), ('status', 'outcome_unknown'),
    ('executed', None), ('executed', False), ('effects_verified', True), ('retry_authorized', True),
    ('output_truncated', True), ('exit_code', True), ('exit_code', 124), ('stderr', 'diagnostic'),
    ('process_tree_observed', False), ('process_tree_observed', 1), ('process_tree_observed', None)])
def test_outer_faults_cannot_promote_even_a_complete_inner_receipt(field, bad):
    p, _ = review()
    outer, raw, receipt = observation(p)
    outer[field] = bad
    with pytest.raises(launch.SetupLaunchRefused):
        launch.reconcile_setup_handoff(p, request_id=ID, outer=frame(outer, raw, receipt))


@pytest.mark.parametrize('field,bad', [('version', True), ('scope', 'accepted'), ('attempt_id', 'e' * 32),
    ('profile_sha256', 'e' * 64), ('empty_job_observed', False), ('empty_job_observed', 1),
    ('result_valid', False), ('result_valid', 1), ('end', 'DeadlineStopped'), ('end', 'ResidualTreeStopped'),
    ('exit_code', True), ('exit_code', 1), ('process_id', True), ('process_id', 0), ('process_id', 2**32),
    ('result_sha256', 'e' * 64)])
def test_inner_faults_cannot_promote_exit_zero(field, bad):
    p, _ = review()
    outer, raw, receipt = observation(p)
    receipt[field] = bad
    with pytest.raises(launch.SetupLaunchRefused):
        launch.reconcile_setup_handoff(p, request_id=ID, outer=frame(outer, raw, receipt))


@pytest.mark.parametrize('fault', ['short', 'trailer', 'magic', 'phase', 'digest', 'indices_alias', 'indices_zero',
    'parent_alias', 'receipt_duplicate', 'receipt_extra', 'base64', 'multiple_frames', 'extra_text', 'oversize'])
def test_frame_and_identity_faults_remain_unknown(fault):
    p, _ = review()
    outer, raw, receipt = observation(p)
    if fault in ('short', 'trailer'):
        raw = raw[:-1] if fault == 'short' else raw + b'x'
    elif fault in ('magic', 'phase', 'digest'):
        offset = {'magic': 0, 'phase': 8, 'digest': 9}[fault]
        raw = raw[:offset] + bytes([raw[offset] ^ 1]) + raw[offset + 1:]
    elif fault.startswith('indices_') or fault == 'parent_alias':
        ids = list(struct.unpack('<7Q', raw[41:]))
        ids[0] = ids[1] if fault == 'indices_alias' else (0 if fault == 'indices_zero' else p['host_profile']['parent']['identity']['index'])
        raw = raw[:41] + struct.pack('<7Q', *ids)
    elif fault == 'receipt_duplicate':
        receipt = json.dumps(receipt).replace('"version": 1', '"version": 1, "version": 1').encode('ascii')
    elif fault == 'receipt_extra':
        receipt['accepted'] = True
    data = frame(outer, raw, receipt)
    if fault == 'base64':
        data['stdout'] = data['stdout'].replace('|', '|!', 1)
    elif fault == 'multiple_frames':
        data['stdout'] *= 2
    elif fault == 'extra_text':
        data['stdout'] = 'accepted\n' + data['stdout']
    elif fault == 'oversize':
        data['stdout'] = 'x' * 4001 + '\n'
    with pytest.raises(launch.SetupLaunchRefused):
        launch.reconcile_setup_handoff(p, request_id=ID, outer=data)


def test_legacy_outer_completion_has_no_implicit_process_tree_evidence():
    p, _ = review()
    outer, raw, receipt = observation(p)
    del outer['process_tree_observed']
    with pytest.raises(launch.SetupLaunchRefused, match='handoff_outer'):
        launch.reconcile_setup_handoff(p, request_id=ID, outer=frame(outer, raw, receipt))


def test_publication_requires_exact_separately_reviewed_anchor_identities():
    p, _ = review(publish=True)
    outer, raw, receipt = observation(p)
    ids = list(struct.unpack('<7Q', raw[41:]))
    ids[0] += 10000
    raw = raw[:41] + struct.pack('<7Q', *ids)
    receipt['result_sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(launch.SetupLaunchRefused, match='published_identity'):
        launch.reconcile_setup_handoff(p, request_id=ID, outer=frame(outer, raw, receipt))


def test_template_keeps_preload_claim_and_uncertain_owner_and_has_no_compile_or_cleanup_route():
    _, raw = review()
    text = raw.decode('ascii')
    assert text.index('$writer = New-Object IO.FileStream') < text.index('$child = [Diagnostics.Process]::Start')
    assert text.index('foreach ($item in $pins)') < text.index('$entered = $true')
    assert 'while ($true) { [Threading.Thread]::Sleep(1000)' in text
    assert 'execution_qpc_limit' in text and 'RunWithin' not in text
    assert 'UseShellExecute = $false' in text and '$info.EnvironmentVariables.Clear()' in text
    for forbidden in ('Add-Type', 'Invoke-Expression', 'Start-Process', 'Remove-Item', 'Set-Acl', 'TerminateProcess', '.Kill('):
        assert forbidden not in text


def test_required_handoff_template_has_an_explicit_repository_include_rule():
    # Prevent a local-only ignored dependency from passing every native fixture
    # but disappearing from the commit/next checkout.
    rules = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    assert '!/scripts/native_validator_setup_handoff.ps1' in rules
    assert (ROOT / 'scripts/native_validator_setup_handoff.ps1').is_file()
