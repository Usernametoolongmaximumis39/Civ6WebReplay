"""Persistent parse cache (``cache/replay.sqlite``)."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "cache" / "replay.sqlite"

# Bumped whenever the turn payload shape changes so stale rows are ignored.
# v0.25: tiles gained ``continent`` / ``water``, ``road`` switched to the route
# index (1-4, 255 = none), ``appeal`` became signed, players gained
# ``commemorations`` / ``pantheon`` and static_info gained religions /
# routeNames / luxuryResources / pseudo / steamId.
# v0.28.1: the turn payload gained the top-level ``religions`` list (per-turn,
# so a religion / its beliefs appear only from the turn they were founded).
# v0.29: ``units[]`` gained ``air`` (``DOMAIN_AIR``), used by the map to fold
# every aircraft on a tile into one shadow-stacked icon.
# v0.30: ``cities[]`` gained ``pillagedBuildings`` (building hashes the city has
# pillaged), used by the city panel / tile panel to mark individual buildings.
# v0.31: tiles gained ``fallout`` (contamination turns) and players gained
# ``wmd`` (``WMD type hash -> count``) for the map marker / 军事 panel.
# v0.32: players gained ``envoyTokens`` (剩余使者, the unspent envoy counter the
# game's top bar draws as ``[ICON_Envoy] N``), used by the 外交 HUD row.
# v0.34: cities gained ``governorPromotionHashes`` (总督点过的晋升类型哈希列表),
# used by the city panel to spell out the promotion names instead of a count.
# v0.40: players gained ``tourismByPlayer`` / ``externalTourist`` /
# ``internalTourist`` (右栏「文化」行的旅游业绩与文化胜利进度), used by the civ card.
# Official base adjacency (None = unavailable, {} = computed zero).
# CCB base adjacency, profile selection and serialized governor establishment.
# Per-district adjacency source accounting for the city/tile panels.
# BBG district adjacency enabled alongside the independent plot-yield profile.
# Vietnam's LOC_CITY_* names are now included in the localization snapshot;
# reparse turns whose display names were cached as untranslated tokens.
# Player resource inventory and actual policy-slot capacities.
# Era score and saved normal/golden age thresholds, including saved shifts.
# Language-neutral adjacency display references for localized API views.
# Governor assignments now retain the target city owner; discard city-ID-only views.
# Unit type keys are unsigned; military strength includes formation/damage offsets.
# Structured package IDs and independent balance MOD release channels.
SCHEMA_VERSION = 26


class ReplayCache:
    def __init__(self, path: Path | str = DEFAULT_CACHE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # a single connection is shared by the background loader and request
        # handlers, so every statement must be serialised through this lock.
        self._lock = threading.RLock()
        self._init()

    def _init(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                create table if not exists save_meta(
                    path text primary key, mtime real, size integer,
                    seed integer, turn integer, timestamp integer,
                    map_name text, map_key text, map_size text, game_speed text, multiplayer integer,
                    parsed_at real);
                create table if not exists turn_state(
                    seed integer, turn integer, mtime real, size integer,
                    payload blob, parsed_at real, ver integer not null default 0,
                    primary key(seed, turn));
                create table if not exists turn_stats(
                    seed integer, turn integer, favor text,
                    primary key(seed, turn));
                """
            )
            # migrate caches written before v0.21 (no `ver` column); old rows keep 0
            metadata_cols = [r[1] for r in self.conn.execute("PRAGMA table_info(save_meta)")]
            if "map_name_en" not in metadata_cols:
                self.conn.execute("alter table save_meta add column map_name_en text")
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(turn_state)")]
            if "ver" not in cols:
                self.conn.execute(
                    "alter table turn_state add column ver integer not null default 0")
            if "yield_rules" not in cols:
                self.conn.execute("alter table turn_state add column yield_rules text")
            if "favor" not in cols:
                self.conn.execute("alter table turn_state add column favor text")
            # Keep different save revisions of the same turn. Switching between
            # folders used to replace the only (seed, turn) row on every visit.
            primary = [r[1] for r in self.conn.execute("PRAGMA table_info(turn_state)") if r[5]]
            if primary == ["seed", "turn"]:
                self.conn.executescript("""
                    begin;
                    alter table turn_state rename to turn_state_old;
                    create table turn_state(
                        seed integer, turn integer, mtime real, size integer,
                        payload blob, parsed_at real, ver integer not null default 0,
                        yield_rules text, favor text,
                        primary key(seed, turn, mtime, size));
                    insert into turn_state select seed, turn, mtime, size,
                        payload, parsed_at, ver, yield_rules, favor from turn_state_old;
                    drop table turn_state_old;
                    commit;
                """)
            self.conn.commit()

    def get_meta(self, path: str, mtime: float, size: int) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "select * from save_meta where path=? and mtime=? and size=?",
                (path, mtime, size),
            ).fetchone()
            return dict(row) if row else None

    def put_meta(self, path: str, mtime: float, size: int, **fields) -> None:
        with self._lock:
            fields.setdefault("parsed_at", time.time())
            cols = ["path", "mtime", "size"] + [k for k in fields]
            vals = [path, mtime, size] + [fields[k] for k in fields]
            placeholders = ",".join("?" * len(cols))
            self.conn.execute(
                f"insert or replace into save_meta({','.join(cols)}) values({placeholders})",
                vals,
            )
            self.conn.commit()

    def get_turn(self, seed: int, turn: int, mtime: float, size: int) -> Optional[bytes]:
        from .tileyields import rules_token
        with self._lock:
            row = self.conn.execute(
                "select payload from turn_state"
                " where seed=? and turn=? and mtime=? and size=? and ver=? and yield_rules=?",
                (seed, turn, mtime, size, SCHEMA_VERSION, rules_token()),
            ).fetchone()
            return row["payload"] if row else None

    def put_turn(self, seed: int, turn: int, mtime: float, size: int, payload: bytes) -> None:
        from .tileyields import rules_token
        with self._lock:
            self.conn.execute(
                "insert or replace into turn_state(seed, turn, mtime, size, payload, parsed_at, ver, yield_rules)"
                " values(?,?,?,?,?,?,?,?)",
                (seed, turn, mtime, size, payload, time.time(), SCHEMA_VERSION, rules_token()),
            )
            self.conn.commit()

    def turn_status(self, seed: int) -> dict:
        """Read readiness and stats availability without fetching payload blobs."""
        from .tileyields import rules_token
        token = rules_token()
        with self._lock:
            rows = self.conn.execute(
                "select turn, mtime, size, favor is not null as has_stats from turn_state"
                " where seed=? and ver=? and yield_rules=?",
                (seed, SCHEMA_VERSION, token),
            ).fetchall()
            return {(r["turn"], r["mtime"], r["size"]): bool(r["has_stats"]) for r in rows}

    # --- per-turn favour snapshots (diplomatic favour, used for per-turn delta)

    def get_turn_stats(self, seed: int, turn: int, mtime: float | None = None,
                       size: int | None = None) -> Optional[str]:
        from .tileyields import rules_token
        with self._lock:
            if mtime is not None:
                row = self.conn.execute(
                    "select favor from turn_state where seed=? and turn=? and mtime=?"
                    " and size=? and ver=? and yield_rules=?",
                    (seed, turn, mtime, size, SCHEMA_VERSION, rules_token()),
                ).fetchone()
                return row["favor"] if row else None
            row = self.conn.execute(
                "select favor from turn_stats where seed=? and turn=?", (seed, turn)
            ).fetchone()
            return row["favor"] if row else None

    def put_turn_stats(self, seed: int, turn: int, favor: str,
                       mtime: float | None = None, size: int | None = None) -> None:
        from .tileyields import rules_token
        with self._lock:
            if mtime is not None:
                self.conn.execute(
                    "update turn_state set favor=? where seed=? and turn=? and mtime=?"
                    " and size=? and ver=? and yield_rules=?",
                    (favor, seed, turn, mtime, size, SCHEMA_VERSION, rules_token()),
                )
                self.conn.commit()
                return
            self.conn.execute(
                "insert or replace into turn_stats(seed, turn, favor) values(?,?,?)",
                (seed, turn, favor),
            )
            self.conn.commit()
