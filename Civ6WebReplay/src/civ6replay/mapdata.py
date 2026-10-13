"""Map / tile parsing (port of CivVIReplay ``ParseMap``)."""
from __future__ import annotations

from typing import List, Tuple

from .binary import Cursor, ParseError, read_int, read_u32
from .model import Tile

MAP_BEGIN = bytes([
    0x0A, 0, 0, 0, 0x0B, 0, 0, 0, 0x0C, 0, 0, 0, 0x0D, 0, 0, 0,
    0x0E, 0, 0, 0, 0x0F, 0, 0, 0, 0x06, 0, 0, 0,
])


def signed16(value: int) -> int:
    """Interpret a raw 16-bit field as signed (appeal: ``0xFFFF`` is ``-1``).

    The game stores appeal as a signed 16-bit value; reading it unsigned turned
    every negative tile into 65535 (v0.25 fix).
    """
    value &= 0xFFFF
    return value - 0x10000 if value > 0x7FFF else value


def find_map_begin(data: bytes) -> int:
    idx = data.find(MAP_BEGIN)
    if idx == -1:
        raise ParseError("MAP_BEGIN anchor not found")
    return idx


def parse_map(data: bytes) -> Tuple[int, List[Tile], int]:
    """Return ``(width, tiles, height)``; byte-exact check happens at ``width``."""
    cur = Cursor(data)
    cur.pos = find_map_begin(data) + 28

    size = read_int(cur)
    if size <= 0 or size > 5_000_000:
        raise ParseError(f"implausible tile count {size}", cur.pos)

    tiles: List[Tile] = []
    for _ in range(size):
        tile = Tile()
        read_int(cur)  # group0
        read_int(cur)  # group1
        read_int(cur)  # landmass
        tile.terrain = read_u32(cur)
        tile.feature = read_u32(cur)
        cur.pos += 2
        tile.continent = read_int(cur)
        cur.pos += 1
        tile.resource = read_u32(cur)
        read_int(cur, 2)  # resource count
        tile.improvment = read_u32(cur)
        cur.pos += 1
        tile.road = read_int(cur, 1)
        tile.roadLvl = read_int(cur, 1)
        # v0.25: appeal is a *signed* 16-bit value (the game stores -1 as
        # 0xFFFF); reading it unsigned turned every negative appeal into 65535.
        tile.appeal = signed16(read_int(cur, 2))
        cur.pos += 3
        tile.riverCount = cur.data[cur.pos]
        cur.pos += 1
        tile.river = cur.data[cur.pos]
        cur.pos += 1
        tile.cliffbitmap = cur.data[cur.pos]
        cur.pos += 1
        tile.pillage = read_int(cur, 1)
        found = read_int(cur, 1)
        cur.pos += 1
        tile.bOverlay = read_u32(cur)

        if tile.bOverlay:
            count = read_int(cur)
            for _ in range(count):
                cur.pos += 11
                value = read_int(cur)
                cur.pos += 1
                count2 = read_int(cur)
                if value:
                    cur.pos += 20 * count2

        if found & 0x40:
            tile.iCity = read_int(cur, 2)
            cur.pos += 2
            cur.pos += 4
            tile.iDistrict = read_int(cur, 2)
            cur.pos += 2
            tile.iPlayer = read_int(cur, 1)
            tile.wonder = read_u32(cur)
        tiles.append(tile)

    cur.pos += 4
    width = read_int(cur)
    if width <= 0:
        raise ParseError(f"invalid map width {width}", cur.pos)
    height = size // width
    return width, tiles, height


