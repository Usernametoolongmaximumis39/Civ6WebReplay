"""Runtime access to the bundled game-database snapshot."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "gamedb" / "vanilla" / "gamedb.sqlite"
ICONS_INDEX = Path(__file__).resolve().parents[2] / "assets" / "icons" / "index.json"


class GameDB:
    def __init__(self, db_path: Path | str = DEFAULT_DB,
                 icons_index: Path | str = ICONS_INDEX):
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self.types: Dict[int, dict] = {}
        self.names: Dict[int, dict] = {}
        self.icons: Dict[int, str] = {}
        self._lock = threading.RLock()
        if self.db_path.exists():
            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._load()
        self._load_icons(Path(icons_index))

    # --- loading -----------------------------------------------------------
    def _load(self) -> None:
        for row in self.conn.execute("select hash, type, kind, category, icon_path from types"):
            self.types[int(row["hash"]) & 0xFFFFFFFF] = {
                "type": row["type"], "kind": row["kind"], "category": row["category"],
            }
        for row in self.conn.execute("select hash, en, zh from names"):
            self.names[int(row["hash"]) & 0xFFFFFFFF] = {"en": row["en"], "zh": row["zh"]}

    def _load_icons(self, path: Path) -> None:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.icons = {int(k) & 0xFFFFFFFF: v for k, v in data.items()}

    @property
    def available(self) -> bool:
        return self.conn is not None

    # --- lookups -----------------------------------------------------------
    def type_str(self, h: int) -> str:
        info = self.types.get(h & 0xFFFFFFFF)
        return info["type"] if info else f"0x{h & 0xFFFFFFFF:08X}"

    def category(self, h: int) -> Optional[str]:
        info = self.types.get(h & 0xFFFFFFFF)
        return info["category"] if info else None

    def name(self, h: int) -> str:
        hm = h & 0xFFFFFFFF
        n = self.names.get(hm)
        if n and (n["zh"] or n["en"]):
            return n["zh"] or n["en"]
        info = self.types.get(hm)
        if info:
            t = info["type"]
            for prefix in ("TECHNOLOGY_", "CIVIC_", "BUILDING_", "UNIT_", "DISTRICT_",
                           "TERRAIN_", "FEATURE_", "RESOURCE_", "IMPROVEMENT_",
                           "PROJECT_", "YIELD_", "GOVERNOR_", "POLICY_", "RELIGION_"):
                if t.startswith(prefix):
                    t = t[len(prefix):]
                    break
            return t.replace("_", " ").title()
        return f"0x{hm:08X}"

    def names(self, hashes) -> Dict[int, str]:
        return {h & 0xFFFFFFFF: self.name(h) for h in hashes}

    def icon(self, h: int) -> Optional[str]:
        return self.icons.get(h & 0xFFFFFFFF)

    def luxury_resources(self) -> List[int]:
        """Hashes of every luxury resource (v0.25 continent badges).

        Reads ``resources.class == RESOURCECLASS_LUXURY`` from the snapshot;
        returns ``[]`` when the table is missing (older snapshot).
        """
        if not self.available:
            return []
        try:
            with self._lock:
                rows = list(self.conn.execute(
                    "select hash from resources where class='RESOURCECLASS_LUXURY'"))
        except sqlite3.OperationalError:
            return []
        return sorted(int(r[0]) & 0xFFFFFFFF for r in rows)

    # --- unique-district / building placement (v0.22) ----------------------
    def replaces(self, h: int) -> Optional[int]:
        """Unique district/building/governor hash -> base hash (or ``None``).

        Reads the ``replaces`` snapshot table built from ``DistrictReplaces`` /
        ``BuildingReplaces`` / ``GovernorReplaces``. Used for gameplay rules
        and placement; unique district artwork resolves by its own TYPE.
        """
        r = self.row("replaces", h)
        if not r:
            return None
        base = r.get("base_hash")
        return None if base is None else int(base) & 0xFFFFFFFF

    def building_district(self, h: int) -> Optional[int]:
        """Building hash -> prerequisite district hash (``None`` = city center).

        Reads the ``building_district`` snapshot table (from
        ``Buildings.PrereqDistrict``); buildings without a prerequisite district
        (palace / monument / walls …) resolve to the containing city center.
        """
        r = self.row("building_district", h, key="building_hash")
        if not r:
            return None
        d = r.get("district_hash")
        return None if d is None else int(d) & 0xFFFFFFFF

    def replaces_map(self) -> Dict[int, int]:
        """Full ``{hash: base_hash}`` replacement map (empty when unavailable)."""
        out: Dict[int, int] = {}
        if not self.available:
            return out
        try:
            with self._lock:
                rows = list(self.conn.execute("select hash, base_hash from replaces"))
        except sqlite3.OperationalError:
            return out
        for h, base in rows:
            if base is None:
                continue
            out[int(h) & 0xFFFFFFFF] = int(base) & 0xFFFFFFFF
        return out

    def building_district_map(self) -> Dict[int, int]:
        """Full ``{building_hash: district_hash}`` map; unset -> city center.

        Rows whose ``district_hash`` is NULL (no prerequisite district) are
        omitted, matching ``building_district`` returning ``None``.
        """
        out: Dict[int, int] = {}
        if not self.available:
            return out
        try:
            with self._lock:
                rows = list(self.conn.execute(
                    "select building_hash, district_hash from building_district"))
        except sqlite3.OperationalError:
            return out
        for b, d in rows:
            if d is None:
                continue
            out[int(b) & 0xFFFFFFFF] = int(d) & 0xFFFFFFFF
        return out

    def building_cost_map(self) -> Dict[int, int]:
        """``{building_hash: cost}`` (``Buildings.Cost``), empty when unavailable.

        v0.35: 地图上一格只贴一栋建筑，前端靠这张表在**同一格的几栋**里挑
        「最后那栋」——一片区域的建筑基本是一条升级链（图书馆 90 → 大学 250 →
        研究实验室 440），造价最大的那栋就是链条末端。城墙不靠造价定档（平衡
        MOD 下三档造价 / 血量都可能撞车），走 :meth:`wall_defense` 的 ``order``。
        快照缺这一列 / 整表时返回 ``{}``，前端退回列表末位。
        """
        out: Dict[int, int] = {}
        if not self.available:
            return out
        try:
            with self._lock:
                rows = list(self.conn.execute("select hash, cost from buildings"))
        except sqlite3.OperationalError:
            return out
        for h, cost in rows:
            if cost is None:
                continue
            out[int(h) & 0xFFFFFFFF] = int(cost)
        return out

    # --- city walls (v0.26) ------------------------------------------------
    def wall_defense(self) -> Dict[str, object]:
        """City-wall caps for the front end.

        ``buildings`` maps a wall building hash -> ``{"hp", "order"}`` where
        ``order`` numbers the tiers by cost ascending (BBG gives all three tiers
        75 HP, so the HP alone cannot tell the tiers apart).  ``urbanDefense`` is
        the cap granted by 钢铁 (``ModifierArguments`` of
        ``STEEL_UNLOCK_URBAN_DEFENSES``) and ``steelTech`` the ``TECH_STEEL``
        hash.  Every field degrades to an empty/``None`` value on a snapshot
        that predates the ``params`` table or the ``outer_defense_hp`` column.
        """
        out: Dict[str, object] = {"buildings": {}, "urbanDefense": None,
                                  "steelTech": None}
        if not self.available:
            return out
        buildings: Dict[str, dict] = {}
        try:
            with self._lock:
                rows = list(self.conn.execute(
                    "select hash, outer_defense_hp, wall_order from buildings "
                    "where outer_defense_hp > 0"))
        except sqlite3.OperationalError:
            rows = []
        for h, hp, order in rows:
            buildings[str(int(h) & 0xFFFFFFFF)] = {
                "hp": int(hp or 0), "order": int(order or 0)}
        out["buildings"] = buildings
        try:
            with self._lock:
                prows = list(self.conn.execute("select name, value from params"))
        except sqlite3.OperationalError:
            prows = []
        for name, value in prows:
            if value is None:
                continue
            if name == "steel_urban_defense":
                try:
                    out["urbanDefense"] = int(value)
                except (TypeError, ValueError):
                    pass
            elif name == "steel_tech_hash":
                out["steelTech"] = int(value) & 0xFFFFFFFF
        return out

    def row(self, table: str, h: int, key: str = "hash"):
        if not self.available:
            return None
        try:
            with self._lock:
                cur = self.conn.execute(
                    f"select * from [{table}] where [{key}]=?", (h & 0xFFFFFFFF,)
                )
                r = cur.fetchone()
        except sqlite3.OperationalError:
            return None  # table absent in an older snapshot
        return dict(r) if r else None

    # --- yields ------------------------------------------------------------
    def tile_yields(self, terrain: int, feature: int, resource: int,
                    improvement: int, road: int = 0) -> Dict[int, int]:
        yields: Dict[int, int] = {}
        if not self.available:
            return yields
        checks = [("terrain", terrain), ("feature", feature),
                  ("resource", resource), ("improvement", improvement)]
        with self._lock:
            for cat, h in checks:
                if h in (None, 0xFFFFFFFF, 0):
                    continue
                for yhash, amount in self.conn.execute(
                    "select yield_hash, amount from yield_changes where category=? and hash=?",
                    (cat, h & 0xFFFFFFFF),
                ):
                    y = int(yhash) & 0xFFFFFFFF
                    yields[y] = yields.get(y, 0) + int(amount)
        return yields

    # --- trees -------------------------------------------------------------
    def tree(self, kind: str) -> List[dict]:
        if not self.available:
            return []
        table = {"technology": "technologies", "civic": "civics"}.get(kind, kind + "s")
        with self._lock:
            rows = self.conn.execute(
                f"select hash, name_key, cost, era from [{table}]"
            ).fetchall()
            prereq_rows = list(self.conn.execute(
                "select hash, prereq_hash from prereqs where kind=?", (kind,)))
        prereqs: Dict[int, List[int]] = {}
        for h, p in prereq_rows:
            if h is None or p is None:
                continue
            prereqs.setdefault(int(h) & 0xFFFFFFFF, []).append(int(p) & 0xFFFFFFFF)
        out = []
        for r in rows:
            h = int(r["hash"]) & 0xFFFFFFFF
            out.append({
                "hash": h,
                "name": self.name(h),
                "type": self.type_str(h),
                "cost": r["cost"],
                "era": r["era"],
                "parents": prereqs.get(h, []),
            })
        return out


_SINGLETON: Optional[GameDB] = None


def get_gamedb() -> GameDB:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = GameDB()
    return _SINGLETON
