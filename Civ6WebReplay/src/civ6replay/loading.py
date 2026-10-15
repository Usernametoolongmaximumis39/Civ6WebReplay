"""Picklable CPU worker; never opens or writes the replay cache."""
from __future__ import annotations

import json
import os
from pathlib import Path


def load_workers(value: int | None = None) -> int:
    if value is None:
        configured = os.environ.get("CIV6_REPLAY_WORKERS")
        if configured is None:
            return max(1, (os.cpu_count() or 1) // 2)
        value = int(configured)
    if not 1 <= value <= 16:
        raise ValueError("存档并发数必须在 1 到 16 之间。")
    return value


def favor_snapshot(payload: dict) -> str:
    return json.dumps({str(p.get("iPlayer")): int(p.get("diploFavor") or 0)
                       for p in payload.get("players", [])}, separators=(",", ":"))


def parse_turn(path: str, mapwrap: dict) -> tuple[bytes, str]:
    # Import here so Windows spawn loads only the parser, without starting a
    # server, a manager or another executor. Send compressed bytes over IPC.
    from .state import parse_save, turn_payload, encode_payload
    state = parse_save(Path(path).read_bytes())
    payload = turn_payload(state, wrap_x=mapwrap.get(state.map_key, True))
    return encode_payload(payload), favor_snapshot(payload)
