"""Build the bundled game-database snapshot from Civ6's debug SQLite files.

Reads ``DebugGameplay.sqlite`` + ``DebugLocalization.sqlite`` from the game
cache and writes ``data/gamedb/vanilla/gamedb.sqlite`` + ``manifest.json``.
Only vanilla content is exported (mod-only types are filtered by comparing
against the recorded mod list).

v0.28.2: the display names additionally merge ``data/vanilla/loc.json`` (the
game's own ``Text`` XML, see ``build_loc.py``) because the ``DebugLocalization``
cache can be missing rows for content the current MOD set enables — that is how
``BELIEF_HOLY_WATERS`` (神圣水域) ended up unresolvable.

Usage::

    python -B data/tools/build_gamedb.py [--profile vanilla] [--loc-json PATH]
"""
from __future__ import annotations

from tool_paths import ROOT, DEV, WORKSPACE

import argparse
import datetime as _dt
import json
import os
import sqlite3
from pathlib import Path




def _crc32_type(text: str) -> int:
    import binascii
    return (~binascii.crc32(text.encode("ascii")) & 0xFFFFFFFF)


def default_cache_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "")
    return Path(local) / "Firaxis Games" / "Sid Meier's Civilization VI" / "Cache"


# entity table -> category + (source type column, name column)
ENTITIES = [
    ("terrains", "terrain", "Terrains", "TerrainType", "Name"),
    ("features", "feature", "Features", "FeatureType", "Name"),
    ("resources", "resource", "Resources", "ResourceType", "Name"),
    ("improvements", "improvement", "Improvements", "ImprovementType", "Name"),
    ("districts", "district", "Districts", "DistrictType", "Name"),
    ("buildings", "building", "Buildings", "BuildingType", "Name"),
    ("units", "unit", "Units", "UnitType", "Name"),
    ("technologies", "technology", "Technologies", "TechnologyType", "Name"),
    ("civics", "civic", "Civics", "CivicType", "Name"),
]

YIELD_TABLES = [
    ("terrain", "Terrain_YieldChanges", "TerrainType"),
    ("feature", "Feature_YieldChanges", "FeatureType"),
    ("resource", "Resource_YieldChanges", "ResourceType"),
    ("improvement", "Improvement_YieldChanges", "ImprovementType"),
    ("building", "Building_YieldChanges", "BuildingType"),
]


def _table_exists(con, name: str) -> bool:
    return con.execute(
        "select 1 from sqlite_master where type='table' and name=?", (name,)
    ).fetchone() is not None


def _cols(con, name: str):
    return [r[1] for r in con.execute("PRAGMA table_info([%s])" % name)]


def load_loc(path: Path) -> dict:
    """Return ``{(locale, tag): text}`` and the set of locales."""
    con = sqlite3.connect(str(path))
    out: dict = {}
    locales = set()
    for lang, tag, text in con.execute(
        "select Language, Tag, Text from LocalizedText"
    ):
        locales.add(lang)
        out[(lang, tag)] = text
    con.close()
    return out, locales


def load_loc_snapshot(path: Path | None) -> dict:
    """``{(locale, tag): text}`` from ``data/vanilla/loc.json`` (XML-derived).

    v0.28.2: the game's ``DebugLocalization.sqlite`` cache is **incomplete** — it
    can be missing rows for content the current MOD set enables (measured:
    ``LOC_BELIEF_HOLY_WATERS_NAME`` / 神圣水域 is absent from the cache while the
    game itself shows it fine).  ``tools/build_loc.py`` harvests those tags from
    the game's own ``Text`` XML (base > DLC > enabled MODs), so its snapshot is
    merged on top of the cache — the XML wins for every tag it carries.
    """
    if path is None:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict = {}
    for section in ("names", "city", "civ"):
        for tag, rec in (doc.get(section) or {}).items():
            rec = rec or {}
            zh, en = rec.get("zh") or "", rec.get("en") or ""
            if zh:
                out[("zh_Hans_CN", tag)] = zh
            if en:
                out[("en_US", tag)] = en
    return out


def pick(loc, tag, *langs, fallback=None):
    for lang in langs:
        val = loc.get((lang, tag))
        if val:
            return val
    return fallback


def build(gameplay: Path, localization: Path, out_dir: Path, profile: str,
          loc_json: Path | None = None) -> dict:
    if not gameplay.exists():
        raise SystemExit(
            f"未找到 {gameplay}\n请先启动一次文明6以生成 DebugGameplay.sqlite，"
            "或用 --cache-dir 指定缓存目录。"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_db = out_dir / "gamedb.sqlite"
    # v0.28.2: 复盘工具正开着时它持有这个 sqlite 的句柄，Windows 下删不掉 —— 那就
    # 先写到一个临时文件，最后用 SQLite 的 backup API 把内容灌回原文件（原地更新，
    # 不需要关掉工具；不过工具的 gamedb 是启动时读进内存的，界面要等重启才刷新）。
    locked = False
    if out_db.exists():
        try:
            out_db.unlink()
        except PermissionError:
            locked = True
    target_db = (out_dir / "gamedb.sqlite.new") if locked else out_db
    if target_db.exists():
        target_db.unlink()

    g = sqlite3.connect(str(gameplay))
    g.row_factory = sqlite3.Row
    loc, locales = load_loc(localization)
    # XML-derived names win over the cache (see ``load_loc_snapshot``): the game's
    # DebugLocalization.sqlite misses rows for MOD / DLC content it still renders.
    loc_xml = load_loc_snapshot(loc_json)
    loc.update(loc_xml)
    locales |= {"zh_Hans_CN", "en_US"}

    # --- Types -------------------------------------------------------------
    type_rows = list(g.execute("select Type, Hash, Kind from Types"))
    hash_of = {}
    kind_of = {}
    for r in type_rows:
        h = r["Hash"] & 0xFFFFFFFF
        hash_of[r["Type"]] = h
        kind_of[r["Type"]] = r["Kind"]

    # icon category = first lowercase token of the type string
    def category(typ: str) -> str:
        return typ.split("_", 1)[0].lower()

    # --- names -------------------------------------------------------------
    names = {}
    for typ, h in hash_of.items():
        # ``LOC_<TYPE>_NAME`` is the canonical tag; DLC city-states (Ayutthaya,
        # Antioch, Babylon, Palenque, ...) only carry a ``_FRONTEND_NAME`` entry.
        for suffix in ("_NAME", "_FRONTEND_NAME"):
            tag = "LOC_" + typ + suffix
            zh = loc.get(("zh_Hans_CN", tag))
            en = loc.get(("en_US", tag))
            if zh or en:
                names[h] = (en or "", zh or "")
                break

    # --- continents (v0.25 文档 C follow-up) -------------------------------
    # ``tiles.continent`` is crc32 of a ``CONTINENT_*`` gameplay type; the display
    # name hangs off ``LOC_<TYPE>_DESCRIPTION`` (there is no ``_NAME`` tag), e.g.
    # CONTINENT_LAURENTIA -> LOC_CONTINENT_LAURENTIA_DESCRIPTION = 劳伦古陆.
    ncont = 0
    if _table_exists(g, "Continents"):
        for (typ,) in g.execute("select ContinentType from Continents"):
            h = hash_of.get(typ)
            if h is None or h in names:
                continue
            tag = "LOC_" + typ + "_DESCRIPTION"
            zh = loc.get(("zh_Hans_CN", tag))
            en = loc.get(("en_US", tag))
            if zh or en:
                names[h] = (en or "", zh or "")
                ncont += 1

    # --- output ------------------------------------------------------------
    out = sqlite3.connect(str(target_db))
    out.execute("create table types(hash integer primary key, type text, kind text, category text, icon_path text)")
    out.execute("create table names(hash integer primary key, en text, zh text)")
    for key, _cat, _tbl, _tc, _nc in ENTITIES:
        out.execute(f"create table {key}(hash integer primary key, type text, name_key text)")
    out.execute("create table yield_changes(category text, hash integer, yield_hash integer, amount integer)")
    out.execute("create table prereqs(kind text, hash integer, prereq_hash integer)")
    out.execute("create table replaces(kind text, hash integer, base_hash integer)")
    out.execute("create table building_district(building_hash integer primary key, district_hash integer)")

    # types table: all entities (so the front-end can resolve any hash)
    seen = set()
    for typ, h in hash_of.items():
        out.execute(
            "insert or replace into types(hash, type, kind, category, icon_path) values(?,?,?,?,?)",
            (h, typ, kind_of.get(typ), category(typ), None),
        )
        seen.add(h)
    for h, (en, zh) in names.items():
        out.execute("insert or replace into names(hash, en, zh) values(?,?,?)", (h, en, zh))

    counts = {}
    counts["continents"] = ncont
    for key, cat, tbl, tcol, ncol in ENTITIES:
        if not _table_exists(g, tbl):
            continue
        cols = _cols(g, tbl)
        # extra columns: (snapshot column, snapshot type, source column in the
        # game DB).  Source columns keep their real (PascalCase) names.
        extra = []
        if key == "districts":
            extra = [("cost", "integer", "Cost")]
        if key == "buildings":
            extra = [("cost", "integer", "Cost"), ("is_wonder", "integer", "IsWonder"),
                     # v0.26: city-wall cap (``Buildings.OuterDefenseHitPoints``);
                     # ``wall_order`` is filled in below from the cost order.
                     ("outer_defense_hp", "integer", "OuterDefenseHitPoints")]
        if key == "units":
            extra = [("combat", "integer", "Combat"),
                     ("ranged", "integer", "RangedCombat"),
                     ("range", "integer", "Range"),
                     ("moves", "integer", "BaseMoves"),
                     ("domain", "text", "Domain"),
                     ("formation_class", "text", "FormationClass"),
                     ("make_trade_route", "integer", "MakeTradeRoute"),
                     ("religious_strength", "integer", "ReligiousStrength")]
        if key in ("technologies", "civics"):
            extra = [("cost", "integer", "Cost"), ("era", "text", "EraType")]
        if key == "terrains":
            extra = [("water", "integer", "Water"), ("hills", "integer", "Hills"),
                     ("mountain", "integer", "Mountain"), ("appeal", "integer", "Appeal")]
        if key == "features":
            extra = [("natural_wonder", "integer", "NaturalWonder"),
                     ("appeal", "integer", "Appeal")]
        if key == "resources":
            extra = [("class", "text", "ResourceClassType")]
        for cname, ctype, _src in extra:
            out.execute(f"alter table {key} add column {cname} {ctype}")

        sel = [tcol, ncol] + [src for _n, _t, src in extra if src in cols]
        n = 0
        for row in g.execute("select %s from [%s]" % (", ".join(sel), tbl)):
            typ = row[0]
            if typ is None:
                continue
            h = hash_of.get(typ)
            if h is None:
                continue
            # build insert dynamically
            cols_ins = ["hash", "type", "name_key"] + [n for n, _t, _s in extra]
            rowvals = [h, typ, row[1]]
            for _n, _t, src in extra:
                rowvals.append(row[sel.index(src)] if src in cols else None)
            out.execute(
                "insert or replace into %s(%s) values(%s)" % (
                    key, ",".join(cols_ins), ",".join("?" * len(cols_ins))),
                rowvals,
            )
            n += 1
        counts[key] = n

    # yield changes
    nyc = 0
    for cat, tbl, tcol in YIELD_TABLES:
        if not _table_exists(g, tbl):
            continue
        for typ, ytype, amount in g.execute(
            "select %s, YieldType, YieldChange from [%s]" % (tcol, tbl)
        ):
            h = hash_of.get(typ)
            yh = hash_of.get(ytype) or _crc32_type(ytype)
            if h is None:
                continue
            out.execute("insert into yield_changes values(?,?,?,?)", (cat, h, yh & 0xFFFFFFFF, amount))
            nyc += 1
    counts["yield_changes"] = nyc

    # prereqs
    npq = 0
    if _table_exists(g, "TechnologyPrereqs"):
        for t, p in g.execute("select Technology, PrereqTech from TechnologyPrereqs"):
            out.execute("insert into prereqs values('technology',?,?)", (hash_of.get(t), hash_of.get(p)))
            npq += 1
    if _table_exists(g, "CivicPrereqs"):
        for t, p in g.execute("select Civic, PrereqCivic from CivicPrereqs"):
            out.execute("insert into prereqs values('civic',?,?)", (hash_of.get(t), hash_of.get(p)))
            npq += 1
    counts["prereqs"] = npq

    # unique-district / building / governor replacements (UD -> base type)
    nrep = 0
    for src_tbl, ucol_opt, bcol_opt, kind in (
            ("DistrictReplaces", ("CivUniqueDistrictType", "DistrictType"),
             ("ReplacesDistrictType", "ReplacesDistrict"), "district"),
            ("BuildingReplaces", ("CivUniqueBuildingType", "BuildingType"),
             ("ReplacesBuildingType", "ReplacesBuilding"), "building"),
            ("GovernorReplaces", ("UniqueGovernorType", "GovernorType"),
             ("ReplacesGovernorType", "ReplacesGovernor"), "governor")):
        if not _table_exists(g, src_tbl):
            continue
        cols = _cols(g, src_tbl)
        ucol = next((c for c in ucol_opt if c in cols), None)
        bcol = next((c for c in bcol_opt if c in cols), None)
        if not ucol or not bcol:
            continue
        for u, b in g.execute("select %s, %s from [%s]" % (ucol, bcol, src_tbl)):
            h = hash_of.get(u)
            bh = hash_of.get(b)
            if h is None or bh is None:
                continue
            out.execute("insert into replaces values(?,?,?)", (kind, h, bh))
            nrep += 1
    counts["replaces"] = nrep

    # building -> prerequisite district (NULL district = no prerequisite = city center)
    nbd = 0
    if _table_exists(g, "Buildings") and "PrereqDistrict" in _cols(g, "Buildings"):
        for b, d in g.execute("select BuildingType, PrereqDistrict from Buildings"):
            bh = hash_of.get(b)
            if bh is None:
                continue
            dh = hash_of.get(d) if d else None
            out.execute("insert or replace into building_district values(?,?)", (bh, dh))
            nbd += 1
    counts["building_district"] = nbd

    # --- city walls (v0.26) -------------------------------------------------
    # ``outer_defense_hp`` is the wall HP cap.  ``wall_order`` numbers the tiers
    # by cost ascending so "the strongest wall this city built" is decidable from
    # the hash alone - a MOD (BBG) may give every tier the same HP (75), which
    # would otherwise make the tiers indistinguishable.
    nwalls = 0
    if _table_exists(g, "Buildings") and "outer_defense_hp" in _cols(out, "buildings"):
        out.execute("alter table buildings add column wall_order integer")
        for order, (h,) in enumerate(out.execute(
                "select hash from buildings where outer_defense_hp > 0 "
                "order by cost, hash")):
            out.execute("update buildings set wall_order=? where hash=?", (order, h))
            nwalls += 1
    counts["walls"] = nwalls

    # --- params (v0.26) -----------------------------------------------------
    # Two values that cannot be derived from a TYPE table: the urban-defence cap
    # granted by 钢铁 (``ModifierArguments`` of
    # ``STEEL_UNLOCK_URBAN_DEFENSES`` -> 400 vanilla / 300 BBG) and the hash of
    # ``TECH_STEEL`` itself (the turn payload only carries hashes).
    params = {}
    if steel_tech := hash_of.get("TECH_STEEL"):
        params["steel_tech_hash"] = steel_tech & 0xFFFFFFFF
    if _table_exists(g, "ModifierArguments"):
        cols = _cols(g, "ModifierArguments")
        id_col = next((c for c in ("ModifierId", "ModifierType") if c in cols), None)
        name_col = "Name" if "Name" in cols else None
        val_col = "Value" if "Value" in cols else None
        if id_col and name_col and val_col:
            row = g.execute(
                "select [%s] from ModifierArguments where [%s]='STEEL_UNLOCK_URBAN_DEFENSES' "
                "and [%s]='DefenseValue'" % (val_col, id_col, name_col)
            ).fetchone()
            if row and row[0] is not None:
                try:
                    params["steel_urban_defense"] = int(str(row[0]).strip())
                except ValueError:
                    pass
    out.execute("create table params(name text primary key, value)")
    for name, value in sorted(params.items()):
        out.execute("insert or replace into params(name, value) values(?,?)", (name, value))
    counts["params"] = len(params)

    out.commit()
    out.execute("vacuum")
    out.close()
    g.close()

    if locked:
        # the tool is running and holds ``gamedb.sqlite``: copy the fresh snapshot
        # over it in place (the running process keeps its in-memory copy until the
        # next start, but the artifact on disk is correct).
        src = sqlite3.connect(str(target_db))
        live = sqlite3.connect(str(out_db))
        with live:
            src.backup(live)
        live.close()
        src.close()
        target_db.unlink()

    manifest = {
        "profile": profile,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "source_gameplay": str(gameplay),
        "source_localization": str(localization),
        # v0.28.2: how many name rows came from the XML snapshot instead of the
        # (incomplete) ``DebugLocalization.sqlite`` cache.
        "source_loc_json": str(loc_json) if loc_json is not None else None,
        "xml_name_rows": len(loc_xml),
        "updated_in_place": locked,
        "locales": sorted(locales),
        "counts": counts,
        "types": len(seen),
    }
    manifest_dir = DEV / "gamedb" / profile if out_dir.resolve().is_relative_to(ROOT / "data") else out_dir
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="vanilla")
    ap.add_argument("--cache-dir", default=str(default_cache_dir()))
    ap.add_argument("--loc-json", default=str(ROOT / "data" / "vanilla" / "loc.json"),
                    help="XML-derived name snapshot (build_loc.py);空串 = 不用")
    ap.add_argument("--out", default=str(ROOT / "data" / "gamedb" / "vanilla"))
    args = ap.parse_args(argv)
    cache = Path(args.cache_dir)
    manifest = build(
        cache / "DebugGameplay.sqlite",
        cache / "DebugLocalization.sqlite",
        Path(args.out),
        args.profile,
        Path(args.loc_json) if args.loc_json else None,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
