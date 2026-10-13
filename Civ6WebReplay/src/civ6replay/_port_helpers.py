"""Shared helpers for the mechanically-ported C++ offset walkers.

``players.py`` and ``visibility.py`` adapt CivVIReplay's C++ walkers and
share the binary-reading helpers defined here.
"""
from __future__ import annotations

from typing import Any, Dict

from .binary import Cursor, ParseError, buff_to_int, read_int, u32
from .model import (
    City,
    Governor,
    Player,
    Record,
    Unit,
)

# Container anchors (bytes)
TERRITORY_BUILDER = b"TerritoryBuilder"
END_IA_STUFF = bytes([0xBA, 0xF1, 0xBF, 0x93])
END_PLAYER_STUFF = bytes([0xBC, 0x0A, 0x2B, 0xDE])
VISIBILITY_BEGIN = bytes([0xD2, 0xDE, 0x2D, 0x3F])

PROD_UNIT = 0

_FACTORIES: Dict[int, Any] = {}

_SUBCONTAINERS = {
    "cities": City,
    "units": Unit,
    "districts": Record,
    "governors": Governor,
    "emissaries": int,
}


def register_container(container, factory) -> None:
    _FACTORIES[id(container)] = factory


def resize(target: list, n: int) -> None:
    factory = _FACTORIES.get(id(target), Record)
    del target[:]
    target.extend(factory() for _ in range(n))
    if factory is Player:
        for p in target:
            for attr, sub in _SUBCONTAINERS.items():
                register_container(getattr(p, attr), sub)


def _range(n: int, it: Cursor | None = None):
    if n < 0 or n > 5_000_000:
        offset = None if it is None else it.pos
        raise ParseError(f"implausible loop count {n} at 0x{offset:x}", offset)
    return range(n)


def _seek(data, needle: bytes, start: int | None = None) -> Cursor:
    idx = data.find(needle, 0 if start is None else start)
    if idx < 0:
        raise ParseError(f"anchor {needle!r} not found", start)
    return Cursor(data, idx)


def peek_byte(it: Cursor) -> int:
    return it.data[it.pos]


def peek_u32(it: Cursor) -> int:
    return u32(it.data, it.pos)


def peek_int(it: Cursor, n: int) -> int:
    return buff_to_int(it.data, it.pos, n)


def read_float(it: Cursor) -> float:
    value = read_int(it)
    return (value >> 8) + (value & 0xFF) / 256.0


def _rmap(it: Cursor, target=None, size_value: int = 4):
    if isinstance(target, int):
        size_value = target
        target = None
    count = read_int(it)
    if count < 0 or count > 2_000_000:
        raise ParseError(f"implausible map size {count}", it.pos)
    out = target if target is not None else {}
    for _ in range(count):
        key = read_int(it)
        value = read_int(it, size_value)
        out[key & 0xFFFFFFFF] = value
    return out


def _rarray(it: Cursor, size: int = 4, sep: int = 1, size_count: int = 4) -> list:
    count = buff_to_int(it.data, it.pos, size_count)
    it.pos += size_count
    if count < 0 or count > 2_000_000:
        raise ParseError(f"implausible array size {count}", it.pos)
    out = []
    for _ in range(count):
        value = buff_to_int(it.data, it.pos, size)
        it.pos += size
        out.append(value)
        if value != 0:
            it.pos += sep
    return out


def read_building_flags(it: Cursor) -> Dict[int, int]:
    """One city's ``{building hash: pillage flag}`` map.

    The upstream walker reads this field with ``readArray(it)`` (a flat ``u32``
    array plus a one-byte separator for non-zero entries) and throws the values
    away.  A byte-level diff of two consecutive saves of 掠夺学院_测试 shows the
    real shape is ``map<BuildingType, bool>``: ``count`` then ``count`` pairs of
    ``{u32 building hash, u8 pillaged}``, i.e. exactly one flag byte per entry —
    which is also what ``readArray`` walks, because building hashes are never 0.

    The flag is what the game exposes as ``pCityBuildings:IsPillaged(type)``
    (``Base/Assets/UI/CitySupport.lua``): pillaging a district pillages the
    topmost building first and only then the district itself, so a district can
    be intact while some of its buildings are already pillaged.
    """
    count = read_int(it)
    if count < 0 or count > 2_000_000:
        raise ParseError(f"implausible building map size {count}", it.pos)
    out: Dict[int, int] = {}
    for _ in range(count):
        key = read_int(it)
        value = 0
        if key != 0:                    # mirrors readArray's separator rule
            value = read_int(it, 1)
        out[key & 0xFFFFFFFF] = value
    return out


def readMapFloat(it: Cursor) -> dict:
    count = read_int(it)
    out: dict = {}
    for _ in range(count):
        key = read_int(it)
        out[key & 0xFFFFFFFF] = read_float(it)
    return out


def readMapBool(it: Cursor) -> dict:
    count = read_int(it)
    out: dict = {}
    for _ in range(count):
        key = read_int(it)
        out[key & 0xFFFFFFFF] = bool(it.data[it.pos])
        it.pos += 1
    return out


def promotions_items(mapping: dict):
    return list(mapping.items())


class PlayerParseError(ParseError):
    pass


def _check(condition: bool, it: Cursor | None = None) -> None:
    if condition:
        return
    offset = None if it is None else it.pos
    raise PlayerParseError(
        f"assertT failed at 0x{offset:x}" if offset is not None else "assertT failed",
        offset,
    )


def _fail(message: str, it: Cursor | None = None) -> None:
    offset = None if it is None else it.pos
    raise PlayerParseError(
        message + (f" at 0x{offset:x}" if offset is not None else ""), offset
    )
