"""BCY configuration values stored as hashed integer parameters in save headers."""
from .hash import crc32_type as H
from .container import TYPE_INT

PARAMS = {H("BBCC_SETTING"): ("scope", {-1, 0, 1}),
          H("BBCC_SETTING_YIELD"): ("mode", {0, 1, 2})}


def parse_bcy(packets):
    values = {"scope": set(), "mode": set()}
    def walk(packet, depth=0):
        if depth > 6:
            return
        match = PARAMS.get(packet.marker & 0xFFFFFFFF)
        if match and packet.type == TYPE_INT and type(packet.value) is int:
            key, allowed = match
            if packet.value in allowed:
                values[key].add(packet.value)
            else:
                values[key].add(None)
        for child in packet.packets.values():
            walk(child, depth + 1)
    for packet in packets or ():
        walk(packet)
    # Duplicate header sections must agree; missing/conflicting is unknown.
    return {key: next(iter(found)) if len(found) == 1 else None
            for key, found in values.items()}
