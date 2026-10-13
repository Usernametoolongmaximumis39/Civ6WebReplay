"""Freeze the loaded gameplay database for offline, per-turn plot yields.

Load the target game first; mod capture additionally requires its fresh save.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import re
import xml.etree.ElementTree as ET

from build_adjacency import TABLES as ADJACENCY_TABLES, official_titles
from build_loc import default_game_dir
from build_loc import WORKSHOP_ROOTS
from build_loc import _harvest, _iter_base_text, _iter_dlc_text, _iter_mod_text

ROOT = Path(__file__).resolve().parents[1]
TABLES = tuple(dict.fromkeys((*ADJACENCY_TABLES,
    "Terrain_YieldChanges", "Feature_YieldChanges", "Resource_YieldChanges",
    "Improvement_YieldChanges", "Improvement_BonusYieldChanges",
    "Improvement_Adjacencies", "Feature_AdjacentYields", "Improvements",
    "ImprovementModifiers", "Improvement_ValidResources",
    "Improvement_YieldsOutsideTerritories", "Adjacent_AppealYieldChanges",
    "PolicyModifiers", "GovernmentModifiers", "GovernorModifiers",
    "GovernorPromotionModifiers", "TechnologyModifiers", "CivicModifiers",
    "CommemorationModifiers", "GameModifiers", "TypeTags",
    "TerrainClass_Terrains", "Eras", "Yields", "GlobalParameters")))

# Display tags cannot always be derived from TYPE: e.g. a minor trait names
# its leader, and BBG's agriculture promotion omits BBG_ from its name tag.
NAME_TABLES = (
    ("Traits", "TraitType", "Name"), ("Beliefs", "BeliefType", "Name"),
    ("Policies", "PolicyType", "Name"), ("Governments", "GovernmentType", "Name"),
    ("GovernorPromotions", "GovernorPromotionType", "Name"),
    ("Technologies", "TechnologyType", "Name"), ("Civics", "CivicType", "Name"),
    ("CommemorationTypes", "CommemorationType", "CategoryDescription"),
)


def read_name_keys(connection):
    """Read authoritative name tags from this profile's captured database."""
    existing = {r[0] for r in connection.execute("select name from sqlite_master where type='table'")}
    return {typ: tag for table, field, name in NAME_TABLES if table in existing
            for typ, tag in connection.execute(f'SELECT "{field}","{name}" FROM "{table}"')
            if tag}


def official_name_keys(game_root):
    """Name metadata for repairing old snapshots, restricted to official types."""
    keys = {}
    for root in (game_root / "Base/Assets/Gameplay", game_root / "DLC"):
        for path in sorted(root.rglob("*.xml")):
            if root.name == "DLC" and not any(p.lower() == "data" for p in path.parts):
                continue
            try:
                doc = ET.parse(path).getroot()
            except (ET.ParseError, OSError):
                continue
            for table, field, name in NAME_TABLES:
                for rows in doc.iter(table):
                    for row in rows:
                        typ, tag = row.get(field), row.get(name)
                        if typ and tag:
                            keys.setdefault(typ, tag)
    return keys


def public_modifier_name_keys(tables):
    """Name public wonder effects from the source wonder's requirements.

    Recipient features on attached child modifiers are not source names.
    """
    features = {r['FeatureType']:r for r in tables['Features'] if r.get('NaturalWonder')}
    modifiers = {r['ModifierId']:r for r in tables['Modifiers']}
    members, arguments = defaultdict(list), defaultdict(dict)
    for row in tables['RequirementSetRequirements']:
        members[row['RequirementSetId']].append(row['RequirementId'])
    for row in tables['RequirementArguments']:
        arguments[row['RequirementId']][row['Name']]=row['Value']
    def source_features(sid,visiting=()):
        if not sid or sid in visiting:
            return set()
        found=set()
        for rid in members[sid]:
            args=arguments[rid]
            if args.get('FeatureType') in features:
                found.add(args['FeatureType'])
            found.update(source_features(args.get('RequirementSetId'),(*visiting,sid)))
        return found
    keys={}
    for row in tables['GameModifiers']:
        mid=row['ModifierId'];modifier=modifiers.get(mid,{})
        found=source_features(modifier.get('OwnerRequirementSetId')) | source_features(modifier.get('SubjectRequirementSetId'))
        if len(found)==1:
            tag=features[next(iter(found))].get('Name')
            if tag:
                keys[mid]=tag
    return keys


def supplement_labels(labels, name_keys, tables, game_root, mod_files=()):
    """Fill missing display text without replacing captured MOD translations.

    Only explicitly selected MODs may supply text. Official Text XML covers
    DLC strings absent from DebugLocalization; runtime remains fully offline.
    """
    needed = set(name_keys.values())
    for rows in tables.values():
        needed.update(row['Name'] for row in rows if row.get('Name'))
    records = {}
    for info in mod_files or ():
        for path in _iter_mod_text(Path(info).parent):
            _harvest(records, path, overwrite=False)
    for path in (*_iter_base_text(game_root), *_iter_dlc_text(game_root)):
        _harvest(records, path, overwrite=False)
    # The bundled name snapshot also covers text shipped as MOD SQL, which
    # the XML fallback cannot read. Copy only tags used by this profile.
    name_snapshot = ROOT / "data/vanilla/loc.json"
    bundled = {}
    if name_snapshot.is_file():
        bundled = json.loads(name_snapshot.read_text(encoding='utf-8')).get('names', {})
        for tag in needed:
            value = bundled.get(tag, {}).get('zh')
            if value:
                records.setdefault(tag, {}).setdefault('zh', value)
    # Some unit traits have an unlocalized trait tag but a localized unit name.
    for tag in needed:
        if tag.startswith('LOC_TRAIT_CIVILIZATION_UNIT_'):
            unit_tag = tag.replace('LOC_TRAIT_CIVILIZATION_', 'LOC_', 1)
            value = (labels.get(unit_tag) or records.get(unit_tag, {}).get('zh')
                     or bundled.get(unit_tag, {}).get('zh'))
            if value:
                records.setdefault(tag, {}).setdefault('zh', value)
    # This internal trait intentionally has no game-facing name.
    records.setdefault('LOC_TRAIT_LEADER_MAJOR_CIV_NAME', {}).setdefault('zh', '通用文明规则')
    labels = dict(labels)
    for tag in sorted(needed):
        if not labels.get(tag) and records.get(tag, {}).get('zh'):
            labels[tag] = records[tag]['zh']
    return labels


def clean_title(title):
    return re.sub(r"\[(?:COLOR[^\]]*|ENDCOLOR)\]", "", title).strip()


def validate_profile(profile, tables, packages):
    ids = {r["ID"] for r in tables["Adjacency_YieldChanges"]}
    ccb = any(i.startswith("CCB_") for i in ids)
    balanced = ccb or any("BBG" in i for i in ids)
    titles = [clean_title(p["name"]) for p in packages]
    if profile == "vanilla" and balanced:
        raise ValueError("请先运行原版游戏；当前数据库含平衡模组规则")
    if profile == "ccb" and (not ccb or not any(re.search(r"\bCCB\b|和而不同", t, re.I) for t in titles)):
        raise ValueError("当前数据库与存档未同时确认 CCB，拒绝采集")
    if profile == "bbg" and (not balanced or ccb
            or not any(re.search(r"better\s+balanced\s+game|\bBBG\b", t, re.I) for t in titles)
            or any(re.search(r"\bCCB\b|和而不同", t, re.I) for t in titles)):
        raise ValueError("当前数据库与存档未同时确认独立 BBG，或混入 CCB，拒绝采集")
    if profile not in ("vanilla", "ccb", "bbg"):
        raise ValueError("未知产出规则集")
    if any("受命于天" in t or "纪元回响" in t for t in titles):
        raise ValueError("当前启用了尚不支持的 CCB 扩展规则")


def mod_sources(packages, localization):
    """Record installed versions and script hashes; never evaluate mod scripts."""
    titles = {clean_title(p["name"]) for p in packages}
    keys = {p["key"] for p in packages}
    with closing(sqlite3.connect(localization.resolve().as_uri() + "?mode=ro", uri=True)) as loc:
        localized = {tag: text for tag, text in loc.execute(
            "select Tag,Text from LocalizedText where Language='zh_Hans_CN'")}
    sources = []
    for root in WORKSHOP_ROOTS:
        if not root.is_dir():
            continue
        for path in root.glob("*/*.modinfo"):
            doc = ET.parse(path).getroot()
            title = doc.findtext("Properties/Name") or ""
            if title not in keys and clean_title(title) not in titles:
                continue
            scripts = []
            for component in doc.findall("InGameActions/AddGameplayScripts"):
                for entry in component.findall("File"):
                    file = path.parent / entry.text
                    if file.exists():
                        scripts.append({"path": entry.text,
                                        "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
            sources.append({"id": doc.get("id"), "name": localized.get(title, title),
                            "version": doc.findtext("Properties/Version") or doc.get("version"),
                            "scripts": scripts})
    return sources


def build(gameplay, localization, game_root, out=None, *, profile="vanilla", save=None,
          packages=None, sources=None, mod_files=None):
    out = out or ROOT / f"data/gamedb/{profile}/tileyields.json"
    packages = packages or []
    if save:
        sys.path.insert(0, str(ROOT / "src"))
        from civ6replay.mods import parse_mod_packages
        packages = parse_mod_packages(save.read_bytes())
        if save.stat().st_mtime < gameplay.stat().st_mtime:
            raise ValueError("请在当前游戏数据库加载后保存一回合，再采集")
    elif profile != "vanilla":
        raise ValueError("模组采集必须用 --save 指定当前运行后生成的存档")
    with closing(sqlite3.connect(gameplay.resolve().as_uri() + "?mode=ro", uri=True)) as c:
        c.row_factory = sqlite3.Row
        c.execute("begin")
        names = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        if missing := set(TABLES) - names:
            raise ValueError(f"缺少产出规则表：{sorted(missing)}")
        tables = {t: [dict(r) for r in c.execute(f'SELECT * FROM "{t}" ORDER BY rowid')]
                  for t in TABLES}
        name_keys = read_name_keys(c)
        name_keys.update(public_modifier_name_keys(tables))
        for table, field in (("TraitModifiers", "TraitType"), ("BeliefModifiers", "BeliefType"),
                             ("PolicyModifiers", "PolicyType"), ("GovernmentModifiers", "GovernmentType"),
                             ("GovernorPromotionModifiers", "GovernorPromotionType"),
                             ("TechnologyModifiers", "TechnologyType"), ("CivicModifiers", "CivicType"),
                             ("CommemorationModifiers", "CommemorationType")):
            for row in tables[table]:
                name_keys.setdefault(row[field], "LOC_" + row[field] + "_NAME")
        # Extra runtime tables are included for audit even if their Lua state
        # cannot yet be reconstructed from a save.
        if profile != "vanilla":
            for t in sorted(names):
                if t.startswith("Ruivo_") or t in ("AbstractModifiers", "Flat_CutOffYieldValues", "Hill_CutOffYieldValues"):
                    tables[t] = [dict(r) for r in c.execute(f'SELECT * FROM "{t}" ORDER BY rowid')]
    validate_profile(profile, tables, packages)
    with closing(sqlite3.connect(localization.resolve().as_uri() + "?mode=ro", uri=True)) as loc:
        labels = {tag: value for tag, value in loc.execute(
            "select Tag,Text from LocalizedText where Language='zh_Hans_CN'")}
    labels = supplement_labels(labels, name_keys, tables, game_root, mod_files)
    document = {"format": 1, "profile": profile, "tables": tables,
                "labels": labels, "nameKeys": name_keys,
                "officialTitles": official_titles(localization.resolve(), game_root)}
    if profile != "vanilla":
        sys.path.insert(0, str(ROOT / "src"))
        from civ6replay.adjacency import _official_package
        from types import SimpleNamespace
        official = SimpleNamespace(official_titles=set(document["officialTitles"]))
        gameplay_packages = [p for p in packages if not (
            _official_package(p["key"], official) or _official_package(p["name"], official))]
        def expected_package(p):
            if profile == "ccb":
                return bool(re.search(r"\bCCB\b|和而不同", clean_title(p["name"]), re.I))
            return bool(re.search(r"better\s+balanced\s+game|\bBBG\b", clean_title(p["name"]), re.I)
                        or p["key"] in ("LOC_BBM_TITLE", "LOC_MPH_TITLE"))
        if any(not expected_package(p) for p in gameplay_packages):
            raise ValueError("存档包含额外且未核验的游戏模组，拒绝覆盖规则快照")
        document["enabledPackages"] = gameplay_packages
        document["sources"] = sources if sources is not None else mod_sources(packages, localization)
        core = r"(?:CCB|和而不同)\s+v?\d" if profile == "ccb" else r"(?:Better Balanced Game|BBG)\s+v?\d"
        from civ6replay.database_versions import CORE_IDS
        if not any(re.match(core, s["name"]) or s.get("id", "").lower() == CORE_IDS[profile]
                   for s in document["sources"]):
            raise ValueError(f"未找到已启用 {profile.upper()} 核心的版本来源")
    document["fingerprint"] = hashlib.sha256(json.dumps(
        document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    return {"output": str(out), "fingerprint": document["fingerprint"],
            "counts": {t: len(rows) for t, rows in tables.items()}}


if __name__ == "__main__":
    cache = Path(os.environ["LOCALAPPDATA"]) / "Firaxis Games/Sid Meier's Civilization VI/Cache"
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=cache)
    ap.add_argument("--game-root", type=Path, default=default_game_dir())
    ap.add_argument("--out", type=Path)
    ap.add_argument("--profile", choices=("vanilla", "ccb", "bbg"), default="vanilla")
    ap.add_argument("--save", type=Path)
    args = ap.parse_args()
    print(json.dumps(build(args.cache_dir / "DebugGameplay.sqlite",
                           args.cache_dir / "DebugLocalization.sqlite",
                           args.game_root, args.out, profile=args.profile, save=args.save), ensure_ascii=False, indent=2))
