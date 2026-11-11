"""Memory-only HOST build recipe, not a builder, installer or authorization.

Never execute checkout code elevated. Byte matches do not authenticate a
compiler, review source, lock paths or establish the Windows/CLR load closure.
The eventual separately trusted builder must acquire/reverify all actual inputs
and execute only in a fresh private staging tree, unelevated. No I/O here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import cast

from night_shifts import bootstrap_native_install_request as request

BUILD_SCOPE = 'reviewed_validator_build_recipe_not_authorization'
SOURCE_NAMES = (
    'native_validator_approval_guardian.cs',
    'native_validator_guardian_entry.cs',
    'native_validator_held_guardian.cs',
    'native_validator_install_boundary.cs',
    'native_validator_install_request.cs',
    'native_validator_install_windows.cs',
    'native_validator_launch_boundary.cs',
    'native_validator_launch_windows.cs',
    'native_validator_process_guardian.cs',
    'native_validator_process_guardian_windows.cs',
    'native_validator_request_guardian.cs',
    'native_validator_section_boundary.cs',
    'native_validator_section_windows.cs',
    'native_validator_worker_entry.cs',
    'native_validator_worker_guardian.cs',
    'native_validator_worker_windows.cs',
)
PROFILE_NAME = 'ReviewedGuardianProfile.g.cs'
MANIFEST_NAME = 'validator.manifest'
REFERENCE_NAMES = ('mscorlib.dll', 'System.dll', 'System.Core.dll', 'System.Xml.dll', 'System.Runtime.Serialization.dll')
TOOLCHAIN_NAMES = ('csc.exe', 'csc.exe.config', 'cvtres.exe', 'cvtres.exe.config', *REFERENCE_NAMES)
# Fixed BUILD-only profile, never caller-selected and unrelated to worker caps.
# This Framework profile permits the root plus two resource-converter creations.
# Accounting may still include an exiting helper; it is not the limit counter.
BUILD_ACTIVE_PROCESS_LIMIT = 2  # set/read back natively; NOT raised for accounting
BUILD_TOTAL_PROCESS_LIMIT = 3  # root + two helper invocations; observed cooperatively
ENTRY_POINTS = (
    ('validator-install-guardian.exe', 'AiAgent.ValidatorEntry.ValidatorGuardianProgram'),
    ('validator-provision-worker.exe', 'AiAgent.ValidatorWorker.ValidatorWorkerProgram'),
)
SETUP_ENTRY_POINTS = (
    ('validator-setup-host.exe', 'AiAgent.ValidatorSetup.ValidatorSetupHostProgram'),
    ('validator-setup-watchdog.exe', 'AiAgent.ValidatorSetup.ValidatorSetupWatchdogProgram'),
)
# No elevation request. A separately trusted starter supplies the elevated role;
# the produced assemblies cannot authenticate their own pre-load provenance.
MANIFEST_BYTES = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
    b'<assemblyIdentity version="1.0.0.0" name="AiAgent.NativeValidator" type="win32"/>'
    b'<trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>'
    b'<requestedExecutionLevel level="asInvoker" uiAccess="false"/>'
    b'</requestedPrivileges></security></trustInfo></assembly>\n'
)
COMMON_OPTIONS = (
    '/noconfig', '/nostdlib+', '/nologo', '/target:exe', '/platform:x64',
    '/langversion:5', '/optimize+', '/debug-', '/checked-', '/unsafe-',
    '/warn:4', '/warnaserror+', '/utf8output',
)


class ValidatorBuildRefused(RuntimeError):
    """Fixed-label data refusal; never installation or execution acceptance."""


@dataclass(frozen=True)
class ValidatorBuildRecipe:
    """Immutable staging/argv DATA. No handles, execution, acceptance or trust."""

    staging_files: tuple[tuple[str, bytes], ...]
    commands: tuple[tuple[str, ...], ...]
    working_directory: str
    directories: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    expected_outputs: tuple[str, ...]
    # Reviewed byte pins to REACQUIRE through trusted native handles later.
    toolchain_pins: tuple[tuple[str, int, str], ...]
    # Independent COMPLETE alias inventories for the selected OS tool files.
    # They select verification targets only, never additional code to execute.
    toolchain_aliases: tuple[tuple[str, tuple[str, ...]], ...]
    # Closed constructors only: original pair, setup host alone, watchdog alone.
    entry_points: tuple[tuple[str, str], ...] = ENTRY_POINTS


def _fields(value: object, names: tuple[str, ...]) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(names):
        raise ValidatorBuildRefused('build_schema')
    return cast(dict[str, object], value)


def _pinned(value: object, pins: object, names: tuple[str, ...], maximum: int) -> tuple[tuple[str, bytes], ...]:
    files = _fields(value, names)
    expected = _fields(pins, names)
    result = []
    for name in names:
        raw = files[name]
        pin = _fields(expected[name], ('bytes', 'sha256'))
        if (type(raw) is not bytes or not 1 <= len(raw) <= maximum
                or type(pin['bytes']) is not int or pin['bytes'] != len(raw)
                or type(pin['sha256']) is not str or len(pin['sha256']) != 64
                or pin['sha256'] != hashlib.sha256(raw).hexdigest()):
            raise ValidatorBuildRefused('build_pin')
        result.append((name, raw))
    return tuple(result)


def _path(value: object, maximum: int) -> str:
    try:
        return request._path(value, maximum)
    except request.InstallRequestRefused:
        raise ValidatorBuildRefused('build_path') from None


def _overlap(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    return a == b or a.startswith(b + '\\') or b.startswith(a + '\\')


def _aliases(value: object, windows: str, framework: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    inventory = _fields(value, TOOLCHAIN_NAMES)
    result = []
    for name in TOOLCHAIN_NAMES:
        paths = inventory[name]
        if type(paths) is not list or not 1 <= len(paths) <= 8:
            raise ValidatorBuildRefused('build_tool_aliases')
        copied = tuple(_path(path, 240) for path in paths)
        lowered = tuple(path.lower() for path in copied)
        selected = framework + '\\' + name
        if (len(set(lowered)) != len(lowered) or selected.lower() not in lowered
                or any(not path.startswith(windows.lower() + '\\') for path in lowered)):
            raise ValidatorBuildRefused('build_tool_aliases')
        result.append((selected, tuple(sorted(copied, key=str.lower))))
    return tuple(result)


def plan_validation_build(value: object, *, source_files: object, toolchain_files: object) -> ValidatorBuildRecipe:
    """Bind reviewed byte snapshots and emit ONLY the two fixed compiler argv.

    The closed review contains version/scope, Windows/staging paths, fixed
    guardian-profile data, independent source/toolchain pins and complete reviewed
    tool-alias maps. Aliases are held verification paths, NOT executable selectors.
    Unreviewed multi-link OS inputs still refuse. The source
    map includes the generated profile's independent pin; caller source bytes
    contain only the sixteen fixed repository members. No commands, reference
    selection, response files, request/policy hashes or build options accepted.
    This proves local consistency only; the future builder must establish actual
    native identities, loader security, freshness, environment and child absence.
    """
    root = _fields(value, ('version', 'scope', 'windows_root', 'staging_root',
                           'guardian_profile', 'source_pins', 'toolchain_pins', 'toolchain_aliases'))
    if type(root['version']) is not int or root['version'] != 1 or root['scope'] != BUILD_SCOPE:
        raise ValidatorBuildRefused('build_scope')
    windows = _path(root['windows_root'], 64)
    stage = _path(root['staging_root'], 100)
    framework = windows + '\\Microsoft.NET\\Framework64\\v4.0.30319'
    aliases = _aliases(root['toolchain_aliases'], windows, framework)
    try:
        generated = request.build_validation_guardian_profile(root['guardian_profile'])
    except request.InstallRequestRefused:
        raise ValidatorBuildRefused('build_profile') from None
    # Revalidate exact source-map shape BEFORE copying; no unknown members are
    # projected away. Generated bytes cannot be supplied as arbitrary C# source.
    sources = _fields(source_files, SOURCE_NAMES)
    complete = {**sources, PROFILE_NAME: generated}
    staged = _pinned(complete, root['source_pins'], (*SOURCE_NAMES, PROFILE_NAME), 512 * 1024)
    tools = _pinned(toolchain_files, root['toolchain_pins'], TOOLCHAIN_NAMES, 32 * 1024**2)
    profile = cast(dict[str, object], root['guardian_profile'])
    approval = cast(dict[str, object], profile['approval_anchor'])
    protected_roots = (windows, cast(str, profile['launch_root']), cast(str, approval['path']))
    if any(_overlap(stage, path) for path in protected_roots):
        raise ValidatorBuildRefused('build_staging_overlap')
    # No inherited PATH, DEVPATH, COMPLUS_*, profiling hooks or response files.
    # This is required environment DATA, not proof of actual process isolation.
    environment = (('SystemRoot', windows), ('WINDIR', windows),
                   ('TEMP', stage + '\\temp'), ('TMP', stage + '\\temp'))
    commands = tuple(
        (framework + '\\csc.exe', *COMMON_OPTIONS, '/main:' + entry,
         '/out:' + stage + '\\out\\' + name, '/win32manifest:' + stage + '\\' + MANIFEST_NAME,
         *('/reference:' + framework + '\\' + ref for ref in REFERENCE_NAMES),
         *(stage + '\\' + source for source, _ in staged))
        for name, entry in ENTRY_POINTS
    )
    outputs = tuple(name for name in request.LAUNCH_NAMES)
    configs = tuple(('out/' + name, request._CONFIG) for name in outputs if name.endswith('.config'))
    pins = tuple((framework + '\\' + name, len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in tools)
    return ValidatorBuildRecipe(
        staging_files=(*staged, (MANIFEST_NAME, MANIFEST_BYTES), *configs),
        commands=commands, working_directory=stage, directories=('out', 'temp'),
        environment=environment, expected_outputs=outputs, toolchain_pins=pins, toolchain_aliases=aliases,
    )
