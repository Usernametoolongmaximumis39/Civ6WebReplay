"""Build ``data/vanilla/loc.json`` from the Civ6 install's localization.

The runtime snapshot (``gamedb.sqlite``) is distilled from the player's
``DebugGameplay.sqlite``/``DebugLocalization.sqlite`` cache, which is missing a
number of localization rows on stripped installs (``LOC_CITY_NAME_AYUTTHAYA``
never makes it into the cache, for example).  This tool instead reads the raw
``Text`` XML shipped with the game so the app can render city / civilization
names exactly as the game shows them (Simplified Chinese first, English second).

Priority (v0.25): **base game text wins over DLC text, which wins over MOD
text**.  DLC *scenario* text rewrites vanilla strings (``CivRoyaleScenario``
turns ``LOC_TERRAIN_PLAINS_NAME`` into a wasteland name, ``LOC_TERRAIN_OCEAN_NAME``
into "Poisoned Ocean" and ``LOC_GOVERNMENT_MONARCHY_NAME`` into "Catholic
Monarchy"), so harvesting the DLC folders last — as v0.24 did — poisoned the
whole snapshot.  MOD text is used only for ``LOC_MOMENT_CATEGORY_*`` (the
golden-age dedication names, which no official text carries in zh) and for tags
the base+DLC text lacks; the kept MOD rows are recorded in the ``mod_names``
section for review.

It walks ``<game>/Base/Assets/Text/*.xml``, ``<game>/DLC/**/Text/**/*.xml`` and
(by default) every MOD folder under
``D:\\SteamLibrary\\steamapps\\workshop\\content\\289070``, extracts
``<Replace Tag=… Language=…><Text>…</Text></Replace>`` rows (plus ``<Row>``
rows under locale directories / ``chinese.xml``-style files, where the language
is implied by the path or the file name) and keeps only ``zh_Hans_CN`` /
``en_US``.

When the game directory is missing the tool degrades to the
``DebugLocalization.sqlite`` cache and records ``"source": "debug_localization"``
in the output document.

Usage::

    python -B data/tools/build_loc.py [--game-dir DIR] [--cache-dir DIR] [--out FILE]
                              [--mod-dirs DIR[;DIR…] | --mod-dirs none]
"""
from __future__ import annotations

from tool_paths import ROOT, DEV, WORKSPACE

import argparse
import datetime as _dt
import html
import json
import os
import re
import sqlite3
import sys
from pathlib import Path


DEFAULT_OUT = ROOT / "data" / "vanilla" / "loc.json"

KEEP_LANGS = ("zh_Hans_CN", "en_US")

# ``Language`` attribute variants seen in the wild -> the two languages we keep.
LANG_ALIASES = {
    "zh_Hans_CN": "zh_Hans_CN",
    "zh_Hans": "zh_Hans_CN",
    "zh_hans_cn": "zh_Hans_CN",
    "zh": "zh_Hans_CN",
    "en_US": "en_US",
    "en_us": "en_US",
    "en": "en_US",
}

# MOD text folders are per-language files (``lang/chinese.xml``,
# ``lang/english.xml`` …) whose rows often carry no ``Language`` attribute.
FILENAME_LANGS = {
    "chinese": "zh_Hans_CN",
    "chinesesimplified": "zh_Hans_CN",
    "zh_hans_cn": "zh_Hans_CN",
    "zh_hans": "zh_Hans_CN",
    "english": "en_US",
    "en_us": "en_US",
}

# Locale directory names that imply a language when a row carries no
# ``Language`` attribute (the ``en_US/`` text folders are the important ones).
LOCALE_DIRS = {"en_US": "en_US", "zh_Hans_CN": "zh_Hans_CN"}

# element (opening + attributes) ... <Text>payload</Text> ... close
_ELEMENT_RE = re.compile(r"<(Replace|Row|Update)\b([^>]*)>(.*?)</\1>", re.DOTALL)
_ATTR_RE = re.compile(r'([A-Za-z_][\w.-]*)\s*=\s*"([^"]*)"')
_TEXT_RE = re.compile(r"<Text\b[^>]*>(.*?)</Text>", re.DOTALL)

STEAM_ROOTS = [
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\Sid Meier's Civilization VI"),
    Path(r"C:\Program Files\Steam\steamapps\common\Sid Meier's Civilization VI"),
    Path(r"D:\SteamLibrary\steamapps\common\Sid Meier's Civilization VI"),
    Path(r"C:\SteamLibrary\steamapps\common\Sid Meier's Civilization VI"),
    Path(r"E:\SteamLibrary\steamapps\common\Sid Meier's Civilization VI"),
]

# Workshop content folders that hold one Civilization VI MOD per subdirectory.
WORKSHOP_ROOTS = [
    Path(r"D:\SteamLibrary\steamapps\workshop\content\289070"),
    Path(r"C:\SteamLibrary\steamapps\workshop\content\289070"),
    Path(r"E:\SteamLibrary\steamapps\workshop\content\289070"),
    Path(r"C:\Program Files (x86)\Steam\steamapps\workshop\content\289070"),
]


def default_game_dir() -> Path:
    env = os.environ.get("CIV6_GAME_DIR")
    if env:
        return Path(env)
    for cand in STEAM_ROOTS:
        if (cand / "Base" / "Assets" / "Text").is_dir():
            return cand
    return STEAM_ROOTS[0]


def default_cache_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "")
    return Path(local) / "Firaxis Games" / "Sid Meier's Civilization VI" / "Cache"


def _expand_mod_dirs(value: str) -> list[Path]:
    """``;``/``,``-separated MOD folders (workshop ``content/<id>`` roots expand).

    A numeric folder is a workshop root (``…/content/289070``) unless it is a
    MOD itself (it carries ``*.modinfo`` or a ``lang``/``text`` folder), so both
    ``content/289070`` and ``content/289070/<mod id>`` may be passed.
    """
    out: list[Path] = []
    for token in re.split(r"[;,]", value or ""):
        token = token.strip().strip('"')
        if not token:
            continue
        p = Path(token)
        if not p.is_dir():
            continue
        if re.fullmatch(r"\d+", p.name) and not _looks_like_mod(p):
            out.extend(sorted(c for c in p.iterdir() if c.is_dir()))
        else:
            out.append(p)
    return out


def _looks_like_mod(path: Path) -> bool:
    """True when ``path`` itself is a MOD folder rather than a workshop root."""
    try:
        if (path / "lang").is_dir() or (path / "Text").is_dir():
            return True
        return next(path.glob("*.modinfo"), None) is not None
    except OSError:  # pragma: no cover - unreadable folder
        return False


def default_mod_dirs() -> list[Path]:
    """Every installed MOD folder, or ``[]`` (``CIV6_MOD_DIRS`` overrides).

    ``CIV6_MOD_DIRS`` accepts ``;``/``,``-separated paths, each of which may be
    a MOD folder or a workshop ``content/289070`` root (its children are used);
    an empty value disables MOD text.
    """
    env = os.environ.get("CIV6_MOD_DIRS")
    if env is not None:
        return _expand_mod_dirs(env)
    out: list[Path] = []
    for root in WORKSHOP_ROOTS:
        if root.is_dir():
            out.extend(sorted(p for p in root.iterdir() if p.is_dir()))
    return out


def _first(value: str) -> str:
    """Civ city names pack grammatical cases as ``a|b|c``; keep the first."""
    if not value:
        return ""
    return value.split("|")[0].strip()


def _clean(text: str) -> str:
    return _first(html.unescape(text).strip())


def _implied_language(path: Path) -> str | None:
    for part in reversed(path.parts):
        if part in LOCALE_DIRS:
            return LOCALE_DIRS[part]
    stem = path.stem.lower()
    if stem in FILENAME_LANGS:
        return FILENAME_LANGS[stem]
    return None


def _iter_base_text(game_dir: Path):
    """``Base/Assets/Text`` (recurses into the per-locale folders)."""
    root = game_dir / "Base" / "Assets" / "Text"
    if root.is_dir():
        for xml in sorted(root.rglob("*.xml")):
            yield xml


def _iter_dlc_text(game_dir: Path):
    """``DLC/**`` XML living under a ``Text`` directory (DLC + expansions)."""
    root = game_dir / "DLC"
    if not root.is_dir():
        return
    for xml in sorted(root.rglob("*.xml")):
        if "text" in [part.lower() for part in xml.parts]:
            yield xml


def _iter_mod_text(mod: Path):
    """Every ``*.xml`` of one MOD folder (MODs keep text under ``lang/``)."""
    for xml in sorted(mod.rglob("*.xml")):
        if any(part.lower() in ("text", "lang") for part in xml.parts):
            yield xml


def _harvest(records: dict, path: Path, *, overwrite: bool) -> None:
    """Merge one XML file's ``zh_Hans_CN`` / ``en_US`` rows into ``records``.

    With ``overwrite=False`` an already-filled slot wins, which is how the
    base-game > DLC > MOD priority is enforced across the harvest passes.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return
    if b"<Text" not in raw:
        return
    text = raw.decode("utf-8", "replace")
    implied = _implied_language(path)
    for m in _ELEMENT_RE.finditer(text):
        attrs = dict(_ATTR_RE.findall(m.group(2)))
        tag = attrs.get("Tag")
        if not tag:
            continue
        raw_lang = attrs.get("Language")
        lang = LANG_ALIASES.get(raw_lang, "") if raw_lang else ""
        if not lang:
            lang = implied or ""
        if lang not in KEEP_LANGS:
            continue
        tm = _TEXT_RE.search(m.group(3))
        if not tm:
            continue
        value = _clean(tm.group(1))
        if not value:
            continue
        slot = records.setdefault(tag, {})
        key = "zh" if lang == "zh_Hans_CN" else "en"
        if overwrite or not slot.get(key):
            slot[key] = value


def build_from_game_xml(game_dir: Path, mod_dirs=(),
                        ) -> tuple[dict, dict, dict]:
    """``(sections, base_records, used_mod_records)``.

    Base-game text wins over DLC scenario text (which rewrites vanilla terrain
    and government names); MOD text only fills ``LOC_MOMENT_CATEGORY_*`` and
    tags that neither base nor DLC carries.
    """
    city_tags = city_name_tags(game_dir, mod_dirs)
    records: dict = {}
    for xml in _iter_base_text(game_dir):
        _harvest(records, xml, overwrite=False)
    base_only = {tag: dict(rec) for tag, rec in records.items()}
    for xml in _iter_dlc_text(game_dir):
        _harvest(records, xml, overwrite=False)

    mod_records: dict = {}
    for mod in mod_dirs:
        for xml in _iter_mod_text(Path(mod)):
            _harvest(mod_records, xml, overwrite=False)

    used_mod: dict = {}
    for tag, rec in mod_records.items():
        if not _is_snapshot_tag(tag, city_tags):
            continue
        if tag.startswith("LOC_MOMENT_CATEGORY_") or tag not in records:
            used_mod[tag] = dict(rec)
    for tag, rec in used_mod.items():
        records.setdefault(tag, {}).update(rec)
    return _select(records, city_tags), base_only, used_mod


def build_from_cache(cache_dir: Path) -> dict:
    path = cache_dir / "DebugLocalization.sqlite"
    if not path.exists():
        raise SystemExit(
            f"未找到游戏文本目录，且缓存缺失：{path}\n"
            "请用 --game-dir 指向文明6安装目录。"
        )
    records: dict = {}
    con = sqlite3.connect(str(path))
    try:
        for lang, tag, text in con.execute(
                "select Language, Tag, Text from LocalizedText where Language in (?,?)",
                KEEP_LANGS):
            value = _clean(text or "")
            if not value:
                continue
            slot = records.setdefault(tag, {})
            slot["zh" if lang == "zh_Hans_CN" else "en"] = value
    finally:
        con.close()
    city_tags: set[str] = set()
    gameplay = cache_dir / "DebugGameplay.sqlite"
    if gameplay.exists():
        con = sqlite3.connect(gameplay.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            city_tags.update(row[0] for row in con.execute("select CityName from CityNames")
                             if row[0] and row[0].startswith("LOC_CITY_"))
        except sqlite3.OperationalError:
            pass  # Older / incomplete gameplay caches may lack this table.
        finally:
            con.close()
    return _select(records, city_tags)


# name-bearing tag families the tool snapshots; a TYPE resolves through
# ``LOC_<TYPE>_NAME`` / ``LOC_<TYPE>_FRONTEND_NAME`` (routes), while religions
# and golden-age moment categories are tagged without a ``_NAME`` suffix.
# Descriptions, effects and pedia paragraphs are deliberately skipped so the
# artifact stays small.
# v0.28.2: ``LOC_BELIEF_`` 是补上的 —— 万神殿 / 教条的中文名原来只从游戏缓存
# ``DebugLocalization.sqlite`` 里取（``gamedb.sqlite`` 的 names 表），而那份缓存
# **会缺行**：本机实测 ``LOC_BELIEF_HOLY_WATERS_NAME``（神圣水域，风云变幻的强化
# 信条）就不在里面，游戏里却显示得好好的。改用游戏自己的 Text XML 兜住。
_NAME_FAMILIES = (
    "LOC_CIVILIZATION_", "LOC_LEADER_", "LOC_UNIT_", "LOC_BUILDING_",
    "LOC_DISTRICT_", "LOC_PROJECT_", "LOC_TECH_", "LOC_CIVIC_",
    "LOC_POLICY_", "LOC_IMPROVEMENT_", "LOC_RESOURCE_", "LOC_FEATURE_",
    "LOC_TERRAIN_", "LOC_RELIGION_", "LOC_GOVERNOR_", "LOC_GOVERNMENT_",
    "LOC_GREAT_PERSON_CLASS_", "LOC_ROUTE_", "LOC_BELIEF_",
)

# ``LOC_MOMENT_CATEGORY_RELIGIOUS`` (no ``_NAME`` suffix) drives the golden-age
# commemoration names; the ``_BONUS_*`` / ``_DESCRIPTION`` relatives must not be
# pulled in.
_MOMENT_CATEGORY_RE = re.compile(r"^LOC_MOMENT_CATEGORY_[A-Z]+$")

# ``LOC_RELIGION_BUDDHISM`` / ``LOC_RELIGION_CUSTOM_1`` — religions carry no
# ``_NAME`` suffix either (``LOC_RELIGION_ORTHODOXY`` = 东正教).
_RELIGION_RE = re.compile(r"^LOC_RELIGION_[A-Z0-9]+$")

# ``<Row CivilizationType="CIVILIZATION_X" Name="LOC_..._NAME" …/>`` in the
# gameplay XML: the *authoritative* display-name tag of a civilization.
_CIV_ROW_RE = re.compile(
    r'CivilizationType="(CIVILIZATION_[A-Z0-9_]+)"[^>]*?\bName="(LOC_[A-Z0-9_]+)"')

_CITY_NAME_ATTR_RE = re.compile(r'\b(?:CityName|CapitalName)="(LOC_CITY_[^"]+)"')


def city_name_tags(game_dir: Path, mod_dirs=()) -> set[str]:
    """Gameplay city-name references, including Vietnam's ``LOC_CITY_*`` tags.

    Use references rather than the whole LOC_CITY_ family, which also contains
    city-panel labels and tooltips that do not belong in the city catalog.
    """
    tags: set[str] = set()
    roots = (game_dir / "Base" / "Assets" / "Gameplay", game_dir / "DLC",
             *(Path(p) for p in mod_dirs))
    for root in roots:
        if not root.is_dir():
            continue
        for xml in root.rglob("*.xml"):
            tags.update(_CITY_NAME_ATTR_RE.findall(
                xml.read_text(encoding="utf-8", errors="replace")))
    return tags


def _is_name_tag(tag: str) -> bool:
    return tag.endswith("_NAME") or tag.endswith("_FRONTEND_NAME")


def _is_snapshot_tag(tag: str, city_tags=()) -> bool:
    """True for the tags ``_select`` keeps (names only, never descriptions)."""
    if tag.startswith("LOC_CITY_NAME_") or tag in city_tags:
        return True
    if tag.startswith("LOC_CIVILIZATION_"):
        return _is_name_tag(tag)
    if _MOMENT_CATEGORY_RE.match(tag) or _RELIGION_RE.match(tag):
        return True
    return _is_name_tag(tag) and tag.startswith(_NAME_FAMILIES)


def _select(records: dict, city_tags=()) -> dict:
    """Split harvested rows into the ``city`` / ``civ`` / ``names`` sections."""
    city: dict = {}
    civ: dict = {}
    names: dict = {}
    for tag, rec in records.items():
        if tag.startswith("LOC_CITY_NAME_") or tag in city_tags:
            city[tag] = rec
        elif tag.startswith("LOC_CIVILIZATION_") and _is_name_tag(tag):
            civ[tag] = rec
        elif _MOMENT_CATEGORY_RE.match(tag):
            names[tag] = rec
        elif _RELIGION_RE.match(tag):
            names[tag] = rec
        elif _is_name_tag(tag) and tag.startswith(_NAME_FAMILIES):
            names[tag] = rec
    return {"city": _normalize(city), "civ": _normalize(civ),
            "names": _normalize(names)}


def civ_name_tags(game_dir: Path) -> dict:
    """``CIVILIZATION_X -> LOC_…_NAME`` from the game's ``Civilizations.xml``.

    Firaxis reuses legacy civilization TYPEs for renamed city-states: the TYPE
    ``CIVILIZATION_JAKARTA`` carries ``Name="LOC_CIVILIZATION_BANDAR_BRUNEI_NAME"``
    (斯里巴加湾 / Bandar Brunei) while the legacy ``LOC_CIVILIZATION_JAKARTA_NAME``
    still holds 雅加达.  The gameplay XML is the authority, so snapshot the map
    (DLC files are read last and win).
    """
    out: dict = {}
    for root in (game_dir / "Base" / "Assets" / "Gameplay", game_dir / "DLC"):
        if not root.is_dir():
            continue
        for xml in sorted(root.rglob("Civilizations.xml")):
            text = xml.read_text(encoding="utf-8", errors="replace")
            for type_str, tag in _CIV_ROW_RE.findall(text):
                out[type_str] = tag
    return out


def _normalize(section: dict) -> dict:
    """Guarantee a non-empty ``zh`` by falling back to ``en`` (and vice versa)."""
    out: dict = {}
    for tag, rec in section.items():
        zh = rec.get("zh") or rec.get("en") or ""
        en = rec.get("en") or rec.get("zh") or ""
        if not zh:
            continue
        out[tag] = {"zh": zh, "en": en}
    return dict(sorted(out.items()))


def build(game_dir: Path | None, cache_dir: Path, out: Path,
          mod_dirs=()) -> dict:
    mod_dirs = [Path(p) for p in mod_dirs]
    if game_dir is not None and (game_dir / "Base" / "Assets" / "Text").is_dir():
        sections, _, used_mod = build_from_game_xml(game_dir, mod_dirs)
        civ_tag = civ_name_tags(game_dir)
        source = "game_xml"
        used_dir = str(game_dir)
        mod_section = _normalize(used_mod)
        mod_used = sorted(mod_section)
    else:
        sections = build_from_cache(cache_dir)
        civ_tag = {}
        source = "debug_localization"
        used_dir = str(cache_dir)
        mod_section = {}
        mod_used = []
        mod_dirs = []
    doc = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "generator": "tools/build_loc.py",
        "source": source,
        "source_dir": used_dir,
        "mod_dirs": [str(p) for p in mod_dirs],
        "counts": {k: len(v) for k, v in sections.items()},
        "mod_used": mod_used,
        "city": sections["city"],
        "civ": sections["civ"],
        "names": sections["names"],
        "mod_names": mod_section,
        "civ_tag": dict(sorted(civ_tag.items())),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game-dir", default=str(default_game_dir()))
    ap.add_argument("--cache-dir", default=str(default_cache_dir()))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--mod-dirs", default=None,
                    help="MOD folders or workshop roots (;/,-separated); "
                         "'none' skips MOD text")
    args = ap.parse_args(argv)
    game_dir = Path(args.game_dir)
    if args.mod_dirs is None:
        mod_dirs = default_mod_dirs()
    else:
        mod_dirs = [] if args.mod_dirs.strip().lower() in ("none", "off", "-") \
            else _expand_mod_dirs(args.mod_dirs)
    doc = build(game_dir, Path(args.cache_dir), Path(args.out), mod_dirs=mod_dirs)
    print(json.dumps({"out": args.out, "source": doc["source"],
                      "counts": doc["counts"], "mods": len(doc["mod_dirs"]),
                      "mod_tags_used": len(doc["mod_used"])},
                     ensure_ascii=False, indent=2))
    if doc["source"] == "debug_localization":
        print("警告：未找到游戏文本目录，已降级读取 Debug 缓存。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
