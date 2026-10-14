"""Turn a raw ``.Civ6Save`` into a fully-linked :class:`GameState`.

Every parsing layer runs under its own guard; a failing layer records a
:class:`LayerError` and leaves its data empty instead of aborting the whole
parse (see the tool's degradation policy).
"""
from __future__ import annotations

import gzip
import json
from typing import List, Optional

from . import container, header, mapdata, players as players_mod
from . import nukes as nukes_mod
from . import mods as mods_mod
from . import modes as modes_mod
from . import unsupported as unsupported_mod
from . import visibility as visibility_mod
from .gamedb import get_gamedb
from .identities import get_identities
from .adjacency import calculate_adjacencies
from .tileyields import calculate_tile_yields, rules_token
from .bcy import parse_bcy
from .binary import Cursor, LayerError, read_int
from .hash import crc32_type
from .model import (GameState, NONE_U32, Player, PlayerInfo, Religion,
                    governor_assigned_to)

TURN_OFFSET = 377

# Layers whose failure changes what the map / panels *show*; those are the only
# ones the front-end banner reports (v0.25).  Everything else (e.g. the players
# tail) is a debug-level note.
DISPLAY_LAYERS = ("map", "turn", "players_info", "visibility", "links")


def _note(state: "GameState", section: str, offset, message: str) -> None:
    """Record a degradation note in ``layerErrors`` or ``tailWarnings``."""
    if section in DISPLAY_LAYERS:
        state.layerErrors.append(LayerError(section, offset, message))
    else:
        state.tailWarnings.append(f"{section}: {message}")


def _mask(v: int) -> int:
    return v & 0xFFFFFFFF


def _prettify(name: str) -> str:
    return name.replace("_", " ").strip()


def _city_display_name(raw: str) -> str:
    """Resolve a raw city-name token to its display name.

    Raw names in the save are either a ``LOC_CITY_NAME_<X>`` localization tag
    (resolved through the bundled snapshot: zh -> en -> prettified token) or a
    player-typed rename (kept verbatim).
    """
    if not raw:
        return ""
    if raw.startswith("LOC_"):
        from .loc import get_loc

        zh, en = get_loc().city_name(raw)
        if zh:
            return zh
        if en:
            return en
        token = raw
        if token.startswith("LOC_CITY_NAME_"):
            token = token[len("LOC_CITY_NAME_"):]
        elif token.startswith("LOC_CITY_"):
            token = token[len("LOC_CITY_"):]
        return _prettify(token)
    return raw


# unit formation class -> category token (mirrors the in-game stacking slots)
_CATEGORY_MAP: Optional[dict] = None


def unit_category(info) -> str:
    """Classify a unit from its game-db ``units`` row (or ``None``).

    ``make_trade_route`` -> ``trade``; ``FORMATION_CLASS_SUPPORT`` -> ``sup``;
    civilian with ``religious_strength > 0`` -> ``rel``; other civilian ->
    ``civ``; land/naval/air combat -> ``mil``; unknown/absent -> ``mil``.
    """
    if not info:
        return "mil"
    if info.get("make_trade_route"):
        return "trade"
    formation = info.get("formation_class") or ""
    if formation == "FORMATION_CLASS_SUPPORT":
        return "sup"
    if formation == "FORMATION_CLASS_CIVILIAN":
        return "rel" if (info.get("religious_strength") or 0) > 0 else "civ"
    return "mil"


def _category_map(db) -> dict:
    """hash -> category for every unit in the snapshot (built once, cached)."""
    global _CATEGORY_MAP
    if _CATEGORY_MAP is None:
        table: dict = {}
        if db.available:
            for r in db.conn.execute(
                    "select hash, formation_class, make_trade_route, religious_strength from units"):
                table[int(r["hash"]) & 0xFFFFFFFF] = unit_category({
                    "formation_class": r["formation_class"],
                    "make_trade_route": r["make_trade_route"],
                    "religious_strength": r["religious_strength"],
                })
        for h, entry in get_identities().entries.items():
            if entry.get("unitInfo"):
                table[h] = unit_category(entry["unitInfo"])
        _CATEGORY_MAP = table
    return _CATEGORY_MAP


_SEA_MAP: Optional[dict] = None


def _sea_map(db) -> dict:
    """hash -> 1/0 for naval units (``units.domain == DOMAIN_SEA``)."""
    global _SEA_MAP
    if _SEA_MAP is None:
        table: dict = {}
        if db.available:
            for r in db.conn.execute("select hash, domain from units"):
                table[int(r["hash"]) & 0xFFFFFFFF] = (
                    1 if (r["domain"] or "") == "DOMAIN_SEA" else 0)
        for h, entry in get_identities().entries.items():
            if entry.get("unitInfo"):
                table[h] = int(entry["unitInfo"].get("domain") == "DOMAIN_SEA")
        _SEA_MAP = table
    return _SEA_MAP


_AIR_MAP: Optional[dict] = None


def _air_map(db) -> dict:
    """hash -> 1/0 for aircraft (``units.domain == DOMAIN_AIR``).

    v0.29: the web map folds every aircraft on a tile into one stack drawn with
    drop shadows (the in-game "flight" look), so the payload has to separate air
    units from the land/naval ones that share the military category.
    """
    global _AIR_MAP
    if _AIR_MAP is None:
        table: dict = {}
        if db.available:
            for r in db.conn.execute("select hash, domain from units"):
                table[int(r["hash"]) & 0xFFFFFFFF] = (
                    1 if (r["domain"] or "") == "DOMAIN_AIR" else 0)
        for h, entry in get_identities().entries.items():
            if entry.get("unitInfo"):
                table[h] = int(entry["unitInfo"].get("domain") == "DOMAIN_AIR")
        _AIR_MAP = table
    return _AIR_MAP


_WATER_MAP: Optional[dict] = None


def _water_map(db) -> dict:
    """terrain hash -> 1/0 (``terrains.water``) for the bridge test."""
    global _WATER_MAP
    if _WATER_MAP is None:
        table: dict = {}
        if db.available:
            for r in db.conn.execute("select hash, water from terrains"):
                table[int(r["hash"]) & 0xFFFFFFFF] = 1 if int(r["water"] or 0) else 0
        # ``TERRAIN_LAKE`` is missing from stripped ``DebugGameplay`` snapshots
        # (see ``identities.EXTRA_TERRAINS``); a lake is water by definition.
        table.setdefault(crc32_type("TERRAIN_LAKE"), 1)
        _WATER_MAP = table
    return _WATER_MAP


# --- city-state helpers (shared semantics with the web front end) ----------

# City-state flavour order for the HUD page (identities.flavour() values).
CITY_STATE_FLAVOUR_ORDER = ["科技", "文化", "商业", "军事", "工业", "宗教"]


def suzerain_of(emissaries) -> Optional[int]:
    """Sender iPlayer holding the suzerain slot of a city state.

    ``emissaries`` maps ``{sender_iPlayer: envoy_count}``.  The suzerain is the
    sender with a *unique* highest count of at least 3 envoys; a tie at the top
    (or a top count below 3) means nobody is suzerain -> ``None``.
    """
    counts = [(int(k), int(v or 0)) for k, v in (emissaries or {}).items()]
    counts = [(k, v) for k, v in counts if v > 0]
    if not counts:
        return None
    top = max(v for _, v in counts)
    if top < 3:
        return None
    winners = [k for k, v in counts if v == top]
    return winners[0] if len(winners) == 1 else None


def city_state_sort_key(city_count: int, flavour: str, max_emissary: int,
                        name: str) -> tuple:
    """Sort key for the city-state HUD page.

    Dead city states (``cityCount == 0``) sink to the bottom; the living ones
    follow the flavour order (科技 → 文化 → 商业 → 军事 → 工业 → 宗教), then
    the highest envoy count (descending) and finally the Chinese name
    (ascending).  Unknown flavours sort after the known ones.
    """
    try:
        order = CITY_STATE_FLAVOUR_ORDER.index(flavour or "")
    except ValueError:
        order = len(CITY_STATE_FLAVOUR_ORDER)
    return (1 if not city_count else 0, order, -int(max_emissary or 0),
            name or "")


def tourism_by_player(p: "Player") -> Dict[str, int]:
    """v0.40: ``{对手槽位: 对它的累积旅游业绩}``（自己那一格与 0 不写进去）。

    存档只给累积量、不给每回合值，而且每一份都被各自的旅游修正（开边 / 商路 /
    同宗教…）乘过 —— 所以前端拿相邻两个存档里**同名键**的差算出每个对手的增量，
    再取**出现次数最多**的那个增量（大多数对手共用的那份 = 没被修正改过的基准）
    ÷ 1024 ÷ 回合间隔，就是游戏文化胜利面板里的「旅游业绩 / 回合」
    （推导见 README v0.40）。
    """
    me = int(getattr(p, "iPlayer", -1))
    out: Dict[str, int] = {}
    for i, v in enumerate(getattr(p, "totalTourismByPlayer", None) or []):
        if v and i != me:
            out[str(i)] = int(v)
    return out


def parse_save(data: bytes, *, want_visibility: bool = True) -> GameState:
    state = GameState()

    # --- container / header ------------------------------------------------
    packets = container.parse_all(data)
    state.bcy = parse_bcy(packets)
    info = header.game_info(packets)
    state.map_name = info["map_name"]
    state.map_name_en = info["map_name_en"]
    state.map_key = info["map_key"]
    state.map_size = info["map_size"]
    state.game_speed = info["game_speed"]
    state.multiplayer = info["multiplayer"]
    state.seed = header.game_seed(packets)
    # v0.26.1: the enabled MOD / DLC list (plain JSON in the header) - it decides
    # which city-wall numbers apply to this save.
    try:
        state.mods = mods_mod.parse_mods(data)
        state.modPackages = mods_mod.parse_mod_packages(data)
        state.balanceMod = mods_mod.balance_mod(state.mods)
    except Exception:            # pragma: no cover - never worth failing a parse
        state.mods = []
        state.balanceMod = ""
    # v0.39: 黑名单 MOD / 不支持的玩法（结社、垄断）——命中就**直接退出**，不碰
    # 后面的解压与游玩数据；前端拿到 ``unsupported`` 后只画叉。
    try:
        state.gameModes = modes_mod.parse_game_modes(packets)
    except Exception:            # pragma: no cover - never worth failing a parse
        state.gameModes = []
    try:
        state.unsupported = unsupported_mod.verdict(state.mods, state.gameModes)
    except Exception:            # pragma: no cover - defensive
        state.unsupported = None
    try:
        color_mods = [*state.mods, *(str(m.get(field, "")) for m in state.modPackages
                                   for field in ("key", "name"))]
        state.playersInfo = header.players_info(packets, mods=color_mods)
    except Exception as exc:  # pragma: no cover - defensive
        _note(state, "players_info", None, repr(exc))
        state.playersInfo = [PlayerInfo(iPlayer=i) for i in range(64)]
    if state.unsupported:
        # 「没有地图」要明确：宽高归零，免得前端 / API 使用者以为有一条 44 宽的空局
        state.width = state.height = 0
        return state

    # --- decompress game state --------------------------------------------
    blob = container.load_game_state(data)

    # --- turn --------------------------------------------------------------
    try:
        state.turn = read_int(Cursor(blob, TURN_OFFSET))
    except Exception as exc:
        _note(state, "turn", TURN_OFFSET, repr(exc))

    # --- map ---------------------------------------------------------------
    try:
        width, tiles, height = mapdata.parse_map(blob)
        state.width, state.tiles, state.height = width, tiles, height
    except Exception as exc:
        _note(state, "map", getattr(exc, "offset", None), repr(exc))
        return state

    # --- players -----------------------------------------------------------
    players: List[Player] = []
    religions: List[Religion] = []
    try:
        players_mod.parse_players(blob, players, religions,
                                  warnings=state.tailWarnings)
    except Exception as exc:
        # v0.25: a players failure means the (post-per-player) tail could not be
        # walked — the era / golden-age data is missing, but cities, units and
        # yields are all parsed already and the UI keeps working.
        _note(state, "players", getattr(exc, "offset", None),
              f"{type(exc).__name__}: {exc}")
    state.players = players
    state.religions = religions

    # --- nuclear state (v0.31) --------------------------------------------
    # Fallout turns per plot and the WMD stockpile live in the tail of the
    # stream, outside the offset walkers; a failure only loses those two views.
    try:
        state.fallout = nukes_mod.parse_fallout(blob, len(state.tiles))
        stock = nukes_mod.parse_wmd(blob)
        for p in state.players:
            p.wmd = stock.get(p.iPlayer, {})
    except Exception as exc:  # pragma: no cover - defensive
        _note(state, "nukes", None, repr(exc))
        state.fallout = []

    # --- finalize player data & compute yields -----------------------------
    try:
        _finalize_players(state)
    except Exception as exc:  # pragma: no cover
        _note(state, "links", None, repr(exc))

    # --- visibility --------------------------------------------------------
    if want_visibility and state.players:
        try:
            visibility_mod.parse_visibility(blob, state.players)
        except Exception as exc:
            _note(state, "visibility", getattr(exc, "offset", None), repr(exc))

    return state


def header_verdict(data: bytes):
    """只看存档头部的「不支持」判定（不解压游玩数据）。

    ``ReplayManager`` 用它决定要不要为这条 seed 解析回合：``None`` = 可以复盘。
    头部本身读不出来时也返回 ``None``（让正常的解析流程去报错 / 降级）。
    """
    packets = container.parse_all(data)
    return unsupported_mod.verdict(mods_mod.parse_mods(data),
                                   modes_mod.parse_game_modes(packets))


def _finalize_players(state: GameState) -> None:
    for p in state.players:
        if p.iPlayer < 0:
            continue
        for c in p.cities:
            c.iPlayer = p.iPlayer
            for key, value in c.yields.items():
                p.yields[_mask(key)] = p.yields.get(_mask(key), 0) + value
            p.totalPop += c.population
            raw = c.name or ""
            c.nameKey = raw
            c.name = _city_display_name(raw) or raw
        p.militaryStrength = 0
        p.unitCount = 0
        for u in p.units:
            u.iPlayer = p.iPlayer
            ui = p.unitsInfo.get(_mask(u.type))
            if ui is not None and getattr(ui, "health", 0) > 0:
                # Strength uses the saved type value, then the formation bonus
                # and one point per full 10% of maximum health lost. Civilian
                # and support types with no combat strength contribute nothing.
                if ui.attack > 0:
                    formation_bonus = {1: 10, 2: 17}.get(u.army, 0)
                    damage = min(ui.health, max(0, u.damage))
                    damage_penalty = (damage * 10) // ui.health
                    p.militaryStrength += max(0, ui.attack + formation_bonus - damage_penalty)
                p.unitCount += 1


def summarize_player(p: Player) -> dict:
    yields = {str(k): round(v, 1) for k, v in p.yields.items()}
    total = {str(k): round(v, 1) for k, v in p.totalYields.items()}
    current_tech = [ _mask(x) for x in p.techDogmeInfo[0].current ]
    current_civic = [ _mask(x) for x in p.techDogmeInfo[1].current ]
    # ``found`` includes every tech/civic key; count only the true entries.
    found_tech = p.techDogmeInfo[0].found
    found_civic = p.techDogmeInfo[1].found
    # v0.22: city-center district per city (carries damage / wall values)
    CITY_CENTER = 0x8A32007D  # crc32_type("DISTRICT_CITY_CENTER")
    center_by_city = {}
    for d in p.districts:
        if _mask(getattr(d, "type", NONE_U32)) == CITY_CENTER:
            center_by_city[int(getattr(d, "cityId", 0xFFFF))] = d
    # Show only this player's governors assigned to this player's own cities.
    # Foreign capitals and city-states reuse the same local city IDs.
    gov_by_city = {}
    for g in p.governors:
        city = getattr(g, "city", 0xFFFF)
        if governor_assigned_to(g, p.iPlayer, city):
            gov_by_city[city] = {
                "type": _mask(getattr(g, "type", NONE_U32)),
                "promotions": len(getattr(g, "promotions", []) or []),
                # v0.34: 具体点过哪些晋升（类型哈希列表）。名字随平衡 MOD
                # 而变，前端用 data/mods/governor_promotions.json 里对应
                # 规则集的表翻译（见 src/civ6replay/governors.py）。
                "promotionHashes": [_mask(k) for k in
                                    (getattr(g, "promotions", []) or [])],
            }
    return {
        "iPlayer": p.iPlayer,
        "gold": p.gold,
        "faith": p.faith,
        "maintenance": round(p.maintenance, 1),
        "diploFavor": p.diploFavor,
        "diploPoint": p.diploPoint,
        "government": _mask(p.government),
        "policies": [[_mask(x) for x in slot] for slot in p.policies],
        # Empty policy entries are serialized as NONE_U32, so each group's
        # length is the actual capacity (including extra slots from bonuses).
        "policySlots": [len(slot) for slot in p.policies],
        "resources": {str(_mask(k)): int(v) for k, v in p.resources.items() if v > 0},
        "cityCount": len(p.cities),
        "totalPop": p.totalPop,
        "militaryStrength": p.militaryStrength,
        "unitCount": p.unitCount,
        "emissaries": {str(i): c for i, c in enumerate(p.emissaries) if c},
        # v0.32: 剩余使者（未派出的使者）—— 只有文明（major）有意义，
        # 前端只在文明卡「外交」行里画它。
        "envoyTokens": int(getattr(p, "envoyTokens", 0)),
        "cities": [
            {"id": c.id, "x": c.x, "y": c.y, "name": c.name,
             "nameKey": getattr(c, "nameKey", "") or c.name,
             "population": c.population, "religion": _mask(c.religion),
             "yields": {str(k): round(v, 1) for k, v in c.yields.items()},
             "currentProds": [_mask(x) for x in c.currentProds],
             "currentProdType": int(getattr(c, "currentProdType", 0) or 0),
             # built buildings: {building hash: tile index}; 0xFFFF = not built
             "built": {str(_mask(k)): (int(v) & 0xFFFF)
                       for k, v in getattr(c, "built", {}).items()
                       if (int(v) & 0xFFFF) != 0xFFFF},
             # v0.29: buildings the city has pillaged (the game tracks this per
             # building, separately from the host district's own ``pillage``).
             "pillagedBuildings": sorted(
                 _mask(k) for k, v in
                 getattr(c, "pillagedBuildings", {}).items() if v),
             "governor": (gov_by_city.get(c.id) or {}).get("type"),
             "governorPromotions": (gov_by_city.get(c.id) or {}).get("promotions"),
             "governorPromotionHashes": (gov_by_city.get(c.id) or {}).get("promotionHashes"),
             "damage": int(getattr(center_by_city.get(c.id), "damage", 0) or 0),
             "wall": int(getattr(center_by_city.get(c.id), "wall", 0) or 0),
             "wallDamage": int(getattr(center_by_city.get(c.id), "wallDamage", 0) or 0)}
            for c in p.cities
        ],
        "districts": [
            {"id": int(getattr(d, "id", 0)),
             "x": int(getattr(d, "x", 0)), "y": int(getattr(d, "y", 0)),
             "type": _mask(getattr(d, "type", NONE_U32)),
             "built": int(getattr(d, "built", 0) or 0),
             "pillage": int(getattr(d, "pillage", 0) or 0),
             "damage": int(getattr(d, "damage", 0) or 0),
             "wallDamage": int(getattr(d, "wallDamage", 0) or 0),
             "wall": int(getattr(d, "wall", 0) or 0),
             "cityId": int(getattr(d, "cityId", 0xFFFF))}
            for d in p.districts
        ],
        "yields": yields,
        "totalYields": total,
        "currentTech": current_tech,
        "currentCivic": current_civic,
        "techResearched": sorted(_mask(k) for k, v in found_tech.items() if v),
        "techTotal": len(found_tech),
        "civicResearched": sorted(_mask(k) for k, v in found_civic.items() if v),
        "civicTotal": len(found_civic),
        "techBoosted": sorted(_mask(k) for k, v in p.techDogmeInfo[0].boost.items() if v),
        "civicBoosted": sorted(_mask(k) for k, v in p.techDogmeInfo[1].boost.items() if v),
        "ageState": p.ageState,
        "eraPoint": p.eraPoint,
        "eraNormalThreshold": p.eraNormalThreshold,
        "eraGoldenThreshold": p.eraGoldenThreshold,
        # v0.25: golden-age dedications (empty when the tail is unreachable) and
        # the pantheon (0xFFFFFFFF = none)
        "commemorations": [_mask(x) for x in p.commemorations],
        "pantheon": _mask(p.pantheon),
        # v0.31: WMD stockpile (hash -> count); the front end resolves the type
        # names / icons and the 军事 panel shows the nuclear / thermonuclear
        # counts.  Empty for players that own none.
        "wmd": {str(_mask(k)): int(v)
                for k, v in (getattr(p, "wmd", {}) or {}).items() if v},
        # v0.40: 旅游业绩 / 文化胜利进度（右栏文明卡「文化」行）。
        # ``tourismByPlayer`` = {对手槽位: 累积旅游业绩}（见 ``tourism_by_player()``），
        # 前端拿相邻两个存档的逐对手增量算出「旅游业绩 / 回合」；
        # ``externalTourist`` = 国际游客（游戏文化胜利面板的分子），
        # ``internalTourist`` = 国内游客（分母取对手里最高的那个 + 1）。
        "tourismByPlayer": tourism_by_player(p),
        "externalTourist": int(getattr(p, "externalTourist", 0) or 0),
        "internalTourist": int(getattr(p, "internalTourist", 0) or 0),
    }

# --- column-JSON serialization ---------------------------------------------

_TILE_COLUMNS = (
    "terrain", "feature", "resource", "improvement", "road", "appeal",
    "riverBits", "cliffBits", "flags", "owner", "city", "district", "wonder",
    "continent", "water", "fallout",
)


def turn_payload(state: GameState, *, wrap_x: Optional[bool] = None) -> dict:
    """Serialize a turn into column-JSON (fixed-length arrays per tile)."""
    n = len(state.tiles)
    cols = {k: [0] * n for k in _TILE_COLUMNS}
    waters = _water_map(get_gamedb())
    # v0.31: contamination turns (0 = clean); ``parse_fallout`` returns an empty
    # list when the table could not be located.
    fallout = state.fallout if len(state.fallout) == n else [0] * n
    for i, t in enumerate(state.tiles):
        cols["terrain"][i] = _mask(t.terrain)
        cols["feature"][i] = _mask(t.feature)
        cols["resource"][i] = _mask(t.resource)
        cols["improvement"][i] = _mask(t.improvment)
        # v0.25: publish the route index itself (0 = ancient road … 4 = railroad,
        # 255 = no road); v0.24 sent ``roadLvl`` which turned out to be a constant
        # per route (0/1/4/5/0) rather than a level.
        cols["road"][i] = t.road
        cols["appeal"][i] = t.appeal
        cols["riverBits"][i] = (t.riverCount & 0xFF) | ((t.river & 0xFF) << 8)
        cols["cliffBits"][i] = t.cliffbitmap & 0xFF
        cols["flags"][i] = ((t.bOverlay & 1) | ((t.pillage & 1) << 1)
                            | ((1 if t.iPlayer != 0xFFFF else 0) << 2)
                            | ((1 if t.resource != NONE_U32 else 0) << 3))
        cols["owner"][i] = -1 if t.iPlayer == 0xFFFF else t.iPlayer
        cols["city"][i] = -1 if t.iCity == 0xFFFF else t.iCity
        cols["district"][i] = -1 if t.iDistrict == 0xFFFF else t.iDistrict
        cols["wonder"][i] = _mask(t.wonder)
        cols["continent"][i] = _mask(t.continent)
        cols["water"][i] = waters.get(_mask(t.terrain), 0)
        cols["fallout"][i] = fallout[i] & 0xFF

    cats = _category_map(get_gamedb())
    seas = _sea_map(get_gamedb())
    airs = _air_map(get_gamedb())
    units = []
    for p in state.players:
        if p.iPlayer < 0:
            continue
        for u in p.units:
            if not u.exist:
                continue
            # ``damage`` is damage *taken* (0 = full health, upstream
            # CivVIState.cpp uses ``health - damage``), so publish the derived
            # HP next to it for the health bar / panels.
            ui = p.unitsInfo.get(_mask(u.type))
            hp_max = int(getattr(ui, "health", 0) or 0) or 100
            damage = int(u.damage or 0)
            units.append({
                "x": u.x, "y": u.y, "type": _mask(u.type), "damage": u.damage,
                "hp": max(0, hp_max - damage), "hpMax": hp_max,
                "army": u.army, "level": u.level, "fortified": u.fortified,
                "iPlayer": p.iPlayer, "xp": u.xp,
                "cat": cats.get(_mask(u.type), "mil"),
                "sea": seas.get(_mask(u.type), 0),
                "air": airs.get(_mask(u.type), 0),
            })

    players = [summarize_player(p) for p in state.players if p.iPlayer >= 0]
    adjacency = calculate_adjacencies(state, wrap_x=wrap_x, include_sources=True)
    for p, summary in zip((p for p in state.players if p.iPlayer >= 0), players):
        for district, record in zip(p.districts, summary["districts"]):
            report = adjacency.get(id(district))
            record["adjacency"] = report["yields"] if report is not None else None
            record["adjacencySources"] = report["sources"] if report is not None else None

    # v0.28.1: religions are *per-turn* state — a religion only exists from the
    # turn it was founded and gains its beliefs over time (2 at founding, up to 4
    # later), so the payload carries the list read from **this** save.
    # ``static_info.religions`` comes from the newest save of the seed and must
    # not be used for the civ card (it made every religion show up on turn 1).
    religions = [
        {"iPlayer": r.iPlayer, "symbol": _mask(r.iSymbol), "name": r.name or "",
         "beliefs": [_mask(b) for b in r.beliefs]}
        for r in state.religions
    ]

    visibility = {}
    for p in state.players:
        if p.iPlayer >= 0 and p.visible:
            visibility[str(p.iPlayer)] = list(p.visible)

    return {
        "turn": state.turn,
        "seed": state.seed,
        "width": state.width,
        "height": state.height,
        "tiles": cols,
        "tileYields": calculate_tile_yields(state, wrap_x=wrap_x),
        "tileYieldRules": rules_token(),
        "bcy": state.bcy,
        "units": units,
        "players": players,
        "religions": religions,
        "visibility": visibility,
    }


def encode_payload(payload: dict) -> bytes:
    return gzip.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def decode_payload(blob: bytes) -> dict:
    return json.loads(gzip.decompress(blob).decode("utf-8"))
