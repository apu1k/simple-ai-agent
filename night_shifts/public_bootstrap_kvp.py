"""Public-only KVP wire helpers; no native acquisition, keys or authorization.

Linux pool records are two fixed byte arrays (512-byte key, 2048-byte value),
NOT UTF-16 or a packed hv_kvp_msg. Host items are bounded WMI embedded XML.
These parsers establish shape only, never origin, freshness or key possession.
"""
from __future__ import annotations

import math
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable

from night_shifts.maintenance_credentials_prototype import (
    PUBLIC_ITEM_NAME, CredentialPrototypeRefused, PublicBootstrap,
    decode_public_bootstrap, encode_public_bootstrap,
)
from night_shifts.maintenance_tls_prototype import AttemptBinding

KEY_BYTES = 512
VALUE_BYTES = 2048
POOL_RECORD_BYTES = KEY_BYTES + VALUE_BYTES
MAX_ITEMS = 32
MAX_XML_CHARS = 8192
MAX_TOTAL_XML_CHARS = 65536


class BootstrapKvpRefused(RuntimeError):
    """Fixed reason labels only; never echo pool, provider or certificate data."""


class Budget:
    """Cooperative deadline/cancellation, NOT a native watchdog or I/O timeout."""

    def __init__(self, seconds: float, cancelled: Callable[[], bool]) -> None:
        if (type(seconds) not in (int, float) or not math.isfinite(seconds)
                or not 0 < seconds <= 30 or not callable(cancelled)):
            raise BootstrapKvpRefused('configuration')
        self._deadline = time.monotonic() + seconds
        self._cancelled = cancelled
        self.check()

    def check(self) -> float:
        try:
            cancelled = self._cancelled()
        except Exception:
            raise BootstrapKvpRefused('cancellation_context') from None
        if type(cancelled) is not bool:
            raise BootstrapKvpRefused('cancellation_context')
        if cancelled:
            raise BootstrapKvpRefused('cancelled')
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise BootstrapKvpRefused('timeout')
        return remaining


def canonical_public_bytes(value: PublicBootstrap) -> bytes:
    """Revalidate a typed PUBLIC value; no generic key/value or payload writer."""
    if type(value) is not PublicBootstrap:
        raise BootstrapKvpRefused('public_record')
    try:
        raw = encode_public_bootstrap(value)
        decode_public_bootstrap(raw, value.binding, observed_vm_id=value.binding.vm_id,
                                item_name=PUBLIC_ITEM_NAME, item_source=1)
    except (CredentialPrototypeRefused, ValueError, TypeError):
        raise BootstrapKvpRefused('public_record') from None
    return raw


def pool_record(value: PublicBootstrap) -> bytes:
    raw = canonical_public_bytes(value)
    # Linux daemon stores UTF-8/ASCII. hv_utils converts it to host UTF-16.
    key = PUBLIC_ITEM_NAME.encode('ascii')
    return key.ljust(KEY_BYTES, b'\0') + raw.ljust(VALUE_BYTES, b'\0')


def _cstring(raw: bytes) -> str:
    head, separator, _ = raw.partition(b'\0')
    if not separator:
        raise BootstrapKvpRefused('pool_shape')
    try:
        return head.decode('utf-8')
    except UnicodeError:
        raise BootstrapKvpRefused('pool_shape') from None


def check_pool_for_append(raw: bytes) -> None:
    """Preserve opaque padding/other items; refuse any reserved-name collision.

    Daemon malloc padding need not be zero. Never rewrite/truncate other records.
    Even an identical existing public item is a collision, not retry permission.
    """
    if (type(raw) is not bytes or len(raw) % POOL_RECORD_BYTES
            or len(raw) >= MAX_ITEMS * POOL_RECORD_BYTES):
        raise BootstrapKvpRefused('pool_shape')
    seen: set[str] = set()
    for offset in range(0, len(raw), POOL_RECORD_BYTES):
        record = raw[offset:offset + POOL_RECORD_BYTES]
        key = _cstring(record[:KEY_BYTES])
        _cstring(record[KEY_BYTES:])
        if not key or key in seen:
            raise BootstrapKvpRefused('pool_shape')
        if key == PUBLIC_ITEM_NAME:
            raise BootstrapKvpRefused('pool_collision')
        seen.add(key)


def _item(xml: str) -> tuple[str, str]:
    if (type(xml) is not str or not 1 <= len(xml) <= MAX_XML_CHARS
            or '<!' in xml or '\0' in xml):
        raise BootstrapKvpRefused('item_xml')
    # Reject DTD/entity/CDATA/comments before parsing, and bound the tree too.
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, ValueError, RecursionError):
        raise BootstrapKvpRefused('item_xml') from None
    if (root.tag != 'INSTANCE'
            or root.attrib != {'CLASSNAME': 'Msvm_KvpExchangeDataItem'}
            or (root.text or '').strip() or (root.tail or '').strip()
            or len(list(root.iter())) > 24):
        raise BootstrapKvpRefused('item_xml')
    types = {'Name': 'string', 'Data': 'string', 'Source': 'uint16',
             'InstanceID': 'string', 'Caption': 'string',
             'Description': 'string', 'ElementName': 'string'}
    values: dict[str, str | None] = {}
    for prop in root:
        name = prop.get('NAME', '')
        if (prop.tag != 'PROPERTY' or name not in types or name in values
                or prop.attrib != {'NAME': name, 'TYPE': types[name]}
                or (prop.text or '').strip() or (prop.tail or '').strip()
                or len(prop) != 1):
            raise BootstrapKvpRefused('item_xml')
        node = prop[0]
        if (node.tag not in ('VALUE', 'VALUE.NULL') or node.attrib or len(node)
                or (node.tail or '').strip()
                or (node.tag == 'VALUE.NULL' and node.text)):
            raise BootstrapKvpRefused('item_xml')
        values[name] = (node.text or '') if node.tag == 'VALUE' else None
    if (not {'Name', 'Data', 'Source'} <= values.keys()
            or values['Source'] != '1' or not values['Name']
            or values['Data'] is None or len(values['Name']) > 1024
            or len(values['Data']) > 1024):
        raise BootstrapKvpRefused('item_schema')
    return values['Name'], values['Data']


def select_public_item(items: tuple[str, ...], binding: AttemptBinding) -> bytes | None:
    """Select only custom guest data from an already scoped provider snapshot.

    Caller-supplied XML/VM strings do NOT attest a provider or grant trust.
    Absence may be polled before first observation; malformed/duplicate/stale
    reserved records are fatal, never ignored in favour of another candidate.
    """
    if (type(binding) is not AttemptBinding or type(items) is not tuple
            or len(items) > MAX_ITEMS
            or any(type(item) is not str for item in items)
            or sum(len(item) for item in items) > MAX_TOTAL_XML_CHARS):
        raise BootstrapKvpRefused('items_bound')
    seen: set[str] = set()
    result: bytes | None = None
    for xml in items:
        name, data = _item(xml)
        if name in seen:
            raise BootstrapKvpRefused('item_duplicate')
        seen.add(name)
        if name == PUBLIC_ITEM_NAME:
            try:
                raw = data.encode('ascii')
                decode_public_bootstrap(raw, binding, observed_vm_id=binding.vm_id,
                                        item_name=name, item_source=1)
            except (UnicodeError, CredentialPrototypeRefused):
                raise BootstrapKvpRefused('public_record') from None
            result = raw
    return result
