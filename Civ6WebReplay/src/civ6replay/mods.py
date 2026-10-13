"""Enabled MOD / DLC list of a save, the MOD blacklist, and the balance-MOD
wall overrides.

The save header carries one small JSON dictionary per enabled package
(``{"LOC_EXPANSION1_MOD_TITLE": []}``, ``{"CCB 1.6": []}``,
``{"LOC_BSM_TITLE": [{"locale": "en_US", "text": "Better Spectator Mod ..."}]}``).
Those dictionaries are plain UTF-8 JSON embedded in the container, so they can be
recovered with :func:`json.JSONDecoder.raw_decode` instead of walking a binary
layout that changes between game versions.

Why we care: a *balance* MOD (BBG / CCB / 和而不同) rewrites the city-wall
numbers, and a single game-db snapshot can only hold one ruleset.  The save's own
mod list is the authority for the game being reviewed, so the wall caps are
switched here.

v0.39: the same list also feeds the *blacklist* (:func:`blacklisted_mods`) - a
MOD that rewrites the data this tool replays (结社体系、CCB 受命于天 / 纪元回响)
would make every number wrong, so such a save is rejected outright instead of
being replayed.  :func:`blacklist_hit` holds the rules.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from .hash import crc32_type

# 平衡 MOD 的城墙数值（远古城墙 / 中世纪城墙 / 文艺复兴城墙 三档同为 75，
# 研了钢铁之后城市防御为 300）。快照只能存一套数值，MOD 局靠存档的 mod 列表切过来。
BALANCE_WALL_HP = 75
BALANCE_URBAN_DEFENSE = 300

# 三档城墙的 TYPE（哈希是 TYPE 串的 crc32，与快照无关），顺序即档次
WALL_TYPES = ("BUILDING_WALLS", "BUILDING_CASTLE", "BUILDING_STAR_FORT")

# ``name`` 是显示用的短名；正则同时匹配 MOD 名与本地化 tag
BALANCE_MODS = (
    ("BBG", re.compile(r"\bbbg\b|better\s+balanced", re.I)),
    ("CCB", re.compile(r"\bccb\b|和而不同", re.I)),
)

# --- MOD 黑名单（v0.39） ----------------------------------------------------
# 命中任一规则即整局判为「不支持」（前端在画布上画叉）。规则只按 MOD 标题匹配；
# ``parse_mods`` 给的是显示名（MOD 自己写的名字，或它本地化文本里的说明）。
#
# 1. 标题带「结社」：这类 MOD 围绕秘密结社（甚至自带一套结社体系）改数据；
# 2. 标题同时带「CCB」与「受命于天」/「纪元回响」：CCB 的两个改写全局规则的版本；
# 3. 标题带「Team PVP」（不分大小写、忽略空格，所以 "TeamPVP" / "team pvp" 都命中），
#    但工具链自己也用这两个 MOD（联机工具箱 / 顶部面板拓展），它们只是 UI 辅助，
#    按关键词放行。
TEAM_PVP_EXEMPT = ("联机工具箱", "顶部面板拓展")
_CCB_RE = re.compile(r"ccb", re.I)
_SPACES = re.compile(r"\s+")

# 只在存档开头找 mod 列表：官方 DLC + MOD 条目都挤在头部几 KB 里
MOD_SCAN_BYTES = 1048576
_TEXT_KEYS = ("text", "value", "name")
# a TYPE-like token such as ``CCB_TITLE``: a MOD name is human readable, so it
# never matches this
_TAGLIKE = re.compile(r"^[A-Z0-9_]+$")
# v0.39：MOD 的 ``<Name>`` 也可能是一个本地化 tag（``LOC_MPT_NAME``，真名在它的
# 文本里），所以额外认这些 ``LOC_*_NAME`` 键；但头部里「设置项的名字」块（难度 /
# 时代 / 地图 / 速度 / 文明 / 领袖 / 规则集 / 玩法 / 场景）长得一模一样，它们不是
# MOD，按前缀排除。实测本机 91 个 Multi 存档 + Hotseat / Single 各若干：这条宽松
# 规则只多认出 ``LOC_MPT_NAME``（Multiplayer Toolkits (UI)）一条真实 MOD 名。
SETUP_NAME_PREFIXES = (
    "LOC_DIFFICULTY_", "LOC_ERA_", "LOC_MAPSIZE_", "LOC_GAMESPEED_", "LOC_MAP",
    "LOC_CIVILIZATION_", "LOC_LEADER_", "LOC_EXPANSION", "LOC_RULESET",
    "LOC_GAMEMODE", "LOC_GAME_MODE", "LOC_WORLD_BUILDER", "LOC_SCENARIO_",
)


def _is_mod_title_key(key: str) -> bool:
    """Is ``key`` the title key of one enabled package?

    Official / DLC entries use a localization tag (``LOC_..._MOD_TITLE``,
    ``LOC_BSM_TITLE``); a MOD without localization uses its own readable name
    (``CCB 1.6``, ``和而不同 2.1``) as the key.  Everything else in the header
    (difficulty / map / era names, ...) is a plain localization blob and is
    skipped - otherwise the list fills up with "Prince", "Standard", ...

    v0.39: ``LOC_*_NAME`` 里也可能是 MOD 名（``LOC_MPT_NAME``），所以这一类也收；
    只有设置项的 ``LOC_*_NAME``（``LOC_DIFFICULTY_PRINCE_NAME`` …）按
    :data:`SETUP_NAME_PREFIXES` 排除。
    """
    key = key.strip()
    if not key:
        return False
    if key.startswith("LOC_"):
        if key.endswith("MOD_TITLE") or key.endswith("_TITLE"):
            return True
        if key.endswith("_NAME"):
            return not key.startswith(SETUP_NAME_PREFIXES)
        return False
    return not _TAGLIKE.match(key)


def _locale_texts(node, out: Dict[str, str]) -> None:
    """Fill ``{locale: text}`` from a (possibly nested) mod-title value."""
    if isinstance(node, dict):
        locale, text = None, None
        for key, value in node.items():
            if isinstance(value, str) and key in _TEXT_KEYS:
                text = value
            elif isinstance(value, str) and key == "locale":
                locale = value
            else:
                _locale_texts(value, out)
        if text and locale:
            out.setdefault(locale, text)
    elif isinstance(node, list):
        for item in node:
            _locale_texts(item, out)


def _pretty_tag(tag: str) -> str:
    """``LOC_AZTEC_MONTEZUMA_MOD_TITLE`` -> ``Aztec Montezuma``."""
    name = tag
    if name.startswith("LOC_"):
        name = name[4:]
    for suffix in ("_MOD_TITLE", "_TITLE"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("_", " ").title()


def _display_name(key: str, value) -> str:
    """Best human-readable name of one package entry."""
    table: Dict[str, str] = {}
    _locale_texts(value, table)
    for locale in ("zh_Hans_CN", "zh_Hant_HK", "en_US"):
        if table.get(locale):
            return table[locale].strip()
    if not key.startswith("LOC_"):
        return key          # a MOD names itself in the key
    return _pretty_tag(key)


def parse_mods(data: bytes) -> List[str]:
    """Title strings of every enabled MOD / DLC in ``data`` (order preserved).

    Returns ``[]`` when the header cannot be read - the UI then treats the game
    as un-modded, which is the pre-v0.26.1 behaviour.
    """
    text = data[:MOD_SCAN_BYTES].decode("utf-8", "replace")
    decoder = json.JSONDecoder()
    out: List[str] = []
    seen = set()
    for match in re.finditer(r'\{"', text):
        try:
            obj, _end = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if not isinstance(obj, dict) or not obj:
            continue
        if not all(isinstance(v, list) for v in obj.values()):
            continue          # the mod-title shape is {key: [...]}
        for key, value in obj.items():
            if not _is_mod_title_key(key):
                continue
            title = _display_name(key, value)
            if not title or title in seen:
                continue
            seen.add(title)
            out.append(title)
    return out


def parse_mod_packages(data: bytes) -> List[dict]:
    """Keep the stable title key as well as its localized display spelling."""
    text = data[:MOD_SCAN_BYTES].decode("utf-8", "replace")
    decoder = json.JSONDecoder()
    packages = {}
    for match in re.finditer(r'\{"', text):
        try:
            obj, _end = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if not isinstance(obj, dict) or not obj or not all(isinstance(v, list) for v in obj.values()):
            continue
        for key, value in obj.items():
            if _is_mod_title_key(key):
                packages.setdefault(key, {"key": key, "name": _display_name(key, value)})
    return list(packages.values())


def balance_mod(mods) -> str:
    """``"BBG"`` / ``"CCB"`` when such a MOD is enabled, else ``""``."""
    joined = "\n".join(str(m) for m in (mods or []))
    if not joined:
        return ""
    for name, pattern in BALANCE_MODS:
        if pattern.search(joined):
            return name
    return ""


def blacklist_hit(title: str) -> str:
    """命中的黑名单规则名（``""`` = 这个 MOD 没问题）。

    Rules, in order: 标题含「结社」；含「CCB」且含「受命于天」/「纪元回响」；
    含「Team PVP」（不分大小写、忽略空格）但不是联机工具箱 / 顶部面板拓展。
    """
    text = (title or "").strip()
    if not text:
        return ""
    if "结社" in text:
        return "结社"
    if _CCB_RE.search(text):
        if "受命于天" in text:
            return "CCB 受命于天"
        if "纪元回响" in text:
            return "CCB 纪元回响"
    squashed = _SPACES.sub("", text).lower()
    if "teampvp" in squashed and not any(k in text for k in TEAM_PVP_EXEMPT):
        return "Team PVP"
    return ""


def blacklisted_mods(mods) -> List[str]:
    """黑名单 MOD 的标题（按存档里的顺序，去重）。

    ``[]`` 表示这条存档的 MOD 列表是干净的；返回值同时给前端当「是哪几个 MOD
    导致的」用，所以保留原始标题而不是规则名。
    """
    out: List[str] = []
    seen = set()
    for entry in (mods or []):
        title = str(entry).strip()
        if not title or title in seen or not blacklist_hit(title):
            continue
        seen.add(title)
        out.append(title)
    return out


def wall_defense_override(wall_defense: Dict[str, object],
                          mods) -> Dict[str, object]:
    """Snapshot wall caps with the balance-MOD numbers applied when needed.

    ``wall_defense`` is the dict from :meth:`GameDB.wall_defense`; the result
    adds ``balanceMod`` and keeps the snapshot's ``steelTech`` (``TECH_STEEL``
    exists in every ruleset).  With a balance MOD the three tiers all cap at
    :data:`BALANCE_WALL_HP` and 钢铁 raises the city to
    :data:`BALANCE_URBAN_DEFENSE`.
    """
    out: Dict[str, object] = dict(wall_defense or {})
    out.setdefault("buildings", {})
    out.setdefault("urbanDefense", None)
    out.setdefault("steelTech", None)
    report = balance_mod(mods)
    out["balanceMod"] = report
    if not report:
        return out
    buildings = dict(out["buildings"] or {})
    for order, type_str in enumerate(WALL_TYPES):
        hash_value = crc32_type(type_str)
        entry = buildings.get(str(hash_value))
        if not entry:                      # no snapshot row: synthesise one
            entry = {"hp": BALANCE_WALL_HP, "order": order}
        else:
            entry = dict(entry)
            entry["hp"] = BALANCE_WALL_HP
        buildings[str(hash_value)] = entry
    out["buildings"] = buildings
    out["urbanDefense"] = BALANCE_URBAN_DEFENSE
    return out


def wall_caps(wall_defense: Dict[str, object]) -> Optional[Tuple[int, int]]:
    """``(wall_hp, urban_defense)`` of a resolved ``wallDefense`` dict."""
    buildings = (wall_defense or {}).get("buildings") or {}
    if not buildings:
        return None
    hp = max(int(e.get("hp") or 0) for e in buildings.values())
    urban = (wall_defense or {}).get("urbanDefense")
    return hp, int(urban) if urban else hp
