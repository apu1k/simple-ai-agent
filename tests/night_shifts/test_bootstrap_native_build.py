"""Closed HOST build DATA and disposable, UNELEVATED fixed-executable builds.

No production profile, install, executable launch, Main invocation, claim, VM or
carried Python. CLR reflection-only inspection reads inert binary metadata.
Observed installed compiler pins in this fixture are NOT independent approval.
"""
from __future__ import annotations

import base64
import copy
import dataclasses
import hashlib
import os
import struct
import subprocess
import tempfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_install_request as request

ROOT = Path(__file__).resolve().parents[2]


def _profile():
    return {'version': 1, 'scope': request.GUARDIAN_PROFILE_SCOPE,
            'operator_sid': 'S-1-5-21-1-2-3-1001',
            'approval_anchor': {'path': r'C:\Approval', 'identity': {'volume': 88, 'index': 100}},
            'launch_root': r'C:\Private Anchor'}


def _pins(files):
    return {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in files.items()}


def _candidate(sources=None, tools=None):
    sources = sources if sources is not None else {name: b'// inert source\n' for name in build.SOURCE_NAMES}
    tools = tools if tools is not None else {name: b'inert ' + name.encode('ascii') for name in build.TOOLCHAIN_NAMES}
    profile = _profile()
    review = {'version': 1, 'scope': build.BUILD_SCOPE, 'windows_root': r'C:\Windows',
              'staging_root': r'C:\Disposable Build', 'guardian_profile': profile,
              'source_pins': _pins({**sources, build.PROFILE_NAME: request.build_validation_guardian_profile(profile)}),
              'toolchain_pins': _pins(tools)}
    return review, sources, tools


def _plan(review, sources, tools):
    return build.plan_validation_build(review, source_files=sources, toolchain_files=tools)


BAD_REVIEWS = (
    ('version_bool', ('version',), True),
    ('version', ('version',), 2),
    ('scope', ('scope',), 'trusted_build'),
    ('extra_option', ('options',), ['/unsafe+']),
    ('extra_entry', ('main',), 'Injected.Main'),
    ('extra_reference', ('references',), ['Injected.dll']),
    ('request_hash', ('request_sha256',), 'a' * 64),
    ('policy_hash', ('policy_sha256',), 'a' * 64),
    ('windows_relative', ('windows_root',), 'Windows'),
    ('windows_injection', ('windows_root',), 'C:\\Windows" /unsafe+'),
    ('windows_device', ('windows_root',), r'C:\NUL'),
    ('windows_long', ('windows_root',), 'C:\\' + 'w' * 62),
    ('stage_unc', ('staging_root',), r'\\host\share'),
    ('stage_traversal', ('staging_root',), r'C:\Build\..\Other'),
    ('stage_long', ('staging_root',), 'C:\\' + 's' * 98),
    ('stage_windows', ('staging_root',), r'C:\WINDOWS\Stage'),
    ('stage_windows_parent', ('staging_root',), r'C:\Windows'),
    ('stage_approval', ('staging_root',), r'C:\Approval\Stage'),
    ('stage_launch', ('staging_root',), r'C:\PRIVATE ANCHOR'),
    ('stage_launch_parent', ('staging_root',), r'C:\Private Anchor\Stage'),
    ('profile_injection', ('guardian_profile', 'approval_anchor', 'path'), 'C:\\Policy\nInjected'),
    ('profile_request_hash', ('guardian_profile', 'request_sha256'), 'a' * 64),
    ('source_pin_bool', ('source_pins', build.SOURCE_NAMES[0], 'bytes'), True),
    ('source_pin_bad', ('source_pins', build.SOURCE_NAMES[0], 'sha256'), 'a' * 64),
    ('source_pin_upper', ('source_pins', build.SOURCE_NAMES[0], 'sha256'), 'A' * 64),
    ('source_pin_extra', ('source_pins', build.SOURCE_NAMES[0], 'reset'), True),
    ('profile_pin_bad', ('source_pins', build.PROFILE_NAME, 'sha256'), 'a' * 64),
    ('toolchain_config', ('toolchain_pins', 'csc.exe.config', 'bytes'), 1),
    ('toolchain_pin', ('toolchain_pins', 'mscorlib.dll', 'sha256'), 'a' * 64),
)


@pytest.mark.parametrize('_case,keys,bad', BAD_REVIEWS, ids=[row[0] for row in BAD_REVIEWS])
def test_review_is_closed_and_pinned(_case, keys, bad):
    review, sources, tools = _candidate()
    target = review
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = bad
    with pytest.raises(build.ValidatorBuildRefused):
        _plan(review, sources, tools)


@pytest.mark.parametrize('which', ('sources', 'source_pins', 'tools', 'toolchain_pins'))
@pytest.mark.parametrize('fault', ('missing', 'extra', 'case_alias', 'nonmapping'))
def test_fixed_inventories_are_not_projected_or_extended(which, fault):
    review, sources, tools = _candidate()
    table = {'sources': sources, 'tools': tools, **review}[which]
    if fault == 'nonmapping':
        if which == 'sources':
            sources = []
        elif which == 'tools':
            tools = []
        else:
            review[which] = []
    else:
        key = next(iter(table))
        value = table.pop(key) if fault in ('missing', 'case_alias') else table[key]
        if fault == 'extra':
            table['Injected.dll'] = value
        elif fault == 'case_alias':
            table[key.upper()] = value
    with pytest.raises(build.ValidatorBuildRefused):
        _plan(review, sources, tools)


@pytest.mark.parametrize('which', ('sources', 'tools'))
@pytest.mark.parametrize('bad', (b'', b'changed', 'text', bytearray(b'mutable'), None, 42))
def test_input_bytes_are_immutable_bounded_and_independently_pinned(which, bad):
    review, sources, tools = _candidate()
    table = sources if which == 'sources' else tools
    table[next(iter(table))] = bad
    with pytest.raises(build.ValidatorBuildRefused):
        _plan(review, sources, tools)


def test_matching_pin_does_not_override_source_bound():
    review, sources, tools = _candidate()
    name = build.SOURCE_NAMES[0]
    sources[name] = b'x' * (512 * 1024 + 1)
    review['source_pins'][name] = _pins(sources)[name]
    with pytest.raises(build.ValidatorBuildRefused):
        _plan(review, sources, tools)


def test_profile_change_requires_fresh_independent_pin():
    review, sources, tools = _candidate()
    review['guardian_profile']['operator_sid'] = 'S-1-5-21-1-2-3-1002'
    with pytest.raises(build.ValidatorBuildRefused):
        _plan(review, sources, tools)


def test_recipe_is_memory_only_deterministic_and_copied(monkeypatch):
    import builtins
    monkeypatch.setattr(builtins, 'open', lambda *_a, **_k: pytest.fail('recipe opened a file'))
    review, sources, tools = _candidate()
    recipe = _plan(review, sources, tools)
    assert recipe == _plan(dict(reversed(tuple(review.items()))), dict(reversed(tuple(sources.items()))), tools)
    before = copy.deepcopy(recipe)
    review['guardian_profile']['operator_sid'] = 'changed'
    sources.clear()
    tools.clear()
    assert recipe == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        recipe.commands = ()


def test_recipe_selects_only_fixed_entries_references_outputs_and_environment():
    recipe = _plan(*_candidate())
    assert recipe.expected_outputs == request.LAUNCH_NAMES
    assert set(dict(recipe.staging_files)) == {*build.SOURCE_NAMES, build.PROFILE_NAME, build.MANIFEST_NAME,
                                             *(f'out/{name}' for name in request.LAUNCH_NAMES if name.endswith('.config'))}
    assert all(raw == request._CONFIG for name, raw in recipe.staging_files if name.endswith('.config'))
    assert recipe.directories == ('out', 'temp')
    assert dict(recipe.environment) == {'SystemRoot': r'C:\Windows', 'WINDIR': r'C:\Windows',
                                        'TEMP': r'C:\Disposable Build\temp', 'TMP': r'C:\Disposable Build\temp'}
    for command, (name, entry) in zip(recipe.commands, build.ENTRY_POINTS, strict=True):
        assert command[0] == r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
        assert command[1:1 + len(build.COMMON_OPTIONS)] == build.COMMON_OPTIONS
        assert '/main:' + entry in command and '/out:' + recipe.working_directory + '\\out\\' + name in command
        assert [arg.rsplit('\\', 1)[-1] for arg in command if arg.startswith('/reference:')] == list(build.REFERENCE_NAMES)
        assert not any(arg.startswith('@') or 'Injected' in arg for arg in command)
        assert len(subprocess.list2cmdline(command)) < 8192
    assert len(recipe.toolchain_pins) == len(build.TOOLCHAIN_NAMES)
    xml = ElementTree.fromstring(build.MANIFEST_BYTES)
    requested = xml.find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
    assert requested is not None and requested.attrib == {'level': 'asInvoker', 'uiAccess': 'false'}


def _quote(path):
    return "'" + str(path).replace("'", "''") + "'"


@pytest.fixture(scope='module')
def executables():
    if os.name != 'nt':
        pytest.skip('requires Windows Framework64 compiler; NOT protected build or native launch evidence')
    windows = Path(os.environ['SystemRoot'])
    framework = windows / 'Microsoft.NET/Framework64/v4.0.30319'
    # These observed bytes test recipe consistency ONLY. A real builder needs
    # separately reviewed pins, secured native acquisition and pre-load trust.
    sources = {name: (ROOT / 'scripts' / name).read_bytes() for name in build.SOURCE_NAMES}
    tools = {name: (framework / name).read_bytes() for name in build.TOOLCHAIN_NAMES}
    with tempfile.TemporaryDirectory(prefix='vb-') as folder:
        stage = Path(folder)
        review, sources, tools = _candidate(sources, tools)
        review['windows_root'] = str(windows)
        review['staging_root'] = str(stage)
        recipe = _plan(review, sources, tools)
        for directory in recipe.directories:
            (stage / directory).mkdir()
        for name, raw in recipe.staging_files:
            (stage / name).write_bytes(raw)
        for command in recipe.commands:
            result = subprocess.run(command, cwd=stage, env=dict(recipe.environment), capture_output=True,
                                    text=True, encoding='utf-8', timeout=25, check=False)
            assert result.returncode == 0, result.stdout + result.stderr
        assert {p.name for p in (stage / 'out').iterdir()} == set(recipe.expected_outputs)
        # Metadata only, in a separate CLR. Never Assembly.Load, invoke Main,
        # start either executable, or call native/security/section/process APIs.
        script = "$ErrorActionPreference='Stop'; "
        for name, _entry in build.ENTRY_POINTS:
            script += (
                f'$a=[Reflection.Assembly]::ReflectionOnlyLoadFrom({_quote(stage / "out" / name)}); '
                # Valid non-AMD64 seed: GetPEKind MUST overwrite it; zero is
                # not a valid ImageFileMachine enum member in PowerShell.
                '$kind=[Reflection.PortableExecutableKinds]0; $machine=[Reflection.ImageFileMachine]::I386; '
                '$a.ManifestModule.GetPEKind([ref]$kind,[ref]$machine); '
                '$refs=@($a.GetReferencedAssemblies() | ForEach-Object {$_.Name} | Sort-Object); '
                '[Console]::WriteLine($a.GetName().Name+"|"+$a.EntryPoint.DeclaringType.FullName+"|"+$machine+"|"+$kind+"|"+($refs -join ",")); '
            )
        command = [str(windows / 'System32/WindowsPowerShell/v1.0/powershell.exe'), '-NoLogo', '-NoProfile',
                   '-NonInteractive', '-EncodedCommand', base64.b64encode(script.encode('utf-16le')).decode('ascii')]
        result = subprocess.run(command, cwd=stage, capture_output=True, text=True, timeout=15, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        metadata = result.stdout.strip().splitlines()
        binaries = {name: (stage / 'out' / name).read_bytes() for name, _ in build.ENTRY_POINTS}
        failures = {}
        for fault in ('no_main', 'no_profile'):
            command = [arg for arg in recipe.commands[0] if not (
                (fault == 'no_main' and arg.startswith('/main:'))
                or (fault == 'no_profile' and arg.endswith('\\' + build.PROFILE_NAME)))]
            command = ['/out:' + str(stage / 'out' / (fault + '.exe')) if arg.startswith('/out:') else arg for arg in command]
            result = subprocess.run(command, cwd=stage, env=dict(recipe.environment), capture_output=True,
                                    text=True, encoding='utf-8', timeout=25, check=False)
            assert result.returncode != 0, 'missing required build input/entry was silently accepted'
            failures[fault] = result.stdout + result.stderr
        return recipe, metadata, binaries, failures


@pytest.mark.parametrize('index', (0, 1), ids=('guardian', 'worker'))
def test_actual_inert_executable_entry_and_reference_metadata(executables, index):
    recipe, metadata, binaries, _ = executables
    assert len(metadata) == 2
    filename, entry = build.ENTRY_POINTS[index]
    name, actual_entry, machine, kind, references = metadata[index].split('|')
    assert name == filename[:-4] and actual_entry == entry
    flags = {flag.strip() for flag in kind.split(',')}
    assert machine == 'AMD64' and 'ILOnly' in flags
    assert not flags.intersection({'Required32Bit', 'Preferred32Bit', 'Unmanaged32Bit'})
    refs = set(references.split(','))
    assert {'mscorlib', 'System', 'System.Runtime.Serialization'} <= refs
    assert refs <= {name[:-4] for name in build.REFERENCE_NAMES}
    raw = binaries[filename]
    offset = struct.unpack_from('<I', raw, 0x3C)[0]
    assert raw[offset:offset + 4] == b'PE\0\0'
    assert struct.unpack_from('<H', raw, offset + 4)[0] == 0x8664
    assert struct.unpack_from('<H', raw, offset + 24)[0] == 0x20B  # PE32+ x64
    assert b'asInvoker' in raw and b'requireAdministrator' not in raw
    assert set(recipe.expected_outputs) == set(request.LAUNCH_NAMES)


def test_actual_compiler_requires_explicit_main_and_generated_profile(executables):
    _, _, _, failures = executables
    assert 'CS0017' in failures['no_main']
    assert 'CS0103' in failures['no_profile'] and 'ReviewedGuardianProfile' in failures['no_profile']


def test_build_recipe_remains_host_only_and_has_no_runner_or_production_profile():
    import ast
    path = ROOT / 'night_shifts/bootstrap_native_build.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imports <= {'__future__', 'hashlib', 'dataclasses', 'typing', 'night_shifts'}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in ('open', 'eval', 'exec', 'compile', '__import__') for node in ast.walk(tree))
    assert 'bootstrap_native_build.py' not in request.CODE_NAMES
    assert {p.name for p in (ROOT / 'scripts').glob('native_validator_*.cs')} == set(build.SOURCE_NAMES)
    assert not (ROOT / 'scripts' / build.PROFILE_NAME).exists()
    for folder, pattern in (('runtime', '*.py'), ('scripts', '*.ps1')):
        for path in (ROOT / folder).glob(pattern):
            assert 'bootstrap_native_build' not in path.read_text(encoding='utf-8-sig')
