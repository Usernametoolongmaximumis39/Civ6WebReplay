"""Low-level binary cursor helpers shared by the parser layers."""
from __future__ import annotations

import struct


class ParseError(Exception):
    """Raised when a parsing layer cannot make progress."""

    def __init__(self, message: str, offset: int | None = None):
        super().__init__(message)
        self.offset = offset


class LayerError:
    """Records a non-fatal failure of one parsing layer."""

    def __init__(self, section: str, byte_offset: int | None, message: str):
        self.section = section
        self.byte_offset = byte_offset
        self.message = message

    def to_dict(self) -> dict:
        return {
            "section": self.section,
            "offset": self.byte_offset,
            "message": self.message,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"LayerError({self.section!r}, {self.byte_offset!r}, {self.message!r})"


class Cursor:
    """A mutable read cursor over a ``bytes`` buffer.

    Mirrors the C++ ``std::vector<byte>::iterator`` style used by
    CivVIReplay: code advances ``it.advance(n)`` and reads with the module
    level helpers below.
    """

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes | bytearray, pos: int = 0):
        self.data = data
        self.pos = pos

    def advance(self, n: int) -> "Cursor":
        new_pos = self.pos + n
        if new_pos > len(self.data):
            raise ParseError(f"advanced past end of buffer (want {new_pos:#x}, size {len(self.data):#x})", self.pos)
        self.pos = new_pos
        return self


def u32(data, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def i32(data, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def buff_to_int(data, off: int, n: int = 4) -> int:
    """C++ ``buffToInteger(*it, n)``: little-endian, width ``n`` bytes."""
    if n == 4:
        return i32(data, off)
    chunk = bytes(data[off:off + n])
    return int.from_bytes(chunk, "little", signed=False)


def read_int(it: Cursor, n: int = 4) -> int:
    value = buff_to_int(it.data, it.pos, n)
    it.pos += n
    return value


def read_u32(it: Cursor) -> int:
    value = u32(it.data, it.pos)
    it.pos += 4
    return value


def read_bytes(it: Cursor, n: int) -> bytes:
    chunk = bytes(it.data[it.pos:it.pos + n])
    it.pos += n
    return chunk


def read_string(it: Cursor, size_count: int = 4) -> str:
    """C++ ``readString``: length prefix (default u32) then raw bytes."""
    count = buff_to_int(it.data, it.pos, size_count)
    it.pos += size_count
    raw = read_bytes(it, count)
    return raw.decode("utf-8", "replace")


__all__ = [
    "ParseError",
    "LayerError",
    "Cursor",
    "u32",
    "i32",
    "buff_to_int",
    "read_int",
    "read_u32",
    "read_bytes",
    "read_string",
]
