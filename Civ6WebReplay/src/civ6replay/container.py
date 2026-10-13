"""CIV6 container parsing + game-state decompression."""
from __future__ import annotations

import zlib
from typing import List, Optional, Tuple

from .binary import Cursor, ParseError, buff_to_int, read_int, read_u32

CIV6_MAGIC = b"CIV6"
END_COMPRESSED = b"\x00\x00\xff\xff\x02\x00\x00\x00"
CHUNK = 65536

TYPE_BOOL = 1
TYPE_INT = 2
TYPE_POINTER = 3
TYPE_STRING = 5
TYPE_UTF16 = 6
TYPE_OBJECT = 10
TYPE_ARRAY = 11
TYPE_TIMESTAMP = 20
TYPE_COMPRESSED = 24


class Packet:
    __slots__ = ("marker", "type", "length", "info", "value", "packets", "order", "found")

    def __init__(self):
        self.marker = 0
        self.type = 0
        self.length = 0
        self.info = 0
        self.value = None
        self.packets: dict = {}
        self.order: List[int] = []
        self.found = 0

    def get_int(self, marker: int) -> int:
        p = self.packets.get(marker)
        return p.value if p is not None else 0xFFFFFFFF

    def get_str(self, marker: int):
        p = self.packets.get(marker)
        return p.value if p is not None else None

    def get_packet(self, marker: int) -> Optional["Packet"]:
        return self.packets.get(marker)


def _parse_array(cur: Cursor) -> Packet:
    p = Packet()
    p.type = TYPE_ARRAY
    count = read_int(cur)
    p.length = count
    for _ in range(count):
        entry = _parse_entry(cur, -1)
        p.packets[entry.marker] = entry
        p.order.append(entry.marker)
    return p


def _parse_entry(cur: Cursor, i_array: int) -> Packet:
    result = Packet()
    result.marker = read_u32(cur) if i_array == -1 else i_array
    result.type = read_u32(cur)
    result.length = buff_to_int(cur.data, cur.pos, 3)
    cur.pos += 3
    result.found = cur.data[cur.pos]
    cur.pos += 1
    result.info = read_u32(cur)

    t = result.type
    if t == TYPE_BOOL:
        result.value = cur.data[cur.pos]
        cur.pos += 4
    elif t in (TYPE_INT, TYPE_POINTER):
        result.value = read_int(cur, 4)
    elif t == 0x15:
        cur.pos += 8
    elif t in (4, TYPE_STRING):
        n = result.length
        result.value = bytes(cur.data[cur.pos:cur.pos + n])
        cur.pos += n if n else 4
    elif t == TYPE_UTF16:
        n = result.length * 2
        result.value = bytes(cur.data[cur.pos:cur.pos + n])
        cur.pos += n
    elif t == TYPE_TIMESTAMP:
        result.value = int.from_bytes(cur.data[cur.pos:cur.pos + 8], "little")
        cur.pos += 8
    elif t == TYPE_COMPRESSED:
        cur.pos += 12
        cur.pos += result.length - 12
    elif t == 0x0D:
        cur.pos += 8
    elif t == TYPE_OBJECT:
        _read_array_into(cur, result, is_array=False)
    elif t == TYPE_ARRAY:
        _read_array_into(cur, result, is_array=True)
    else:
        raise ParseError(f"unknown packet type {t}", cur.pos)
    return result


def _read_array_into(cur: Cursor, result: Packet, is_array: bool) -> None:
    array_len = read_int(cur)
    result.length = array_len
    result.value = array_len
    for i in range(array_len):
        entry = _parse_entry(cur, i if is_array else -1)
        result.packets[entry.marker] = entry
        result.order.append(entry.marker)


def _walk(data: bytes) -> Tuple[List[Packet], int]:
    """Walk the top-level packet tree; return ``(packets, compressed_start)``."""
    if data[:4] != CIV6_MAGIC:
        raise ParseError("not a CIV6 save (bad magic)")
    packets: List[Packet] = []
    cur = Cursor(data, 8)
    packets.append(_parse_array(cur))
    cur.pos += 4
    cur.pos += 4
    packets.append(_parse_array(cur))
    cur.pos += 4
    packets.append(_parse_array(cur))
    cur.pos += 4
    packets.append(_parse_array(cur))
    count = read_int(cur)
    for _ in range(count):
        cur.pos += 4
        packets.append(_parse_array(cur))
    packets.append(_parse_array(cur))
    cur.pos += 4
    return packets, cur.pos


def parse_all(data: bytes) -> List[Packet]:
    return _walk(data)[0]


def inflate_chunked(raw: bytes) -> bytes:
    """Wire format: 64 KiB blocks separated by a 4-byte filler."""
    cleaned = bytearray()
    pos = 0
    n = len(raw)
    while pos < n:
        take = min(CHUNK, n - pos)
        cleaned += raw[pos:pos + take]
        pos += take
        if pos < n:
            pos += 4
    d = zlib.decompressobj()
    out = d.decompress(bytes(cleaned))
    out += d.flush()
    return out


def compressed_region(data: bytes) -> Tuple[int, int]:
    start = _walk(data)[1]
    end = data.find(END_COMPRESSED, start)
    if end == -1:
        raise ParseError("END_COMPRESSED marker not found", start)
    return start, end


def load_game_state(data: bytes) -> bytes:
    """Decompress and return the full game-state stream (tiles + players)."""
    start, end = compressed_region(data)
    return inflate_chunked(data[start:end + 4])
