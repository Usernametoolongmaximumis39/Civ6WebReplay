"""Discover replays from a directory of ``.Civ6Save`` files.

Saves are grouped by game seed; each group is one game ordered by turn.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import container, header
from .binary import Cursor, read_int
from .cache import ReplayCache

TURN_OFFSET = 377
M_TIMESTAMP = 0x0EFE6D64


def default_save_dir() -> Path:
    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    return (Path(home) / "Documents" / "My Games" / "Sid Meier's Civilization VI"
            / "Saves" / "Multi" / "auto")


@dataclass
class SaveInfo:
    path: str
    mtime: float
    size: int
    seed: int = 0
    turn: int = 0
    timestamp: int = 0
    map_name: str = ""
    map_size: str = ""
    game_speed: str = ""
    multiplayer: bool = False


def read_meta(data: bytes) -> dict:
    packets = container.parse_all(data)
    info = header.game_info(packets)
    seed = header.game_seed(packets)
    ts = 0
    ts_pkt = packets[0].get_packet(M_TIMESTAMP)
    if ts_pkt is not None and isinstance(ts_pkt.value, int):
        ts = ts_pkt.value
    blob = container.load_game_state(data)
    turn = read_int(Cursor(blob, TURN_OFFSET))
    return {"seed": seed, "turn": turn, "timestamp": ts, **info}


def discover(save_dir: Path | str | None = None,
             cache: Optional[ReplayCache] = None) -> List[SaveInfo]:
    save_dir = Path(save_dir or default_save_dir())
    cache = cache or ReplayCache()
    infos: List[SaveInfo] = []
    if not save_dir.exists():
        return infos
    for path in sorted(save_dir.glob("*.Civ6Save")):
        st = path.stat()
        meta = cache.get_meta(str(path), st.st_mtime, st.st_size)
        if meta is None:
            try:
                meta = read_meta(path.read_bytes())
            except Exception:
                meta = {"seed": 0, "turn": 0, "timestamp": 0, "map_name": "",
                        "map_size": "", "game_speed": "", "multiplayer": False}
            cache.put_meta(str(path), st.st_mtime, st.st_size, **meta)
        infos.append(SaveInfo(
            path=str(path), mtime=st.st_mtime, size=st.st_size,
            seed=int(meta["seed"]), turn=max(0, int(meta["turn"])),
            timestamp=int(meta["timestamp"]),
            map_name=meta.get("map_name", ""), map_size=meta.get("map_size", ""),
            game_speed=meta.get("game_speed", ""),
            multiplayer=bool(meta.get("multiplayer", False)),
        ))
    return infos


def group_by_seed(infos: List[SaveInfo]) -> Dict[int, List[SaveInfo]]:
    groups: Dict[int, List[SaveInfo]] = {}
    for info in infos:
        groups.setdefault(info.seed, []).append(info)
    for group in groups.values():
        group.sort(key=lambda s: (s.turn, s.mtime))
    return groups


def latest_save_for_seed(infos: List[SaveInfo], seed: int) -> Optional[SaveInfo]:
    group = [i for i in infos if i.seed == seed]
    if not group:
        return None
    return max(group, key=lambda s: (s.turn, s.mtime))
