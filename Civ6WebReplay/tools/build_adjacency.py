"""Freeze the loaded gameplay database for offline district adjacency.

Run after loading an official game: python tools/build_adjacency.py.
This deliberately never replaces the other game-data snapshots.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from civ6replay.database_versions import component_role
from civ6replay.mod_identity import manifest_metadata
DEFAULT_OUT = ROOT / "data" / "gamedb" / "vanilla" / "adjacency.json"
TABLES = (
    "District_Adjacencies", "Adjacency_YieldChanges", "ExcludedAdjacencies",
    "DistrictReplaces", "CivilizationTraits", "LeaderTraits", "Leaders",
    "TraitModifiers", "BeliefModifiers", "BuildingModifiers", "DistrictModifiers",
    "Modifiers", "ModifierArguments", "DynamicModifiers", "Requirements",
    "RequirementArguments", "RequirementSets", "RequirementSetRequirements",
    "Districts", "Buildings", "Features", "Resources", "Terrains", "Types",
)
BALANCE_TABLES = ("GovernorModifiers", "GovernorPromotionModifiers", "Governors", "GovernorPromotions")
CCB_TABLES = (*BALANCE_TABLES, "Ruivo_New_Adjacency", "Ruivo_AdjacencyType")


def official_titles(localization: Path, game_root: Path | None) -> list[str]:
    """Title spellings emitted by the save header, including localized DLCs."""
    titles = set()
    if not game_root or not game_root.is_dir():
        raise ValueError("需指定原版游戏安装目录 --game-root，以核对官方 DLC 标题")
    with closing(sqlite3.connect(localization.as_uri() + "?mode=ro", uri=True)) as loc:
        for path in sorted(game_root.glob("DLC/**/*.modinfo")):
            doc = ET.parse(path).getroot()
            name = doc.findtext("Properties/Name")
            if not name:
                continue
            titles.add(name)
            if name.startswith("LOC_"):
                tag = name[4:]
                for suffix in ("_MOD_TITLE", "_TITLE", "_NAME"):
                    if tag.endswith(suffix):
                        tag = tag[:-len(suffix)]
                        break
                titles.add(tag.replace("_", " ").title())
                titles.update(r[0] for r in loc.execute(
                    "select Text from LocalizedText where Tag=?", (name,)))
    return sorted(titles)


def build(gameplay: Path, localization: Path, game_root: Path,
          out: Path = DEFAULT_OUT, *, profile: str = "official",
          packages: list[dict] | None = None, mod_files: list[Path] | None = None) -> dict:
    if profile not in ("official", "ccb", "bbg"):
        raise ValueError("仅支持原版、CCB 和 BBG 快照")
    if profile != "official" and out.resolve() == DEFAULT_OUT.resolve():
        raise ValueError(f"{profile.upper()} 快照不能覆盖原版文件")
    gameplay = gameplay.resolve()
    with closing(sqlite3.connect(gameplay.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        # One read transaction prevents mixing two sessions during reload.
        conn.execute("begin")
        names = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        balance = any(n.startswith("Ruivo_") for n in names) or bool(conn.execute(
            "select 1 from Adjacency_YieldChanges where ID like '%BBG%' or ID like '%CCB%'"
        ).fetchone())
        if profile == "official" and balance:
            raise ValueError("当前数据库含 BBG / CCB 规则，请先加载原版游戏")
        if profile == "ccb" and not conn.execute(
                "select 1 from Adjacency_YieldChanges where ID like '%CCB%'"
        ).fetchone():
            raise ValueError("当前数据库未包含 CCB 相邻规则")
        if profile == "bbg":
            if any(n.startswith("Ruivo_") for n in names) or conn.execute(
                    "select 1 from Adjacency_YieldChanges where ID like '%CCB%'"
            ).fetchone():
                raise ValueError("BBG 采集检测到 CCB 规则，拒绝混用数据库")
            if not conn.execute("select 1 from Adjacency_YieldChanges where ID like '%BBG%'").fetchone():
                raise ValueError("当前数据库未包含 BBG 相邻规则")
        selected = (*TABLES, *CCB_TABLES) if profile == "ccb" else (
            (*TABLES, *BALANCE_TABLES) if profile == "bbg" else TABLES)
        missing = set(selected) - names
        if missing:
            raise ValueError(f"数据库缺少规则表: {sorted(missing)}")
        tables = {name: [dict(r) for r in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
                  for name in selected}
    payload = {"format": 1, "profile": profile, "tables": tables,
               "officialTitles": official_titles(localization.resolve(), game_root)}
    if profile != "official":
        if not packages or not any(component_role(p, profile) == "core" for p in packages):
            raise ValueError(f"需用当前 {profile.upper()} 存档核对启用的模组列表")
        if profile == "bbg" and any(component_role(p, "ccb") == "core" for p in packages):
            raise ValueError("BBG 存档同时含有 CCB，拒绝采集混合规则")
        payload["packages"] = packages
        payload["modSources"] = [{**manifest_metadata(ET.parse(path).getroot()),
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                 for path in mod_files or ()]
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                           ensure_ascii=False).encode("utf-8")).hexdigest()
    payload["fingerprint"] = fingerprint
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    return {"fingerprint": fingerprint, "counts": {k: len(v) for k, v in tables.items()},
            "output": str(out)}


def main():
    cache = Path(os.environ.get("LOCALAPPDATA", "")) / "Firaxis Games" / "Sid Meier's Civilization VI" / "Cache"
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=cache)
    ap.add_argument("--game-root", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--profile", choices=("official", "ccb", "bbg"), default="official")
    ap.add_argument("--save", type=Path, help="模组规则快照对应的当前存档")
    ap.add_argument("--mod-file", type=Path, action="append", default=[])
    args = ap.parse_args()
    packages = None
    if args.profile != "official":
        if not args.save:
            ap.error("模组导出需提供 --save")
        if args.save.stat().st_mtime < (args.cache_dir / "DebugGameplay.sqlite").stat().st_mtime:
            ap.error("请使用当前数据库加载后保存的存档")
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from civ6replay.mods import parse_mod_packages
        packages = parse_mod_packages(args.save.read_bytes())
    print(json.dumps(build(args.cache_dir / "DebugGameplay.sqlite",
                           args.cache_dir / "DebugLocalization.sqlite",
                           args.game_root, args.out or (DEFAULT_OUT if args.profile == "official" else
                               ROOT / f"data/gamedb/{args.profile}/adjacency.json"), profile=args.profile,
                           packages=packages, mod_files=args.mod_file), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
