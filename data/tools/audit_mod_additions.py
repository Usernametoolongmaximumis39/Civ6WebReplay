"""List captured non-official TYPEs and their source evidence; never edit game data."""
from __future__ import annotations

from tool_paths import ROOT, DEV, WORKSPACE

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET

from build_loc import WORKSHOP_ROOTS, _harvest, _iter_base_text, _iter_dlc_text, default_game_dir


ENGINE_KINDS = {"KIND_COLLECTION", "KIND_EFFECT", "KIND_REQUIREMENT"}
TOKEN = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
SQL_STR = re.compile(r"'((?:[^']|'')*)'")
TYPE_INSERT = re.compile(
    r'\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO)\s+[\["`]?Types\b.*?;', re.I | re.S)
ENTITIES = {
    "KIND_CIVILIZATION": ("Civilizations", "CivilizationType", "文明"),
    "KIND_LEADER": ("Leaders", "LeaderType", "领袖"),
    "KIND_UNIT": ("Units", "UnitType", "单位"),
    "KIND_BUILDING": ("Buildings", "BuildingType", "建筑与人造奇观"),
    "KIND_DISTRICT": ("Districts", "DistrictType", "区域"),
    "KIND_IMPROVEMENT": ("Improvements", "ImprovementType", "改良设施"),
    "KIND_FEATURE": ("Features", "FeatureType", "地貌与自然奇观"),
    "KIND_RESOURCE": ("Resources", "ResourceType", "资源"),
    "KIND_POLICY": ("Policies", "PolicyType", "政策"),
    "KIND_PROJECT": ("Projects", "ProjectType", "项目"),
    "KIND_GOVERNOR": ("Governors", "GovernorType", "总督"),
    "KIND_GOVERNOR_PROMOTION": ("GovernorPromotions", "GovernorPromotionType", "总督晋升"),
    "KIND_PROMOTION": ("UnitPromotions", "UnitPromotionType", "单位晋升"),
    "KIND_PROMOTION_CLASS": ("UnitPromotionClasses", "PromotionClassType", "单位晋升类别"),
    "KIND_GREAT_PERSON_CLASS": ("GreatPersonClasses", "GreatPersonClassType", "伟人类别"),
    "KIND_GREAT_PERSON_INDIVIDUAL": ("GreatPersonIndividuals", "GreatPersonIndividualType", "伟人个体"),
    "KIND_TRAIT": ("Traits", "TraitType", "特性"),
    "KIND_ABILITY": ("UnitAbilities", "UnitAbilityType", "单位能力"),
    "KIND_MODIFIER": ("DynamicModifiers", "ModifierType", "修正器类型"),
    "KIND_PSEUDOYIELD": ("PseudoYields", "PseudoYieldType", "AI 虚拟产出"),
}
for suffix in ("MOUNTAIN", "RIVER", "LAKE", "SEA", "VOLCANO"):
    plural = {"SEA": "Seas", "VOLCANO": "Volcanoes"}.get(suffix, suffix.title() + "s")
    ENTITIES["KIND_NAMED_" + suffix] = ("Named" + plural, "Named" + suffix.title() + "Type", "地理名称")


def read_sql(path):
    return path.read_text(encoding="utf-8-sig", errors="replace")


def declarations(raw, xml=False):
    """Literal registrations plus read-only SELECTs that generate registrations."""
    literal, queries = set(), []
    if xml:
        try:
            doc = ET.fromstring(raw)
        except ET.ParseError:
            return literal, queries
        for table in doc.iter("Types"):
            literal.update(row.get("Type") for row in table if row.get("Type") and row.tag in ("Row", "Replace"))
    else:
        code = re.sub(r"/\*.*?\*/|--[^\n]*", "", raw, flags=re.S)
        for match in TYPE_INSERT.finditer(code):
            statement = match.group()
            literal.update(s.replace("''", "'") for s in SQL_STR.findall(statement))
            # Civ6 SQLite also accepts double-quoted string literals.
            literal.update(re.findall(r'"([A-Z][A-Z0-9_ ]+)"', statement))
            select = re.search(r"\bSELECT\b.*", statement, re.I | re.S)
            if select:
                queries.append(select.group())
    return literal, queries


def official_inventory(game_root):
    """Conservative inventory: official declarations AND references, including scenarios.

    References retain engine-defined types absent from XML Types registrations.
    Exact attribute/SQL values retain official identifiers containing spaces.
    """
    known, files = set(), []
    for root in (game_root / "Base/Assets/Gameplay", game_root / "DLC"):
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in (".xml", ".sql"):
                continue
            raw = read_sql(path)
            known.update(TOKEN.findall(raw))
            if path.suffix.lower() == ".xml":
                known.update(re.findall(r'\b\w+\s*=\s*"([^"]*)"', raw))
            else:
                known.update(s.replace("''", "'") for s in SQL_STR.findall(raw))
            files.append({"path": path.relative_to(game_root).as_posix(),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if not files:
        raise ValueError("No official gameplay sources found")
    return known, files


def source_inventory(capture):
    selected = {s["id"].lower(): s for s in capture["sources"]}
    sources, labels = [], {}
    for root in WORKSHOP_ROOTS:
        for info in sorted(root.glob("*/*.modinfo")):
            doc = ET.parse(info).getroot()
            identity = doc.get("id", "").lower()
            if identity not in selected:
                continue
            expected = selected[identity]["modinfoSha256"]
            if hashlib.sha256(info.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Installed modinfo differs from capture: {info}")
            for path in sorted(info.parent.rglob("*")):
                if path.suffix.lower() not in (".sql", ".xml", ".lua"):
                    continue
                raw = read_sql(path)
                if path.suffix.lower() == ".xml":
                    _harvest(labels, path, overwrite=False)
                literal, queries = declarations(raw, path.suffix.lower() == ".xml")
                sources.append({"modId": identity, "modName": doc.findtext("Properties/Name"),
                                "path": path.relative_to(info.parent).as_posix(),
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                "literal": literal, "queries": queries, "raw": raw})
    found = {s["modId"] for s in sources}
    if set(selected) - found:
        raise ValueError(f"Missing captured mod sources: {set(selected) - found}")
    # SQL text packs use LocalizedText or BaseGameText rather than XML rows.
    with sqlite3.connect(":memory:") as textdb:
        textdb.execute("CREATE TABLE LocalizedText(Language TEXT, Tag TEXT, Text TEXT, PRIMARY KEY(Language,Tag))")
        textdb.execute("CREATE TABLE BaseGameText(Tag TEXT PRIMARY KEY, Text TEXT)")
        for source in sources:
            if not source["path"].lower().endswith(".sql"):
                continue
            for match in re.finditer(
                r"\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO)\s+(?:LocalizedText|BaseGameText)\b.*?;",
                source["raw"], re.I | re.S):
                try:
                    textdb.execute(match.group())
                except sqlite3.Error:
                    continue  # Unsupported dynamic text is left explicitly unresolved.
        for lang, tag, value in textdb.execute("SELECT Language,Tag,Text FROM LocalizedText"):
            if lang in ("zh_Hans_CN", "en_US"):
                labels.setdefault(tag, {}).setdefault("zh" if lang == "zh_Hans_CN" else "en", value)
        for tag, value in textdb.execute("SELECT Tag,Text FROM BaseGameText"):
            labels.setdefault(tag, {}).setdefault("en", value)
    return sources, labels


def audit(profile, game_root, output, directory=None):
    directory = Path(directory).resolve() if directory else WORKSPACE / "data/gamedb" / profile
    capture = json.loads((directory / "capture.json").read_text(encoding="utf-8"))
    official, official_files = official_inventory(game_root)
    sources, labels = source_inventory(capture)
    for path in (*_iter_base_text(game_root), *_iter_dlc_text(game_root)):
        _harvest(labels, path, overwrite=False)
    identities = {e["type"]: e for e in json.loads((ROOT / "data/vanilla/identities.json").read_text(encoding="utf-8"))["entries"]}
    shared = ROOT / "data/shared/identities.json"
    if shared.is_file():
        identities.update({e["type"]: e for e in json.loads(shared.read_text(encoding="utf-8"))["entries"]})
    with sqlite3.connect((ROOT / "data/gamedb/vanilla/gamedb.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as v:
        bundled = {r[0] for r in v.execute("SELECT type FROM types")}
    rows, excluded = [], []
    with sqlite3.connect((directory / "gameplay.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        # Evaluate registration SELECTs against the captured tables. Prefix
        # matching alone would incorrectly assign every TRAIT_CIVILIZATION_*
        # to Steel Thunder's conditional EnabledUniqueUnits registration.
        for source in sources:
            for query in source["queries"]:
                try:
                    source["literal"].update(r[0] for r in db.execute(query) if r[0])
                except sqlite3.Error:
                    pass
        entity_rows = {}
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for kind, (table, key, _) in ENTITIES.items():
            if table in tables:
                entity_rows[kind] = {r[key]: dict(r) for r in db.execute(f'SELECT * FROM "{table}"')}
        for typ, hash_value, kind in db.execute("SELECT Type,Hash,Kind FROM Types ORDER BY Kind,Type"):
            if typ in official:
                continue
            evidence = [s for s in sources if typ in s["literal"]]
            historical = False
            # _utils registers abilities before Spy.sql deletes this original
            # promotion. Re-running the SELECT on the final snapshot cannot
            # reproduce that one retained ability, so retain both source facts.
            prefix = "BBG_FAKE_ABILITY_"
            if not evidence and typ.startswith(prefix) and typ[len(prefix):] in official:
                suffix = typ[len(prefix):]
                deleted = [s for s in sources if re.search(
                    r"DELETE\s+FROM\s+UnitPromotions\s+WHERE\s+UnitPromotionType\s*=\s*['\"]" + re.escape(suffix) + r"['\"]",
                    s["raw"], re.I)]
                generated = [s for s in sources if any(re.search(
                    r"'BBG_FAKE_ABILITY_'\s*\|\|\s*UnitPromotionType", q, re.I) for q in s["queries"])]
                if deleted and generated:
                    evidence = generated + deleted
                    historical = True
            # Engine types are registered by the executable, not official XML.
            # Exclude only if also present in the bundled baseline AND no mod declaration.
            if kind in ENGINE_KINDS and typ in bundled and not evidence:
                excluded.append({"type": typ, "kind": kind, "reason": "baseline engine type; no mod registration"})
                continue
            rec = entity_rows.get(kind, {}).get(typ)
            tag = rec.get("Name") if rec else None
            tag = tag or "LOC_" + typ + "_NAME"
            text = labels.get(tag, {})
            identity = identities.get(typ, {})
            icon = identity.get("icon")
            icon_exists = bool(icon and (ROOT / "assets/icons" / icon).is_file())
            rows.append({"type": typ, "kind": kind, "hash": hash_value & 0xFFFFFFFF,
                         "hex": f"0x{hash_value & 0xFFFFFFFF:08X}", "nameKey": tag,
                         "zh": text.get("zh"), "en": text.get("en"), "entity": rec,
                         "status": "实体表存在" if rec is not None else "仅 TYPE 注册，无实体行",
                         "alreadyInBundledTypes": typ in bundled,
                         "identityExists": bool(identity), "existingIcon": icon if icon_exists else None,
                         "sourceEvidence": [{k: s[k] for k in ("modId", "modName", "path", "sha256")} for s in evidence],
                         "sourceStatus": "动态注册后，对应晋升已删除" if historical else
                         "已找到 TYPE 注册语句" if evidence else "未定位注册语句，待核对"})
    counts = dict(sorted(Counter(r["kind"] for r in rows).items()))
    doc = {"profile": profile, "capturedAt": capture["capturedAt"], "packages": capture["packages"],
           "snapshotDirectory": directory.relative_to(WORKSPACE).as_posix(),
           "method": "Captured Types minus official Base/DLC declarations and references; exclude baseline engine types without mod registrations",
           "gameplaySha256": hashlib.sha256((directory / "gameplay.sqlite").read_bytes()).hexdigest(),
           "officialFiles": official_files, "counts": counts, "entries": rows, "excludedEngineTypes": excluded}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = DEV / "docs" / f"{profile}-additions.md"
    lines = [f"# {profile.upper()} 当前采集的新增内容清单", "",
             f"采集时间：{capture['capturedAt']}。本清单依据 `{(directory / 'gameplay.sqlite').relative_to(WORKSPACE).as_posix()}`，不受当前运行中的游戏影响。", "",
             "对比口径：原版包括游戏本体、官方 DLC、资料片与官方场景；只列新增 TYPE，不列已有内容的数值、效果和名称修改。",
             "项目 vanilla/gamedb.sqlite 已含模组条目，因此以安装目录的官方 XML/SQL 声明与引用为排除依据。",
             "未在官方文件出现的引擎类型，只有同时存在于旧基准且未找到模组注册语句时才排除。",
             "来源以 Types 注册语句为依据；引用或翻译一个 TYPE 不视为新增该 TYPE。SQL 拼接生成的 TYPE 通过在只读采集库中执行其 SELECT 子句追溯。", "",
             f"共 **{len(rows)}** 个非原版 TYPE；其中 **{sum(r['alreadyInBundledTypes'] for r in rows)}** 个已混入项目旧原版库。另排除 **{len(excluded)}** 个旧基准已有的引擎 TYPE。",
             "中文名从已核对版本的模组源文件补读；采集 labels.json 缺少许多模组文本。名称无法补读时显示 TYPE。",
             "贴图列检查基础与共享 identities.json 索引指向的本地 PNG 是否存在；视觉验证记录见 docs/shared-mod-icons.md。", "",
             "## 分类统计", "", "| 分类 | KIND | 数量 |", "|---|---|---:|"]
    for kind, count in counts.items():
        lines.append(f"| {ENTITIES.get(kind, ('', '', kind))[2]} | `{kind}` | {count} |")
    owners = Counter(tuple(sorted({s["modName"] for s in r["sourceEvidence"]})) for r in rows)
    lines += ["", "## 注册来源统计", "", "| 来源 | TYPE 数 |", "|---|---:|"]
    for owner, count in sorted(owners.items()):
        lines.append(f"| {' / '.join(owner) or '待核对'} | {count} |")
    lines += ["", f"本清单包含此次 {profile.upper()} 配置中核心、文明拓展及配套地图/多人助手的新增 TYPE；注册来源逐项列示。"]
    lines += ["", "## 完整条目", "",
              "`已收录` 指项目现有 identities.json 有该 TYPE；隐藏设施、虚拟资源以及仅注册的条目需按用途决定适配方式。", ""]
    ordered = list(ENTITIES) + sorted(set(counts) - set(ENTITIES))
    for kind in ordered:
        group = [r for r in rows if r["kind"] == kind]
        if not group:
            continue
        lines += [f"### {ENTITIES.get(kind, ('', '', kind))[2]}：{kind}（{len(group)}）", "",
                  "| 名称 | TYPE | 哈希 | 注册来源 | 状态 | 现有 TYPE/贴图 |",
                  "|---|---|---|---|---|---|"]
        for row in group:
            owners = "/".join(dict.fromkeys(s["modName"] for s in row["sourceEvidence"])) or "待核对"
            status = row["status"]
            if row["entity"] and row["entity"].get("InternalOnly"):
                status += "；InternalOnly"
            coverage = ("已收录" if row["identityExists"] else "未收录") + ("；有 PNG" if row["existingIcon"] else "；无已索引 PNG")
            name = (row["zh"] or row["en"] or "—").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {name} | `{row['type']}` | `{row['hex']}` | {owners} | {status} | {coverage} |")
        lines.append("")
    lines += ["## 复核与复现", "", f"机器可读明细：`{output.relative_to(WORKSPACE).as_posix()}`。包含实体行、来源文件与 SHA-256，可供后续 TYPE/贴图适配。", "",
              f"复现：`python -B data/tools/audit_mod_additions.py --profile {profile}" +
              (f" --snapshot-dir {directory.relative_to(WORKSPACE).as_posix()}" if directory != WORKSPACE / "data/gamedb" / profile else "") +
              "`。需要本机官方游戏文件与此次采集所启用模组的相同 modinfo 版本。",
              "模组实体表是否存在只表示此次采集已加载定义；不代表这一局地图中实际出现，也不保证在所有模式中可建造。", ""]
    report.write_text("\n".join(lines), encoding="utf-8")
    return {"report": str(report), "json": str(output), "total": len(rows), "counts": counts,
            "unresolved": [r["type"] for r in rows if not r["sourceEvidence"]]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("bbg", "ccb"), default="bbg")
    parser.add_argument("--game-root", type=Path, default=default_game_dir())
    parser.add_argument("--out", type=Path)
    parser.add_argument("--snapshot-dir", type=Path, help="Separate capture.json/gameplay.sqlite directory for a read-only additions audit")
    args = parser.parse_args()
    print(json.dumps(audit(args.profile, args.game_root, args.out or WORKSPACE / "data/gamedb" / args.profile / "additions-audit.json", args.snapshot_dir), ensure_ascii=False, indent=2))
