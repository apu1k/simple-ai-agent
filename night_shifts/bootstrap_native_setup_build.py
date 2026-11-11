"""Closed setup HOST/watchdog build data, never I/O, approval or installation.

Build/review the host FIRST. Its independent finished-byte pin enters only the
later watchdog. No observed-pin default or self/request hash cycle. Never elevate
checkout code; platform/builder load trust are external prerequisites.
"""
from __future__ import annotations

import hashlib
import struct
from typing import cast

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_install_request as request
from night_shifts import bootstrap_native_setup as setup

HOST_SCOPE = 'reviewed_setup_host_references_not_authorization'
HOST_BUILD_SCOPE = 'reviewed_setup_host_build_recipe_not_authorization'
WATCHDOG_BUILD_SCOPE = 'reviewed_setup_watchdog_build_recipe_not_authorization'
HOST_PROFILE_NAME = 'ReviewedSetupHost.g.cs'
WATCHDOG_PROFILE_NAME = 'ReviewedSetupSupervisor.g.cs'
HOST_SOURCES = (
    'native_validator_install_boundary.cs', 'native_validator_install_request.cs', 'native_validator_install_windows.cs',
    'native_validator_launch_boundary.cs', 'native_validator_launch_windows.cs', 'native_validator_process_guardian.cs',
    'native_validator_process_guardian_windows.cs', 'native_validator_section_boundary.cs', 'native_validator_setup.cs',
    'native_validator_setup_windows.cs', 'native_validator_setup_entry.cs', 'native_validator_setup_host_files.cs',
)
WATCHDOG_SOURCES = (*HOST_SOURCES, 'native_validator_setup_supervisor.cs', 'native_validator_setup_supervisor_windows.cs')


class SetupBuildRefused(RuntimeError):
    """Fixed-label consistency refusal, never installation/execution authority."""


def _host(value: object) -> dict[str, object]:
    p = request._fields(value, ('version', 'scope', 'operation', 'attempt_id', 'budget_seconds', 'expires_unix',
        'parent', 'operator_sid', 'host_anchor', 'references', 'packet'))
    request._number(p['version'], 1, 1)
    if (type(p['scope']) is not str or p['scope'] != HOST_SCOPE or type(p['operation']) is not str
            or p['operation'] not in ('prepare', 'publish')):
        raise SetupBuildRefused('setup_profile_scope')
    if type(p['attempt_id']) is not str or len(p['attempt_id']) != 32 or any(c not in '0123456789abcdef' for c in p['attempt_id']):
        raise SetupBuildRefused('setup_attempt')
    request._number(p['budget_seconds'], 6, 300)
    request._number(p['expires_unix'], 1, 253402300799)
    parent = request._fields(p['parent'], ('path', 'identity'))
    path = request._path(parent['path'], 150)
    pv, parent_index = request._identity(parent['identity'])
    host = request._fields(p['host_anchor'], ('path', 'identity', 'claims_index', 'receipts_index', 'scratch_index'))
    root = request._path(host['path'], 180)
    hv, index = request._identity(host['identity'])
    ids = [index, *(request._number(host[n], 1, 2**64 - 1) for n in ('claims_index', 'receipts_index', 'scratch_index'))]
    if len(set(ids)) != 4 or build._overlap(path, root):
        raise SetupBuildRefused('setup_host_overlap')
    request.build_validation_guardian_profile({'version': 1, 'scope': request.GUARDIAN_PROFILE_SCOPE,
        'operator_sid': p['operator_sid'], 'approval_anchor': {'path': path + '\\native-validator-bootstrap\\approval',
        'identity': parent['identity']}, 'launch_root': root})
    if p['operation'] == 'prepare':
        if p['references'] is not None or p['packet'] is not None:
            raise SetupBuildRefused('setup_prepare_profile')
    else:
        refs = request._fields(p['references'], ('version', 'scope', 'operator_sid', 'parent', 'indices'))
        setup._references(refs)
        if refs['parent'] != parent or refs['operator_sid'] != p['operator_sid']:
            raise SetupBuildRefused('setup_reference_binding')
        request._pin(p['packet'], setup.MAX_PACKET_BYTES)
    if hv == pv:
        reserved = {parent_index}
        if p['references'] is not None:
            reserved.update(cast(dict[str, int], cast(dict[str, object], p['references'])['indices']).values())
        if reserved.intersection(ids):
            raise SetupBuildRefused('setup_host_alias')
    return p


def setup_host_binding(value: object) -> bytes:
    """Canonical cross-language consistency binding, NOT an authenticator."""
    try:
        p = _host(value)
        parent = cast(dict[str, object], p['parent'])
        host = cast(dict[str, object], p['host_anchor'])
        pv, pi = request._identity(parent['identity'])
        hv, hi = request._identity(host['identity'])
        pieces = [struct.pack('<i', 1)]

        def text(v: object) -> None:
            raw = cast(str, v).encode('ascii')
            pieces.extend((struct.pack('<i', len(raw)), raw))

        text(p['operation'])
        text(p['operator_sid'])
        text(parent['path'])
        pieces.append(struct.pack('<IQ', pv, pi))
        text(host['path'])
        pieces.append(struct.pack('<IQQQQ', hv, hi, host['claims_index'], host['receipts_index'], host['scratch_index']))
        text(p['attempt_id'])
        pin = cast(dict[str, object] | None, p['packet'])
        pieces.append(struct.pack('<iqi', p['budget_seconds'], p['expires_unix'], 0 if pin is None else pin['bytes']))
        text('' if pin is None else pin['sha256'])
        indices = None if p['references'] is None else cast(dict[str, int], cast(dict[str, object], p['references'])['indices'])
        pieces.append(struct.pack('<' + 'Q' * 7, *(0 if indices is None else indices[n] for n in setup.ANCHORS)))
        return b''.join(pieces)
    except (request.InstallRequestRefused, setup.SetupRefused):
        raise SetupBuildRefused('setup_profile') from None


def emit_setup_host_profile(value: object) -> bytes:
    """Required memory-only C# DATA; no shipped/dummy/default profile."""
    try:
        p = _host(value)
        parent = cast(dict[str, object], p['parent'])
        host = cast(dict[str, object], p['host_anchor'])
        pv, pi = request._identity(parent['identity'])
        hv, hi = request._identity(host['identity'])
        pin = cast(dict[str, object] | None, p['packet'])
        refs = 'null'
        if p['references'] is not None:
            indices = cast(dict[str, int], cast(dict[str, object], p['references'])['indices'])
            refs = 'new SetupReferences(parent,new System.Collections.Generic.Dictionary<string,ulong>(System.StringComparer.Ordinal){' + ','.join(
                '{"' + n + '",' + str(indices[n]) + 'UL}' for n in setup.ANCHORS) + '})'
        raw = ('// GENERATED REVIEW DATA, not approval or pre-load trust.\nnamespace AiAgent.ValidatorSetup {\n'
            'internal static class ReviewedSetupHost { internal static SetupHostProfile Create() {\n'
            f'var parent=new SetupParent(@"{parent["path"]}",{pv}u,{pi}UL,"{p["operator_sid"]}");\n'
            f'var location=new SetupLocation(@"{host["path"]}",{hv}u,{hi}UL,{host["claims_index"]}UL,{host["receipts_index"]}UL,{host["scratch_index"]}UL);\n'
            f'return new SetupHostProfile(parent,location,"{p["attempt_id"]}","{p["operation"]}",{p["budget_seconds"]},{p["expires_unix"]}L,'
            f'{0 if pin is None else pin["bytes"]},"{"" if pin is None else pin["sha256"]}",{refs});\n'
            '} }\n}\n').encode('ascii')
        if len(raw) > 4096:
            raise SetupBuildRefused('setup_profile_bound')
        return raw
    except (request.InstallRequestRefused, setup.SetupRefused):
        raise SetupBuildRefused('setup_profile') from None


def emit_setup_watchdog_profile(host_pin: object) -> bytes:
    """Host FINISHED pin must be independently reviewed, never discovered here."""
    try:
        count, digest = request._pin(host_pin, 16 * 1024**2)
        return ('// GENERATED REVIEW DATA; host pin is NOT watchdog self-authentication.\n'
            'namespace AiAgent.ValidatorSetup { internal static class ReviewedSetupSupervisor {\n'
            f'internal static SetupSupervisorProfile Create() {{ return new SetupSupervisorProfile(ReviewedSetupHost.Create(),{count},"{digest}"); }}\n'
            '} }\n').encode('ascii')
    except request.InstallRequestRefused:
        raise SetupBuildRefused('setup_host_pin') from None


def _plan(value: object, sources: object, tools: object, *, watchdog: bool) -> build.ValidatorBuildRecipe:
    try:
        p = build._fields(value, ('version', 'scope', 'windows_root', 'staging_root', 'host_profile', 'host_pin',
            'source_pins', 'toolchain_pins', 'toolchain_aliases'))
        if type(p['version']) is not int or p['version'] != 1 or p['scope'] != (WATCHDOG_BUILD_SCOPE if watchdog else HOST_BUILD_SCOPE):
            raise SetupBuildRefused('setup_build_scope')
        hp = _host(p['host_profile'])
        names = WATCHDOG_SOURCES if watchdog else HOST_SOURCES
        supplied = build._fields(sources, names)
        complete = {name: supplied[name] for name in names}
        complete[HOST_PROFILE_NAME] = emit_setup_host_profile(hp)
        if watchdog:
            complete[WATCHDOG_PROFILE_NAME] = emit_setup_watchdog_profile(p['host_pin'])
        elif p['host_pin'] is not None:
            raise SetupBuildRefused('setup_host_pin_cycle')
        staged = build._pinned(complete, p['source_pins'], tuple(complete), 512 * 1024)
        windows = build._path(p['windows_root'], 64)
        stage = build._path(p['staging_root'], 100)
        parent = cast(dict[str, object], hp['parent'])
        host = cast(dict[str, object], hp['host_anchor'])
        if any(build._overlap(stage, cast(str, x)) for x in (windows, parent['path'], host['path'])):
            raise SetupBuildRefused('setup_stage_overlap')
        framework = windows + '\\Microsoft.NET\\Framework64\\v4.0.30319'
        aliases = build._aliases(p['toolchain_aliases'], windows, framework)
        held = build._pinned(tools, p['toolchain_pins'], build.TOOLCHAIN_NAMES, 32 * 1024**2)
        entry = build.SETUP_ENTRY_POINTS[1 if watchdog else 0]
        exe, main = entry
        command = (framework + '\\csc.exe', *build.COMMON_OPTIONS, '/main:' + main, '/out:' + stage + '\\out\\' + exe,
            '/win32manifest:' + stage + '\\' + build.MANIFEST_NAME,
            *('/reference:' + framework + '\\' + n for n in build.REFERENCE_NAMES), *(stage + '\\' + n for n, _ in staged))
        return build.ValidatorBuildRecipe(staging_files=(*staged, (build.MANIFEST_NAME, build.MANIFEST_BYTES), ('out/' + exe + '.config', request._CONFIG)),
            commands=(command,), working_directory=stage, directories=('out', 'temp'), environment=(('SystemRoot', windows), ('WINDIR', windows),
            ('TEMP', stage + '\\temp'), ('TMP', stage + '\\temp')), expected_outputs=(exe, exe + '.config'),
            toolchain_pins=tuple((framework + '\\' + n, len(raw), hashlib.sha256(raw).hexdigest()) for n, raw in held),
            toolchain_aliases=aliases, entry_points=(entry,))
    except (build.ValidatorBuildRefused, request.InstallRequestRefused, setup.SetupRefused):
        raise SetupBuildRefused('setup_build_data') from None


def plan_setup_host_build(value: object, *, source_files: object, toolchain_files: object) -> build.ValidatorBuildRecipe:
    return _plan(value, source_files, toolchain_files, watchdog=False)


def plan_setup_watchdog_build(value: object, *, source_files: object, toolchain_files: object) -> build.ValidatorBuildRecipe:
    return _plan(value, source_files, toolchain_files, watchdog=True)
