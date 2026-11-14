"""Closed, memory-only precompiled command-owner recipe; never installation.

Reuses the existing bounded UNELEVATED build owner. Independent source/tool pins,
complete tool aliases and reviewed builder/OS/CLR load trust are prerequisites.
Observed output hashes do not supply independently reviewed deployment pins.
"""
from __future__ import annotations

import hashlib

from night_shifts import bootstrap_native_build as build
from night_shifts.bootstrap_native_install_request import _CONFIG

SCOPE = 'reviewed_command_bootstrap_build_not_authorization'
SOURCES = ('privileged_command_helper.ps1', 'privileged_command_bootstrap.cs')
CORE = 'CommandWatchdog.g.cs'


def plan_command_bootstrap_build(value: object, *, source_files: object, toolchain_files: object) -> build.ValidatorBuildRecipe:
    p = build._fields(value, ('version', 'scope', 'windows_root', 'staging_root', 'source_pins', 'toolchain_pins', 'toolchain_aliases'))
    if type(p['version']) is not int or p['version'] != 1 or p['scope'] != SCOPE:
        raise build.ValidatorBuildRefused('command_bootstrap_scope')
    held = dict(build._pinned(source_files, p['source_pins'], SOURCES, 65536))
    text = held[SOURCES[0]].decode('utf-8-sig').replace('\r\n', '\n')
    start, end = "    Add-Type -TypeDefinition @'\n", "\n'@\n"
    if text.count(start) != 1:
        raise build.ValidatorBuildRefused('command_bootstrap_core')
    core, separator, _ = text.split(start, 1)[1].partition(end)
    if not separator or not core.startswith('using System;\n'):
        raise build.ValidatorBuildRefused('command_bootstrap_core')
    windows, stage = build._path(p['windows_root'], 64), build._path(p['staging_root'], 100)
    if build._overlap(windows, stage):
        raise build.ValidatorBuildRefused('command_bootstrap_stage')
    framework = windows + '\\Microsoft.NET\\Framework64\\v4.0.30319'
    aliases = build._aliases(p['toolchain_aliases'], windows, framework)
    tools = build._pinned(toolchain_files, p['toolchain_pins'], build.TOOLCHAIN_NAMES, 32 * 1024**2)
    exe, main = build.COMMAND_ENTRY_POINT
    command = (framework + '\\csc.exe', *build.COMMON_OPTIONS, '/main:' + main,
        '/out:' + stage + '\\out\\' + exe, '/win32manifest:' + stage + '\\' + build.MANIFEST_NAME,
        *('/reference:' + framework + '\\' + n for n in build.REFERENCE_NAMES), stage + '\\' + CORE, stage + '\\' + SOURCES[1])
    return build.ValidatorBuildRecipe(staging_files=((CORE, core.encode('utf-8')), (SOURCES[1], held[SOURCES[1]]),
        (build.MANIFEST_NAME, build.MANIFEST_BYTES), ('out/' + exe + '.config', _CONFIG)), commands=(command,),
        working_directory=stage, directories=('out', 'temp'), environment=(('SystemRoot', windows), ('WINDIR', windows),
        ('TEMP', stage + '\\temp'), ('TMP', stage + '\\temp')), expected_outputs=(exe, exe + '.config'),
        toolchain_pins=tuple((framework + '\\' + n, len(raw), hashlib.sha256(raw).hexdigest()) for n, raw in tools),
        toolchain_aliases=aliases, entry_points=(build.COMMAND_ENTRY_POINT,))
