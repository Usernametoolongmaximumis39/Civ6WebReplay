"""Saved cumulative plot yield changes, including disaster fertility.

The Feature component stores a dense plot-to-slot index followed by sparse
six-yield maps. Read current totals; never replay probabilistic disaster rules.
An absent/unknown layout raises ParseError instead of inventing zero fertility.
"""
from __future__ import annotations

import struct

from .binary import ParseError
from .hash import crc32_type
from .mapdata import find_map_begin

YIELDS = tuple(crc32_type("YIELD_" + name) & 0xFFFFFFFF for name in
               ("FOOD", "PRODUCTION", "GOLD", "SCIENCE", "CULTURE", "FAITH"))
FEATURE = struct.pack("<I", 7) + b"Feature"


def parse_plot_changes(blob: bytes, plots: int) -> dict[int, dict[int, int]]:
    """Return nonzero signed changes by plot index and yield hash.

    Validate the component version, baseline map, plot count, slot permutation,
    and every yield key. Reject ambiguity and truncated data as unknown state.
    """
    if not 0 < plots <= 5_000_000:
        raise ParseError("invalid plot count for saved yield changes")
    start = find_map_begin(blob) + 28
    found = []
    pos = blob.find(FEATURE, start)
    while pos >= 0:
        try:
            q = pos + len(FEATURE)
            # Component-specific metadata varies; observed kind/version are 7/4.
            _, kind, version = struct.unpack_from("<III", blob, q)
            if (kind, version) != (7, 4):
                raise ValueError("unknown Feature component layout")
            q += 12

            def vector():
                nonlocal q
                n, = struct.unpack_from("<I", blob, q)
                if n != 6:
                    raise ValueError("invalid yield map size")
                q += 4
                values = {}
                for _ in range(n):
                    key, value = struct.unpack_from("<Ii", blob, q)
                    q += 8
                    if key not in YIELDS or key in values:
                        raise ValueError("unknown or duplicate yield key")
                    values[key] = value
                return {key: value for key, value in values.items() if value}

            if vector():
                raise ValueError("unsupported nonzero default yield map")
            count, = struct.unpack_from("<I", blob, q)
            q += 4
            if count != plots:
                raise ValueError("saved yield plot count mismatch")
            indices = struct.unpack_from(f"<{count}i", blob, q)
            q += count * 4
            slots, = struct.unpack_from("<I", blob, q)
            q += 4
            if slots > plots or q + slots * 52 > len(blob):
                raise ValueError("invalid saved yield slot count")
            if any(i < -1 or i >= slots for i in indices):
                raise ValueError("saved yield index out of range")
            if sorted(i for i in indices if i >= 0) != list(range(slots)):
                raise ValueError("saved yield slots are not a permutation")
            vectors = [vector() for _ in range(slots)]
            found.append({i: vectors[k] for i, k in enumerate(indices)
                          if k >= 0 and vectors[k]})
        except (struct.error, ValueError):
            pass
        pos = blob.find(FEATURE, pos + len(FEATURE))
    if len(found) != 1:
        raise ParseError("saved plot yield table missing, unsupported or ambiguous")
    return found[0]
