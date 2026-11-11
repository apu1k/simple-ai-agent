"""Held local-NTFS build inputs and create-new private staging; UNELEVATED only.

No process launch, installation, publication, overwrite, ACL repair or deletion.
Windows/.NET and the builder runtime remain separately trusted prerequisites.
"""
from __future__ import annotations

import ctypes as c
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace

from night_shifts import bootstrap_native_build as build
from night_shifts import bootstrap_native_build_artifacts as artifacts
from night_shifts import maintenance_store_native_prototype as native
from night_shifts.bootstrap_native_build_windows import _Window, _Windows, _require

_TI = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'
_SYSTEM = frozenset(('S-1-5-18', 'S-1-5-32-544', _TI))
_RETAINED_STAGES: list[_BuildStage] = []


@dataclass
class _Held:
    handle: native._Handle
    before: native.Observation
    final: str
    directory: bool
    private: bool
    tool: bool
    inherited: bool = False
    reviewed_links: int = 1


class _BuildStage:
    def __init__(self, api: _Windows, sid: str, recipe: build.ValidatorBuildRecipe, window: _Window,
                 completed: Callable[[], int], quiescent: Callable[[], bool]) -> None:
        self.api, self.sid, self.recipe, self.window = api, sid, recipe, window
        self.completed, self.quiescent = completed, quiescent
        self.used = self.closed = False
        self.all: list[native._Handle] = []
        self.paths: dict[str, _Held] = {}
        self.identities: set[native.FileIdentity] = set()
        self.inputs: dict[str, tuple[_Held, int, str]] = {}
        self.produced: dict[str, tuple[_Held, int, str]] = {}
        self.tool_inventories: list[tuple[str, tuple[str, ...], _Held]] = []
        self.stage: _Held | None = None
        self.out: _Held | None = None
        self.temp: _Held | None = None

    def _policy(self, value: native.Observation, *, directory: bool, private: bool, tool: bool,
                inherited: bool = False, reviewed_links: int = 1) -> None:
        if tool and not directory:
            # Only explicitly reviewed OS files may have aliases. Every alias
            # is enumerated, opened and pinned below. Stage inputs/outputs and
            # ALL directories retain the original single-link shape rule.
            _require(type(reviewed_links) is int and 1 <= reviewed_links <= 8
                     and value.links == reviewed_links, 'build_stage_tool_links')
            native._check_shape(replace(value, links=1), directory=False)
        else:
            native._check_shape(value, directory=directory)
        trusted = _SYSTEM if tool else _SYSTEM | {self.sid}
        _require(value.acl.owner in trusted and 1 <= len(value.acl.rules) <= 128, 'build_stage_owner')
        if private:
            _require(not inherited or not directory, 'build_stage_inherited_kind')
            _require(value.acl.owner == self.sid and value.protected != inherited and len(value.acl.rules) == 3,
                     'build_stage_private')
            flags = 16 if inherited else (3 if directory else 0)
            expected = {(sid, 0x1f01ff, flags, 0) for sid in (self.sid, 'S-1-5-18', 'S-1-5-32-544')}
            _require({(rule.sid, rule.mask, rule.flags, rule.kind) for rule in value.acl.rules} == expected,
                     'build_stage_private')
        else:
            harmless = 0x1200a9 | 0xa0000000 | (6 if directory else 0)
            for rule in value.acl.rules:
                _require(rule.kind in (0, 1) and not rule.flags & ~31, 'build_stage_ace')
                # OWNER RIGHTS denotes this object's ALREADY VERIFIED owner,
                # not another account. Python 3.14 private temp parents use it.
                principal_trusted = rule.sid in trusted or (rule.sid == 'S-1-3-4' and value.acl.owner in trusted)
                if rule.kind == 0 and not rule.flags & 8 and not principal_trusted:
                    _require(not rule.mask & ~harmless, 'build_stage_mutable_ancestry')

    def _adopt(self, handle: native._Handle, *, directory: bool, private: bool = False,
               tool: bool = False, previous: _Held | None = None, inherited: bool = False,
               reviewed_links: int = 1, alias_of: _Held | None = None) -> _Held:
        self.all.append(handle)  # own BEFORE observation/rejection
        if directory:
            self.api.require_case_insensitive(handle)
        value = self.api.observe(handle)
        self._policy(value, directory=directory, private=private, tool=tool, inherited=inherited,
                     reviewed_links=reviewed_links)
        if alias_of is not None:
            _require(tool and not directory and not private and previous is None
                     and alias_of.tool and value == alias_of.before
                     and reviewed_links == alias_of.reviewed_links, 'build_stage_tool_alias_identity')
        elif previous is None:
            _require(value.identity not in self.identities, 'build_stage_identity_alias')
            self.identities.add(value.identity)
        else:
            _require(not previous.handle.value and value.identity == previous.before.identity, 'build_stage_seal_identity')
        return _Held(handle, value, self.api.final_name(handle), directory, private, tool, inherited, reviewed_links)

    def _match(self, held: _Held) -> None:
        self.window.check()
        _require(not self.closed and held.handle.value, 'build_stage_closed')
        if held.directory:
            self.api.require_case_insensitive(held.handle)
        now = self.api.observe(held.handle)
        self._policy(now, directory=held.directory, private=held.private, tool=held.tool, inherited=held.inherited,
                     reviewed_links=held.reviewed_links)
        before = held.before
        if held.directory:
            now, before = replace(now, size=0), replace(before, size=0)
        _require(now == before and self.api.final_name(held.handle) == held.final, 'build_stage_metadata_drift')

    def _child(self, parent: _Held, name: str, *, directory: bool, create: bool = False,
               private: bool = False, tool: bool = False, writable: bool = False,
               previous: _Held | None = None, inherited: bool = False,
               reviewed_links: int = 1, alias_of: _Held | None = None) -> _Held:
        self._match(parent)
        held = self._adopt(self.api.relative_build(parent.handle, name, directory=directory, create=create,
                                                   sid=self.sid, writable=writable), directory=directory,
                           private=private, tool=tool, previous=previous, inherited=inherited,
                           reviewed_links=reviewed_links, alias_of=alias_of)
        # All participating directories were checked case-insensitive. Permit
        # ONLY ASCII case spelling differences, not a different native object.
        _require(held.before.identity.volume == parent.before.identity.volume
                 and held.final.isascii() and parent.final.isascii()
                 and held.final.lower() == (parent.final.rstrip('\\') + '\\' + name).lower(), 'build_stage_path_drift')
        self._match(parent)
        return held

    def _walk(self, path: str, *, tool: bool = False) -> _Held:
        drive, parts = (path, ()) if len(path) == 3 and path[1:] == ':\\' else native._path_parts(path)
        key = drive.lower()
        if key not in self.paths:
            self.paths[key] = self._adopt(self.api.root(drive), directory=True)
        parent = self.paths[key]
        for part in parts:
            key += part.lower() + '\\'
            if key not in self.paths:
                self.paths[key] = self._child(parent, part, directory=True, tool=tool)
            parent = self.paths[key]
        return parent

    def _read(self, held: _Held, count: int, digest: str) -> bytes:
        self._match(held)
        _require(held.before.size == count and 1 <= count <= 32 * 1024**2, 'build_stage_input_size')
        _require(self.api.k.SetFilePointerEx(held.handle.value, 0, None, 0), 'build_stage_seek')
        result = bytearray()
        while len(result) < count:
            self.window.check()
            wanted = min(65536, count - len(result))
            buffer, read = c.create_string_buffer(wanted), c.c_uint32()
            _require(self.api.k.ReadFile(held.handle.value, buffer, wanted, c.byref(read), None)
                     and 1 <= read.value <= wanted, 'build_stage_read')
            result.extend(buffer.raw[:read.value])
        extra, read = c.create_string_buffer(1), c.c_uint32()
        _require(self.api.k.ReadFile(held.handle.value, extra, 1, c.byref(read), None) and read.value == 0,
                 'build_stage_eof')
        self._match(held)
        raw = bytes(result)
        _require(hashlib.sha256(raw).hexdigest() == digest, 'build_stage_input_pin')
        self.window.check()
        return raw

    def _write_source(self, parent: _Held, name: str, raw: bytes) -> _Held:
        writer = self._child(parent, name, directory=False, create=True, private=True, writable=True)
        offset = 0
        while offset < len(raw):
            self.window.check()
            part = raw[offset:offset + 65536]
            buffer, written = c.create_string_buffer(part), c.c_uint32()
            _require(self.api.k.WriteFile(writer.handle.value, buffer, len(part), c.byref(written), None)
                     and written.value == len(part), 'build_stage_write')
            offset += written.value
        _require(self.api.k.FlushFileBuffers(writer.handle.value), 'build_stage_flush')
        # BEFORE any process exists, close the owned writer under a private held
        # parent, reacquire a share-read-only reader and require SAME identity,
        # security, controlled archive/size delta, final name and complete bytes.
        # This is not an atomic rights downgrade or a claim-file implementation.
        self.api.close(writer.handle)
        reader = self._child(parent, name, directory=False, private=True, previous=writer)
        before, after = writer.before, reader.before
        _require(before.identity == after.identity and before.acl == after.acl and before.protected == after.protected
                 and (before.attributes | 32) == (after.attributes | 32) and after.size == len(raw), 'build_stage_seal')
        self._read(reader, len(raw), hashlib.sha256(raw).hexdigest())
        return reader

    def _names(self, held: _Held, expected: set[str]) -> None:
        self._match(held)
        _require(self.api.names(held.handle) == expected, 'build_stage_inventory')
        self._match(held)

    def acquire(self) -> _BuildStage:
        _require(not self.used, 'build_stage_one_shot')
        self.used = True
        try:
            # Pin actual selected OS-tool paths BEFORE creating staging. This
            # does not measure every possible Windows/CLR loader dependency.
            reviewed = dict(self.recipe.toolchain_aliases)
            for path, count, digest in self.recipe.toolchain_pins:
                parent_path, name = path.rsplit('\\', 1)
                aliases = reviewed[path]
                parent = self._walk(parent_path, tool=True)
                held = self._child(parent, name, directory=False, tool=True, reviewed_links=len(aliases))
                self.inputs['tool:' + name] = held, count, digest
                self._read(held, count, digest)
                self.tool_inventories.append((path, aliases, held))
                self._alias_inventory(path, aliases, held)
                for index, alias in enumerate(aliases):
                    if alias.lower() == path.lower():
                        continue
                    alias_parent, leaf = alias.rsplit('\\', 1)
                    parent = self._walk(alias_parent, tool=True)
                    item = self._child(parent, leaf, directory=False, tool=True,
                                       reviewed_links=len(aliases), alias_of=held)
                    self.inputs['tool:' + name + ':' + str(index)] = item, count, digest
                    self._read(item, count, digest)
                self._alias_inventory(path, aliases, held)
            parent_path, leaf = self.recipe.working_directory.rsplit('\\', 1)
            parent = self._walk(parent_path)
            self.stage = self._child(parent, leaf, directory=True, create=True, private=True)
            self.out = self._child(self.stage, 'out', directory=True, create=True, private=True)
            self.temp = self._child(self.stage, 'temp', directory=True, create=True, private=True)
            for name, raw in self.recipe.staging_files:
                parent, leaf = (self.out, name[4:]) if name.startswith('out/') else (self.stage, name)
                held = self._write_source(parent, leaf, raw)
                self.inputs[name] = held, len(raw), hashlib.sha256(raw).hexdigest()
            self.reverify()
            return self
        except BaseException:
            try:
                self.close()
            except BaseException:
                _RETAINED_STAGES.append(self)
            raise

    def _alias_inventory(self, path: str, expected: tuple[str, ...], held: _Held) -> None:
        self._match(held)
        actual = self.api.aliases(path)
        _require(tuple(name.lower() for name in actual) == tuple(name.lower() for name in expected),
                 'build_stage_tool_aliases')
        self._match(held)

    def _collect(self) -> None:
        assert self.out is not None
        finished = self.completed()
        _require(type(finished) is int and 0 <= finished <= len(self.recipe.entry_points), 'build_stage_completion')
        names = [name for name, _ in self.recipe.entry_points[:finished]]
        self._names(self.out, {name[4:] for name in self.inputs if name.startswith('out/')} | set(names))
        for name in names:
            if name in self.produced:
                continue
            _require(self.quiescent(), 'build_stage_output_while_active')
            # Compiler-created, not installed: EXACT inheritance from the held
            # protected out directory (three inherited user/SYSTEM/BA ACEs).
            # No ACL repair/protection toggle after compiler creation.
            held = self._child(self.out, name, directory=False, private=True, inherited=True)
            _require(1 <= held.before.size <= 16 * 1024**2, 'build_stage_output_bound')
            count = held.before.size
            _require(self.api.k.SetFilePointerEx(held.handle.value, 0, None, 0), 'build_stage_seek')
            sha, remaining = hashlib.sha256(), count
            while remaining:
                self.window.check()
                wanted = min(remaining, 65536)
                buffer, read = c.create_string_buffer(wanted), c.c_uint32()
                _require(self.api.k.ReadFile(held.handle.value, buffer, wanted, c.byref(read), None)
                         and 1 <= read.value <= wanted, 'build_stage_output_read')
                sha.update(buffer.raw[:read.value])
                remaining -= read.value
            raw = self._read(held, count, sha.hexdigest())
            artifacts.inspect_fixed_executable(name, raw)
            self.window.check()
            self.produced[name] = held, count, sha.hexdigest()

    def reverify(self) -> None:
        _require(not self.closed and self.stage is not None and self.temp is not None, 'build_stage_closed')
        assert self.stage is not None and self.temp is not None
        for held in self.paths.values():
            self._match(held)
        self._names(self.stage, {name for name, _ in self.recipe.staging_files if '/' not in name} | {'out', 'temp'})
        self._names(self.temp, set())
        self._collect()
        for path, aliases, first in self.tool_inventories:
            self._alias_inventory(path, aliases, first)
        for held, count, digest in (*self.inputs.values(), *self.produced.values()):
            self._read(held, count, digest)
        self.window.check()

    def outputs(self) -> object:
        _require(self.completed() == len(self.recipe.entry_points) and self.quiescent(), 'build_stage_outputs_before_absence')
        self.reverify()
        result = {}
        for name in self.recipe.expected_outputs:
            held, count, digest = self.inputs['out/' + name] if name.endswith('.config') else self.produced[name]
            result[name] = self._read(held, count, digest)
        self.reverify()
        return result

    def close(self) -> None:
        _require(not self.closed, 'build_stage_close_once')
        self.closed = True
        unknown = False
        for handle in reversed(self.all):
            if handle.value:
                try:
                    self.api.close(handle)
                except BaseException:
                    unknown = True
        _require(not unknown, 'build_stage_close_unknown')
