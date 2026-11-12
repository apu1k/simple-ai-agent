"""Fixed outer-snapshot data and STRICT setup observation reconciliation.

No I/O, process, pin discovery, approval or installation. Independent template,
helper, host/watchdog and platform/load review precede use. Matching observed
hashes never supply that review. Transported exit/receipt data is not acceptance.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import struct
from dataclasses import dataclass
from typing import cast

from night_shifts import bootstrap_native_install_request as request
from night_shifts import bootstrap_native_setup as setup
from night_shifts import bootstrap_native_setup_build as build

SCOPE = 'reviewed_setup_outer_handoff_not_authorization'
PLACEHOLDER = b'__REVIEW_DATA__'
MODE = '--setup-supervise-qpc-v1'
RECEIPT_SCOPE = 'local_setup_process_observations_not_acceptance'


class SetupLaunchRefused(RuntimeError):
    """Fixed label only; no automatic retry, cleanup, acceptance or pin promotion."""


@dataclass(frozen=True)
class SetupHandoff:
    """Immutable explicit review script; NEVER execute it outside protected review."""

    script: str
    seconds: int
    working_directory: str


def _pin(raw: bytes) -> dict[str, object]:
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _review(value: object) -> dict[str, object]:
    try:
        p = request._fields(value, ('version', 'scope', 'host_profile', 'host_pin', 'watchdog_pin',
            'template_pin', 'outer_helper_sha256'))
        request._number(p['version'], 1, 1)
        if type(p['scope']) is not str or p['scope'] != SCOPE:
            raise SetupLaunchRefused('handoff_scope')
        build.setup_host_binding(p['host_profile'])
        for name, maximum in (('host_pin', 16 * 1024**2), ('watchdog_pin', 16 * 1024**2), ('template_pin', 24000)):
            request._pin(p[name], maximum)
        digest = p['outer_helper_sha256']
        if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise SetupLaunchRefused('handoff_helper_pin')
        return p
    except (request.InstallRequestRefused, build.SetupBuildRefused, setup.SetupRefused):
        raise SetupLaunchRefused('handoff_review') from None


def _policy(p: dict[str, object]) -> tuple[bytes, str]:
    profile = cast(dict[str, object], p['host_profile'])
    count, digest = request._pin(p['host_pin'], 16 * 1024**2)
    profile_sha = hashlib.sha256(build.setup_host_binding(profile)).hexdigest()
    raw = (f'{{"host_bytes":{count},"host_sha256":"{digest}","profile_sha256":"{profile_sha}",'
        '"scope":"protected_setup_operation_approval_once","version":1}\n').encode('ascii')
    return raw, profile_sha


def prepare_setup_handoff(value: object, *, template: bytes, request_id: str, deadline_unix: int) -> SetupHandoff:
    """Freeze the complete fixed script and independent data for existing UI/UAC.

    There are no commands/entry/path selectors beyond the reviewed fixed profile.
    Template/helper pins MUST be independent review inputs, never discovered here.
    The protected command helper must implement original-window start records.
    Old deployments refuse in the snapshot; source application installs nothing.
    """
    try:
        p = _review(value)
        count, digest = request._pin(p['template_pin'], 24000)
        if type(template) is not bytes or len(template) != count or hashlib.sha256(template).hexdigest() != digest or template.count(PLACEHOLDER) != 1:
            raise SetupLaunchRefused('handoff_template_pin')
        if type(request_id) is not str or len(request_id) != 32 or any(c not in '0123456789abcdef' for c in request_id):
            raise SetupLaunchRefused('handoff_request')
        request._number(deadline_unix, 1, 253402300799)
        profile = cast(dict[str, object], p['host_profile'])
        host = cast(dict[str, object], profile['host_anchor'])
        root = cast(str, host['path'])
        policy, profile_sha = _policy(p)
        claim = (f'{{"policy_sha256":"{hashlib.sha256(policy).hexdigest()}","profile_sha256":"{profile_sha}",'
            '"scope":"setup_outer_attempt_consumed_not_acceptance","version":1}\n').encode('ascii')
        files = {'policy.json': _pin(policy), 'validator-setup-host.exe': p['host_pin'],
            'validator-setup-host.exe.config': _pin(request._CONFIG), 'validator-setup-watchdog.exe': p['watchdog_pin'],
            'validator-setup-watchdog.exe.config': _pin(request._CONFIG)}
        if profile['operation'] == 'publish':
            files['setup.packet'] = profile['packet']
        data = dict(request_id=request_id, deadline_unix=deadline_unix, seconds=profile['budget_seconds'],
            expires_unix=profile['expires_unix'], operator_sid=profile['operator_sid'], root=root,
            publish=profile['operation'] == 'publish', outer_helper_sha256=p['outer_helper_sha256'],
            files=files, outer_claim=base64.b64encode(claim).decode('ascii'))
        encoded = base64.b64encode(json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii'))
        script = template.replace(PLACEHOLDER, encoded).decode('ascii')
        if len(script.encode('utf-8')) > 32768:
            raise SetupLaunchRefused('handoff_script_bound')
        return SetupHandoff(script, cast(int, profile['budget_seconds']), root)
    except (request.InstallRequestRefused, UnicodeError, ValueError, TypeError, OverflowError):
        raise SetupLaunchRefused('handoff_data') from None


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def _b64(value: str, maximum: int) -> bytes:
    if len(value) > (maximum + 2) // 3 * 4:
        raise SetupLaunchRefused('handoff_frame_bound')
    raw = base64.b64decode(value, validate=True)
    if len(raw) > maximum or base64.b64encode(raw).decode('ascii') != value:
        raise SetupLaunchRefused('handoff_frame_encoding')
    return raw


def reconcile_setup_handoff(value: object, *, request_id: str, outer: object) -> dict[str, object]:
    """Evaluate already-authenticated outer receipt DATA. Never read/retry/repair.

    Caller MUST first authenticate the protected general receipt and exact frozen
    request via runtime.elevated_commands. This pure function cannot do that.
    Missing, failed, truncated or incoherent observations are UNKNOWN, not absence.
    """
    try:
        p = _review(value)
        if type(outer) is not dict:
            raise SetupLaunchRefused('handoff_outer')
        o = cast(dict[str, object], outer)
        if (type(o.get('version')) is not int or o['version'] != 1 or o.get('request_id') != request_id
                or o.get('operation') != 'elevated_commands' or o.get('helper_sha256') != p['outer_helper_sha256']
                or o.get('status') != 'completed' or o.get('executed') is not True or o.get('effects_verified') is not False
                or o.get('retry_authorized') is not False or o.get('output_truncated') is not False
                or o.get('process_tree_observed') is not True or o.get('lifetime_observed') is not True
                or type(o.get('exit_code')) is not int or o['exit_code'] != 0 or o.get('stderr') != ''):
            raise SetupLaunchRefused('handoff_outer')
        stdout = o.get('stdout')
        if type(stdout) is not str or not 1 <= len(stdout) <= 4000 or not stdout.endswith('\n'):
            raise SetupLaunchRefused('handoff_frame')
        fields = stdout.removesuffix('\n').removesuffix('\r').split('|')
        if len(fields) != 3 or fields[0] != 'NVSO0001':
            raise SetupLaunchRefused('handoff_frame')
        result, receipt = _b64(fields[1], 97), _b64(fields[2], 2048)
        profile = cast(dict[str, object], p['host_profile'])
        _, profile_sha = _policy(p)
        expected_header = b'NVSR0001' + bytes([int(profile['operation'] == 'publish')]) + bytes.fromhex(profile_sha)
        if len(result) != 97 or result[:41] != expected_header:
            raise SetupLaunchRefused('handoff_result_binding')
        indices = dict(zip(setup.ANCHORS, struct.unpack('<7Q', result[41:]), strict=True))
        refs = {'version': 1, 'scope': setup.SCOPE, 'operator_sid': profile['operator_sid'], 'parent': profile['parent'], 'indices': indices}
        setup._references(refs)
        if profile['operation'] == 'publish' and refs != profile['references']:
            raise SetupLaunchRefused('handoff_published_identity')
        r = request._fields(json.loads(receipt.decode('ascii'), object_pairs_hook=_unique),
            ('version', 'scope', 'attempt_id', 'profile_sha256', 'empty_job_observed', 'end', 'exit_code', 'process_id', 'result_sha256', 'result_valid'))
        if (type(r['version']) is not int or r['version'] != 1 or r['scope'] != RECEIPT_SCOPE
                or r['attempt_id'] != profile['attempt_id'] or r['profile_sha256'] != profile_sha
                or r['empty_job_observed'] is not True or r['result_valid'] is not True
                or r['end'] != 'RootExited' or type(r['exit_code']) is not int or r['exit_code'] != 0
                or type(r['process_id']) is not int or not 1 <= r['process_id'] <= 2**32 - 1
                or r['result_sha256'] != hashlib.sha256(result).hexdigest()):
            raise SetupLaunchRefused('handoff_receipt_binding')
        return dict(status='setup_observed_not_accepted', scope='protected_transport_setup_observations_not_acceptance',
            request_id=request_id, operation=profile['operation'], profile_sha256=profile_sha,
            references=refs, accepted=False, provisioning_authorized=False, gate_a='unrun', retry_authorized=False)
    except (request.InstallRequestRefused, setup.SetupRefused, UnicodeError, ValueError, TypeError, KeyError, binascii.Error):
        raise SetupLaunchRefused('handoff_observation_unknown') from None
