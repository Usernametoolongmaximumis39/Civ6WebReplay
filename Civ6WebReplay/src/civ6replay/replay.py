"""Discover replays from a ``.Civ6Save`` file or a directory of saves.

Saves are grouped by game seed; each group is one game ordered by turn.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import container, header
from .binary import Cursor, read_int
from .cache import ReplayCache
from .loading import load_workers

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
    map_key: str = ""
    map_name_en: str = ""


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
             cache: Optional[ReplayCache] = None, *, workers: int | None = None) -> List[SaveInfo]:
    save_dir = Path(save_dir or default_save_dir())
    cache = cache or ReplayCache()
    infos: List[SaveInfo] = []
    if not save_dir.exists():
        return infos
    if save_dir.is_file():
        paths = [save_dir] if save_dir.suffix.lower() == ".civ6save" else []
    else:
        paths = sorted(p for p in save_dir.iterdir()
                       if p.is_file() and p.suffix.lower() == ".civ6save")
    def inspect(path):
        # A live autosave may disappear while the game rotates its files.
        try:
            st = path.stat()
        except OSError:
            return None
        meta = cache.get_meta(str(path), st.st_mtime, st.st_size)
        if meta is None:
            try:
                meta = read_meta(path.read_bytes())
            except Exception:
                meta = {"seed": 0, "turn": 0, "timestamp": 0, "map_name": "",
                        "map_size": "", "game_speed": "", "multiplayer": False}
            cache.put_meta(str(path), st.st_mtime, st.st_size, **meta)
        return SaveInfo(
            path=str(path), mtime=st.st_mtime, size=st.st_size,
            seed=int(meta["seed"]), turn=max(0, int(meta["turn"])),
            timestamp=int(meta["timestamp"]),
            map_name=meta.get("map_name", ""), map_size=meta.get("map_size", ""),
            game_speed=meta.get("game_speed", ""),
            multiplayer=bool(meta.get("multiplayer", False)),
            map_key=meta.get("map_key", ""),
            map_name_en=meta.get("map_name_en") or "",
        )
    count = min(load_workers(workers), len(paths))
    if count > 1:
        with ThreadPoolExecutor(max_workers=count, thread_name_prefix="civ6-scan") as pool:
            infos = [info for info in pool.map(inspect, paths) if info is not None]
    else:
        infos = [info for path in paths if (info := inspect(path)) is not None]
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
