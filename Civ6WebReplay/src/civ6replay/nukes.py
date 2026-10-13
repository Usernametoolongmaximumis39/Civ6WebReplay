"""Nuclear state: per-plot contamination and the per-player WMD stockpile.

Both live in the tail of the decompressed game state (the plot table sits
inside the last player records, the stockpile map inside every player record),
which the offset walkers in ``players`` do not cover.  They are found by
signature instead, and each signature is validated before anything is read:

contamination - one 9-byte row per plot: a u32 "turns remaining" followed by
five constant bytes, introduced by a u32 plot count and a u32 four.  Zero means
clean.  The 核弹测试 saves (a jet bomber dropping one *nuclear* device) show
0 -> 10 on the seven blast tiles and 10 -> 9 after one turn.

WMD stockpile - per player: a u32 iPlayer, a u32 one, a u32 entry count and
then that many (type hash, count) pairs, the first of which is always the
``WMD_NUCLEAR_DEVICE`` type.  The row starts at the nuclear hash, so the three
leading fields are read backwards from it.
"""
from __future__ import annotations

import struct
from typing import Dict, List, Optional

from .hash import crc32_type

# ``~crc32`` of the two rows of Base/Assets/Gameplay/Data/WMDs.xml.
WMD_NUCLEAR_DEVICE = crc32_type("WMD_NUCLEAR_DEVICE") & 0xFFFFFFFF
WMD_THERMONUCLEAR_DEVICE = crc32_type("WMD_THERMONUCLEAR_DEVICE") & 0xFFFFFFFF
WMD_TYPES = (WMD_NUCLEAR_DEVICE, WMD_THERMONUCLEAR_DEVICE)

FALLOUT_ROW = 9                        # bytes per plot in the contamination table
FALLOUT_TAIL = bytes([1, 4, 0, 0, 0])  # constant part of every row
FALLOUT_PROBES = (0, 1, 2)             # rows checked before trusting a table


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_fallout(blob: bytes, plots: int) -> List[int]:
    """Turns of contamination per plot (0 = clean).

    A table that cannot be located yields ``plots`` zeros, so a game patch that
    moves it degrades into "nothing is contaminated" instead of breaking the
    turn payload.
    """
    if plots <= 0:
        return []
    needle = struct.pack("<I", plots)
    pos = blob.find(needle)
    while pos >= 0:
        start = pos + 8                       # header: <plot count><4>
        end = start + plots * FALLOUT_ROW
        if end <= len(blob):
            probes = list(FALLOUT_PROBES) + [plots // 2, plots - 2]
            ok = all(blob[start + k * FALLOUT_ROW + 4:
                          start + k * FALLOUT_ROW + 9] == FALLOUT_TAIL
                     for k in probes if 0 <= k < plots)
            if ok and blob[end - FALLOUT_ROW + 4:end - FALLOUT_ROW + 5] == b"\x01":
                return [_u32(blob, start + k * FALLOUT_ROW)
                        for k in range(plots)]
        pos = blob.find(needle, pos + 1)
    return [0] * plots


def parse_wmd(blob: bytes) -> Dict[int, Dict[int, int]]:
    """``iPlayer -> {WMD type hash: count}``; players without stock are absent."""
    out: Dict[int, Dict[int, int]] = {}
    pat = struct.pack("<I", WMD_NUCLEAR_DEVICE)
    pos = blob.find(pat)
    while pos >= 0:
        if pos >= 12:
            i_player = _u32(blob, pos - 12)
            entries = _u32(blob, pos - 4)
            if 0 <= i_player < 64 and 1 <= entries <= 64 \
                    and pos + entries * 8 <= len(blob):
                stock = {_u32(blob, pos + 8 * k): _u32(blob, pos + 8 * k + 4)
                         for k in range(entries)}
                if WMD_NUCLEAR_DEVICE in stock:
                    out[i_player] = stock
        pos = blob.find(pat, pos + 1)
    return out


def stock_total(stock: Optional[dict]) -> int:
    """Total devices in one stockpile map (used by the tests)."""
    return sum(int(v) for v in (stock or {}).values())
