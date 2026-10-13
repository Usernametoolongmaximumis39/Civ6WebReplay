"""Export offline policy/ability text from one captured ruleset and its sources.

The text export can use an audit-only gameplay snapshot: it never replaces
runtime rules. Only that snapshot's selected packages supply translations.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

from build_loc import WORKSHOP_ROOTS, default_game_dir, _implied_language, _iter_base_text
from audit_mod_additions import read_sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from civ6replay.hash import crc32_type
from civ6replay.database_maintenance import write_json

ENTITIES = (("Policies", "PolicyType", "policy"), ("Traits", "TraitType", "trait"),
            ("UnitAbilities", "UnitAbilityType", "ability"),
            ("UnitPromotions", "UnitPromotionType", "promotion"),
            ("GovernorPromotions", "GovernorPromotionType", "governor_promotion"))


def selected_mods(capture, roots=WORKSHOP_ROOTS):
    expected = {s["id"].lower(): s for s in capture["sources"]}
    found = {}
    for root in roots:
        for path in sorted(Path(root).glob("*/*.modinfo")):
            doc = ET.parse(path).getroot()
            identity = doc.get("id", "").lower()
            if identity not in expected:
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected[identity]["modinfoSha256"]:
                raise ValueError(f"Installed package differs from capture: {path}")
            if identity in found:
                raise ValueError(f"Duplicate selected package: {identity}")
            found[identity] = path
    if expected.keys() - found.keys():
        raise ValueError(f"Missing selected packages: {expected.keys() - found.keys()}")
    return list(found.values())


def text_actions(infos, *, missing=None):
    actions = []
    for info in infos:
        doc = ET.parse(info).getroot()
        for action in doc.findall("InGameActions/UpdateText"):
            for entry in action.findall("File"):
                relative = Path(entry.text or "")
                path = (info.parent / relative).resolve()
                if not path.is_relative_to(info.parent.resolve()):
                    raise ValueError(f"Invalid text source: {path}")
                # Optional game-mode text must not overwrite standard gameplay.
                if "_MODE" in path.stem.upper() or any(part.lower() == "mode" for part in path.parts):
                    continue
                if path.stem.lower() in {"french", "german", "italian", "japanese", "korean",
                                          "polish", "portuguese", "russian", "spanish"}:
                    continue
                if not path.is_file():
                    if missing is None:
                        raise ValueError(f"Missing selected text source: {path}")
                    missing.append(str(path))
                    continue
                actions.append((int(action.findtext("Properties/LoadOrder", "0")), path))
    return [path for _, path in sorted(actions, key=lambda row: row[0])]


def text_db():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE LocalizedText(Language TEXT, Tag TEXT, Text TEXT, Gender TEXT,
            Plurality TEXT, PRIMARY KEY(Language,Tag));
        CREATE TABLE BaseGameText(Tag TEXT PRIMARY KEY, Text TEXT, Gender TEXT, Plurality TEXT);
    """)
    # Source SQL is evaluated only in the isolated localization database.
    db.set_authorizer(lambda op, a, b, *_: sqlite3.SQLITE_DENY
                      if op in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA)
                      or (op == sqlite3.SQLITE_FUNCTION and (b or "").lower() == "load_extension")
                      else sqlite3.SQLITE_OK)
    return db


def apply_text(db, path):
    raw = read_sql(path)
    if path.suffix.lower() == ".sql":
        db.executescript(raw)
        return
    # A few shipped XML comments contain another comment opener.
    raw = re.sub(r"<\?xml.*?\?>|<!--.*?-->", "", raw, flags=re.S)
    if not raw.strip():
        return
    doc = ET.fromstring(raw)
    implied = _implied_language(path)
    for table in doc.iter():
        if table.tag not in ("LocalizedText", "BaseGameText"):
            continue
        fields = {"Tag", "Text", "Gender", "Plurality"}
        if table.tag == "LocalizedText":
            fields.add("Language")
        for row in table:
            if row.tag in ("Row", "Replace"):
                values = {**{c.tag: "".join(c.itertext()) for c in row}, **row.attrib}
                if table.tag == "LocalizedText" and not values.get("Language"):
                    values["Language"] = implied
                values = {k: v for k, v in values.items() if k in fields}
                if not values.get("Tag") or "Text" not in values:
                    continue
                db.execute(f'INSERT OR REPLACE INTO {table.tag} ({",".join(values)}) '
                           f'VALUES ({",".join("?" for _ in values)})', list(values.values()))
            elif row.tag in ("Delete", "Update"):
                where = row.find("Where")
                conditions = dict(where.attrib) if where is not None else dict(row.attrib)
                conditions = {k: v for k, v in conditions.items() if k in fields}
                if not conditions:
                    raise ValueError(f"Unbounded text operation: {path}")
                clause = " AND ".join(k + "=?" for k in conditions)
                if row.tag == "Delete":
                    db.execute(f"DELETE FROM {table.tag} WHERE {clause}", list(conditions.values()))
                else:
                    node = row.find("Set")
                    values = {**node.attrib, **{c.tag: "".join(c.itertext()) for c in node}} if node is not None else {}
                    values = {k: v for k, v in values.items() if k in fields}
                    if values:
                        db.execute(f'UPDATE {table.tag} SET {",".join(k+"=?" for k in values)} '
                                   f'WHERE {clause}', [*values.values(), *conditions.values()])


def build(gameplay, game_root, *, profile, packages=(), mod_files=(), localization=None, official_text_files=None):
    game_root, gameplay = Path(game_root), Path(gameplay)
    titles = {p[k] for p in packages for k in ("key", "name")}
    official = [p for p in sorted((game_root / "DLC").rglob("*.modinfo"))
                if ET.parse(p).getroot().findtext("Properties/Name") in titles]
    unavailable = []
    official_paths = text_actions(official, missing=unavailable) if official_text_files is None else official_text_files
    paths = [*_iter_base_text(game_root), *official_paths, *text_actions(mod_files)]
    # Only policy/ability text and its referenced translations are needed.
    # Selected companion packages also ship unrelated menus, sometimes with
    # invalid SQL; those menus must not prevent a rule-text export.
    with closing(sqlite3.connect(gameplay.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        needed = {tag for table, _, _ in ENTITIES if table in tables
                  for field in ("Name", "Description")
                  if any(r[1] == field for r in db.execute(f"PRAGMA table_info({table})"))
                  for (tag,) in db.execute(f"SELECT {field} FROM {table}") if tag}
    tagged = []
    for path in paths:
        raw = read_sql(path)
        tags = set(re.findall(r"\bLOC_[A-Za-z0-9_]+\b", raw))
        tags.update(tag for tag in needed if not tag.startswith("LOC_") and tag in raw)
        # Dynamic text updates can affect tags without spelling them out.
        dynamic = bool(re.search(r"\b(?:UPDATE|DELETE)\s+(?:LocalizedText|BaseGameText)\b", raw, re.I)
                       or re.search(r"<(?:Update|Delete)\b", raw))
        tagged.append((path, tags, dynamic))
    while True:
        expanded = needed | {tag for _, tags, dynamic in tagged if dynamic or tags & needed for tag in tags}
        if expanded == needed:
            break
        needed = expanded
    unrelated = [str(path) for path, tags, dynamic in tagged if not dynamic and not tags & needed]
    paths = [path for path, tags, dynamic in tagged if dynamic or tags & needed]
    sources = []
    with closing(text_db()) as text:
        if localization and Path(localization).is_file():
            with closing(sqlite3.connect(Path(localization).resolve().as_uri() + "?mode=ro", uri=True)) as loc:
                text.executemany("INSERT OR REPLACE INTO LocalizedText(Language,Tag,Text) VALUES (?,?,?)",
                                 loc.execute("SELECT Language,Tag,Text FROM LocalizedText"))
        for path in paths:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            try:
                apply_text(text, path)
            except (sqlite3.Error, ET.ParseError) as exc:
                raise ValueError(f"Cannot read selected text source {path}: {exc}") from exc
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Text source changed during export: {path}")
            sources.append({"path": str(path), "sha256": digest})
        labels = {}
        for tag, value in text.execute("SELECT Tag,Text FROM BaseGameText"):
            labels.setdefault(tag, {})["en"] = value
        for lang, tag, value in text.execute("SELECT Language,Tag,Text FROM LocalizedText"):
            key = {"zh_hans_cn": "zh", "zh_hans": "zh", "en_us": "en"}.get((lang or "").lower())
            if key and value:
                labels.setdefault(tag, {})[key] = value
    def localized(tag, lang):
        value = labels.get(tag, {}).get(lang, "")
        for _ in range(12):
            updated = re.sub(r"\{(LOC_[A-Za-z0-9_]+)\}",
                             lambda m: labels.get(m[1], {}).get(lang) or m[0], value)
            if updated == value:
                break
            value = updated
        # Never expose unresolved localization tags as user-facing descriptions.
        return "" if "{LOC_" in value or value.startswith("LOC_") else html.unescape(value).strip()
    entries, civilizations, leaders = {}, {}, {}
    with closing(sqlite3.connect(gameplay.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        content_traits = set()
        for table in ("Units", "Buildings", "Districts", "Improvements"):
            if table in tables and any(r[1] == "TraitType" for r in db.execute(f"PRAGMA table_info({table})")):
                content_traits.update(r[0] for r in db.execute(f"SELECT TraitType FROM {table} WHERE TraitType IS NOT NULL"))
        for table, key, kind in ENTITIES:
            if table not in tables:
                continue
            for r in db.execute(f"SELECT * FROM {table}"):
                row = dict(r)
                typ = row[key]
                entries[str(crc32_type(typ))] = {"type": typ, "kind": kind,
                    "internalOnly": bool(row.get("InternalOnly")),
                    "uniqueContent": kind == "trait" and typ in content_traits,
                    "nameTag": row.get("Name"), "descriptionTag": row.get("Description"),
                    **{lang: {"name": localized(row.get("Name"), lang),
                              "description": localized(row.get("Description"), lang)} for lang in ("zh", "en")}}
        for table, key, dest in (("CivilizationTraits", "CivilizationType", civilizations),
                                 ("LeaderTraits", "LeaderType", leaders)):
            if table in tables:
                for row in db.execute(f"SELECT * FROM {table}"):
                    dest.setdefault(str(crc32_type(row[key])), []).append(str(crc32_type(row["TraitType"])))
        parents = {str(crc32_type(r["LeaderType"])): str(crc32_type(r["InheritFrom"]))
                   for r in db.execute("SELECT * FROM Leaders") if r["InheritFrom"]} if "Leaders" in tables else {}
    counts = {kind: sum(r["kind"] == kind for r in entries.values()) for _, _, kind in ENTITIES}
    missing = [{"type": r["type"], "tag": r["descriptionTag"]} for r in entries.values()
               if r["descriptionTag"] and not (r["zh"]["description"] or r["en"]["description"])]
    if any(hashlib.sha256(Path(s["path"]).read_bytes()).hexdigest() != s["sha256"] for s in sources):
        raise ValueError("Text sources changed during export")
    return {"format": 1, "profile": profile, "builtAt": datetime.now(timezone.utc).isoformat(),
            "gameplaySha256": hashlib.sha256(gameplay.read_bytes()).hexdigest(),
            "packages": list(packages), "sources": sources, "unrelatedTextFiles": unrelated,
            "unavailableOfficialFiles": unavailable, "counts": counts,
            "missingDescriptions": missing, "entries": entries,
            "civilizations": civilizations, "leaders": leaders, "leaderParents": parents}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", choices=("vanilla", "ccb", "bbg"), default="ccb")
    ap.add_argument("--snapshot", type=Path)
    ap.add_argument("--game-dir", type=Path, default=default_game_dir())
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    directory = args.snapshot or ROOT / "data/gamedb" / args.profile
    if args.profile == "vanilla":
        from build_official_rule_text import build_official
        doc = build_official(args.game_dir)
    else:
        capture = json.loads((directory / "capture.json").read_text(encoding="utf-8"))
        if capture["profile"] != args.profile:
            raise ValueError("Snapshot profile mismatch")
        doc = build(directory / "gameplay.sqlite", args.game_dir, profile=args.profile,
                    packages=capture["packages"], mod_files=selected_mods(capture),
                    localization=directory / "localization.sqlite")
    out = args.out or ROOT / "data/gamedb" / args.profile / "rule-text.json"
    write_json(out, doc)
    print(json.dumps({"out": str(out), "counts": doc["counts"], "missingDescriptions": doc["missingDescriptions"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
