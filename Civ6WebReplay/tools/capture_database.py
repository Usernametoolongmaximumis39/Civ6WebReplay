"""BBG / CCB capture and restore; the BAT is the deliberately separate UI."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from civ6replay import container, header
from civ6replay.binary import ParseError
from civ6replay.adjacency import AdjacencyRules, _official_package
from civ6replay.database_maintenance import (check_profile, create_backup, data_lock,
    delete_backup, list_backups, recover, replace_data, restore, write_json)
from civ6replay.database_versions import (CORE_IDS, EXPANSION_IDS, clean_title,
    component_role, component_versions, format_versions)
from civ6replay.mods import blacklisted_mods, parse_mod_packages
from civ6replay.modes import parse_game_modes
from civ6replay.tileyields import YieldRules
from civ6replay.unsupported import verdict
from build_adjacency import build as build_adjacency, official_titles
from build_loc import default_game_dir, WORKSHOP_ROOTS
from build_tileyields import build as build_tileyields, validate_profile
from build_rule_text import build as build_rule_text

# Known companions, stable package IDs rather than arbitrary BBG/CCB prefixes.
COMPANIONS = {
    "bbg": {"c88cba8b-8311-4d35-90c3-51a4a5d66542", "619ac86e-d99d-4bf3-b8f0-8c5b8c402567"},
    "ccb": {"8af4fe8e-5406-7d72-d9d6-a8f5d1b66e10", "8af4fe8e-5406-7d72-d9d6-a8f5d1b66e20",
            "8af4fe8e-5406-7d72-d9d6-a8f5d1b66e66"},
}
SINGLE_PLAYER_VALUE = -379035929  # Observed CIV6 single-player game-type marker.


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def signature(path):
    st = path.stat()
    return st.st_mtime_ns, st.st_size


def database_signature(path):
    wal = path.with_name(path.name + "-wal")
    return signature(path), signature(wal) if wal.exists() else None


def source_roots(game_root, extra=()):
    if extra:
        return list(dict.fromkeys(Path(p).resolve() for p in extra if Path(p).is_dir()))
    roots = list(WORKSHOP_ROOTS)
    roots += [Path.home() / "Documents/My Games/Sid Meier's Civilization VI/Mods",
              Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Firaxis Games/Sid Meier's Civilization VI/Mods"]
    # Also handle Steam libraries outside the old hardcoded drive list.
    roots.append(game_root.parent.parent / "workshop/content/289070")
    for steam in (Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Steam",
                  Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Steam"):
        vdf = steam / "steamapps/libraryfolders.vdf"
        if vdf.exists():
            for folder in re.findall(r'"path"\s+"([^\"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
                roots.append(Path(folder.replace("\\\\", "\\")) / "steamapps/workshop/content/289070")
    return list(dict.fromkeys(p.resolve() for p in roots if p.is_dir()))


def resolve_sources(packages, localization, roots):
    with closing(sqlite3.connect(localization.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        labels = {}
        for tag, text in con.execute("select Tag,Text from LocalizedText where Language in ('zh_Hans_CN','en_US')"):
            labels.setdefault(tag, set()).add(clean_title(text))
    wanted = {clean_title(p[k]) for p in packages for k in ("key", "name")}
    found = {}
    for root in roots:
        for info in sorted(root.rglob("*.modinfo")):
            try:
                doc = ET.parse(info).getroot()
            except (ET.ParseError, OSError):
                continue
            title = doc.findtext("Properties/Name", "")
            aliases = {clean_title(title), *labels.get(title, set())}
            if not wanted.intersection(aliases):
                continue
            identity = (doc.get("id") or "").lower()
            if not identity or (identity in found and found[identity][0] != info):
                raise ValueError(f"无法唯一确认 MOD 来源：{title}")
            found[identity] = (info, doc, aliases)
    return found


def validate_packages(profile, packages, titles, found):
    from types import SimpleNamespace
    official = SimpleNamespace(official_titles=set(titles))
    names = [clean_title(p[k]) for p in packages for k in ("key", "name")]
    blocked = blacklisted_mods(names)
    if blocked:
        raise ValueError("加载了不支持的 MOD：" + "、".join(blocked))
    cores = {p for p in ("bbg", "ccb") if any(component_role(row, p) == "core" for row in packages)}
    if len(cores) > 1 or cores != {profile}:
        raise ValueError("BBG 与 CCB 混装，或当前存档与所选规则集不符")
    allowed = {CORE_IDS[profile], EXPANSION_IDS[profile], *COMPANIONS[profile]}
    selected = {}
    for package in packages:
        if _official_package(package["key"], official) or _official_package(package["name"], official):
            continue
        aliases = {clean_title(package["key"]), clean_title(package["name"])}
        matches = [(identity, value) for identity, value in found.items() if aliases.intersection(value[2])]
        if len(matches) != 1 or matches[0][0] not in allowed:
            raise ValueError("加载了未识别或不支持的 MOD：" + package["name"])
        selected[matches[0][0]] = matches[0][1]
    if CORE_IDS[profile] not in selected:
        raise ValueError("无法确认已启用核心 MOD 的版本来源")
    # Known selected companions must not quietly omit their required core/extension.
    for value in selected.values():
        for entry in value[1].findall("Dependencies/Mod"):
            dependency = (entry.get("id") or "").lower()
            if dependency in allowed and dependency not in selected:
                raise ValueError("缺少 MOD 必要依赖：" + dependency)
    return selected


def snapshot(source, output):
    before = database_signature(source)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        with closing(sqlite3.connect(output)) as target:
            con.backup(target)
            if target.execute("pragma integrity_check").fetchone()[0] != "ok":
                raise ValueError("游戏数据库完整性校验失败")
    if database_signature(source) != before:
        raise ValueError("游戏数据库在采集期间发生变化，请重新保存后重试")
    # Existing exporters check freshness against the original generation time.
    os.utime(output, ns=(before[0][0], before[0][0]))


def governor_section(gameplay, localization, profile):
    with closing(sqlite3.connect(localization.resolve().as_uri() + "?mode=ro", uri=True)) as loc:
        labels = {(tag, lang): text for tag, lang, text in loc.execute("select Tag,Language,Text from LocalizedText")}
    with closing(sqlite3.connect(gameplay.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        governors = []
        for row in con.execute("select * from Governors order by rowid"):
            entries = []
            for p in con.execute("select p.* from GovernorPromotionSets s join GovernorPromotions p "
                                 "on p.GovernorPromotionType=s.GovernorPromotion where s.GovernorType=? order by s.rowid",
                                 (row["GovernorType"],)):
                entries.append({"type": p["GovernorPromotionType"], "name_zh": labels.get((p["Name"], "zh_Hans_CN"), ""),
                                "name_en": labels.get((p["Name"], "en_US"), ""), "level": p["Level"],
                                "column": p["Column"], "base_ability": bool(p["BaseAbility"])})
            governors.append({"type": row["GovernorType"], "name_zh": labels.get((row["Name"], "zh_Hans_CN"), ""),
                              "name_en": labels.get((row["Name"], "en_US"), ""), "promotions": entries})
    return {"label": profile.upper(), "built": datetime.now(timezone.utc).isoformat(),
            "verified_in_game": None, "governors": governors, "sources": [{"label": "本局实际生效的游戏数据库与本地化文本"}]}


def capture(profile, save, cache, game_root, *, root=ROOT, mod_roots=(), since=None):
    check_profile(profile)
    save, cache, game_root, root = map(Path, (save, cache, game_root, root))
    gameplay, localization = cache / "DebugGameplay.sqlite", cache / "DebugLocalization.sqlite"
    for file in (save, gameplay, localization):
        if not file.is_file():
            raise ValueError(f"找不到文件：{file}")
    observed_save = signature(save)
    observed = {p: database_signature(p) for p in (gameplay, localization)}
    if save.stat().st_mtime < max(gameplay.stat().st_mtime, localization.stat().st_mtime, since or 0):
        raise ValueError("请在当前单人游戏中重新保存一次，再确认采集")
    raw = save.read_bytes()
    packages = parse_mod_packages(raw)
    blocked = blacklisted_mods([p[k] for p in packages for k in ("key", "name")])
    if blocked:
        raise ValueError("加载了不支持的 MOD：" + "、".join(blocked))
    packets = container.parse_all(raw)
    mode = packets[0].get_packet(header.M_MULTIPLAYER)
    if mode is None or mode.value != SINGLE_PLAYER_VALUE or "hotseat" in {p.lower() for p in save.parts}:
        raise ValueError("请使用单人游戏存档采集")
    unsupported = verdict([p["name"] for p in packages], parse_game_modes(packets))
    if unsupported:
        raise ValueError(unsupported["message"])
    titles = official_titles(localization.resolve(), game_root)
    found = resolve_sources(packages, localization, source_roots(game_root, mod_roots))
    selected = validate_packages(profile, packages, titles, found)
    with closing(sqlite3.connect(gameplay.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        tables = {"Adjacency_YieldChanges": [{"ID": r[0]} for r in con.execute("select ID from Adjacency_YieldChanges")]}
    validate_profile(profile, tables, packages)
    # Back up active data before exporting the new snapshot.
    backup = create_backup(profile, root)
    staging_parent = root / "data/.capture-staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging_parent, prefix=profile + "-") as temporary:
        out = Path(temporary)
        snapshot(gameplay, out / "gameplay.sqlite")
        snapshot(localization, out / "localization.sqlite")
        sources, source_hashes = [], {}
        for identity, (info, doc, aliases) in selected.items():
            dest = out / "scripts" / identity
            dest.mkdir(parents=True)
            shutil.copyfile(info, dest / info.name)
            source_hashes[info] = hashlib.sha256(info.read_bytes()).hexdigest()
            scripts = []
            for entry in doc.findall("InGameActions/AddGameplayScripts/File"):
                relative = Path(entry.text or "")
                file = info.parent / relative
                if relative.is_absolute() or not file.resolve().is_relative_to(info.parent.resolve()) or not file.is_file():
                    raise ValueError("MOD 脚本缺失或路径无效：" + str(relative))
                target = dest / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                source_hashes[file] = digest
                scripts.append({"path": relative.as_posix(), "sha256": digest})
            name = next((p["name"] for p in packages if clean_title(p["key"]) in aliases or clean_title(p["name"]) in aliases),
                        doc.findtext("Properties/Name", ""))
            sources.append({"id": identity, "name": name, "version": doc.findtext("Properties/Version") or doc.get("version"),
                            "modinfoSha256": source_hashes[info], "scripts": scripts})
        build_adjacency(out / "gameplay.sqlite", out / "localization.sqlite", game_root, out / "adjacency.json",
                        profile=profile, packages=packages, mod_files=[v[0] for v in selected.values()])
        build_tileyields(out / "gameplay.sqlite", out / "localization.sqlite", game_root, out / "tileyields.json",
                        profile=profile, save=save, sources=sources, mod_files=[v[0] for v in selected.values()])
        AdjacencyRules(read_json(out / "adjacency.json"))
        YieldRules(read_json(out / "tileyields.json"))
        section = governor_section(out / "gameplay.sqlite", out / "localization.sqlite", profile)
        with closing(sqlite3.connect((out / "localization.sqlite").resolve().as_uri() + "?mode=ro", uri=True)) as con:
            labels = {lang: {tag: text for tag, text in con.execute("select Tag,Text from LocalizedText where Language=?", (lang,))}
                      for lang in ("zh_Hans_CN", "en_US")}
        write_json(out / "labels.json", labels)
        text_doc = build_rule_text(
            out / "gameplay.sqlite", game_root, profile=profile, packages=packages,
            mod_files=[v[0] for v in selected.values()], localization=out / "localization.sqlite")
        write_json(out / "rule-text.json", text_doc)
        source_hashes.update({Path(s["path"]): s["sha256"] for s in text_doc["sources"]})
        versions = component_versions(profile, packages, sources)
        manifest = {"format": 1, "profile": profile, "capturedAt": datetime.now(timezone.utc).isoformat(),
                    "packages": packages, "sources": sources, "versions": versions,
                    "referenceSaveSha256": hashlib.sha256(raw).hexdigest(),
                    "files": {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in out.rglob("*") if p.is_file()}}
        write_json(out / "capture.json", manifest)
        if (any(database_signature(p) != stamp for p, stamp in observed.items())
                or signature(save) != observed_save or save.read_bytes() != raw):
            raise ValueError("存档或游戏数据库发生变化，未替换数据，请重新保存后重试")
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != digest for p, digest in source_hashes.items()):
            raise ValueError("MOD 文件在采集期间更新，未替换数据，请重新进入游戏后重试")
        replace_data(profile, out, {"present": True, "section": section}, backup, root)
    return {"profile": profile, "versions": versions, "backup": backup.name}


def _path(prompt, fallback):
    value = input(f"{prompt} [{fallback}]：").strip().strip('"')
    return Path(value) if value else Path(fallback)


def choose_profile():
    profile = ""
    while not profile:
        choice = input("采集哪套数据库？ 1. BBG  2. CCB  0. 退出：").strip()
        if choice == "0":
            return None
        profile = {"1": "bbg", "2": "ccb"}.get(choice, "")
    return profile


def interactive(args, profile):
    backups = list_backups(profile, args.root)
    if backups:
        choice = input("1. 采集新数据  2. 回档  3. 删除历史备份  0. 退出：").strip()
        if choice in ("2", "3"):
            for index, doc in enumerate(backups, 1):
                created = datetime.fromisoformat(doc["createdAt"]).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                print(f"{index}. {created}  {format_versions(doc.get('versions', [])) or '版本未记录'}  [{doc['id']}]")
            value = input("输入备份序号（0 取消）：").strip()
            if value == "0":
                return
            if not value.isdigit() or not 1 <= int(value) <= len(backups):
                raise ValueError("无效的备份序号")
            identity = backups[int(value) - 1]["id"]
            if choice == "3":
                if input("确认删除这份备份？输入 DELETE：").strip() == "DELETE":
                    delete_backup(profile, identity, args.root)
                    print("备份已删除。")
            else:
                restore(profile, identity, args.root)
                print("回档成功，请重新启动复盘工具。")
            return
        if choice == "0":
            return
        if choice != "1":
            raise ValueError("无效选项")
    since = time.time()
    print(f"请先关闭复盘工具。启用纯净的 {profile.upper()} 核心及已识别配套 MOD，开启一把单人游戏。")
    print("禁用额外规则 MOD，不启用秘密结社或垄断玩法。进入游戏后保存一次，保持本局开启。")
    if input("准备好后输入 Y 开始检测（其他输入取消）：").strip().lower() != "y":
        return
    game_root = args.game_root
    if not (game_root / "Base/Assets").is_dir():
        game_root = _path("游戏安装目录", game_root)
    cache = args.cache_dir
    if not (cache / "DebugGameplay.sqlite").is_file():
        cache = _path("游戏缓存目录", cache)
    saves = [p for p in args.save_dir.rglob("*.Civ6Save") if p.stat().st_mtime >= since]
    candidate = max(saves, key=lambda p: p.stat().st_mtime) if saves else None
    if candidate:
        print("检测到新单人存档：" + str(candidate))
        save = _path("回车使用该存档，也可输入其他存档路径", candidate)
    else:
        save = _path("未找到新单人存档，请输入刚保存的存档路径", "")
    result = capture(profile, save, cache, game_root, root=args.root, mod_roots=args.mod_root, since=since)
    print("采集成功：" + format_versions(result["versions"]))
    print("旧数据备份：" + result["backup"] + "；请重新启动复盘工具。")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", nargs="?", default="interactive", choices=("interactive", "capture", "list-backups", "restore", "delete-backup"))
    ap.add_argument("--profile", choices=("bbg", "ccb"))
    ap.add_argument("--save", type=Path)
    ap.add_argument("--backup")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--game-root", type=Path, default=default_game_dir())
    ap.add_argument("--cache-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Firaxis Games/Sid Meier's Civilization VI/Cache")
    ap.add_argument("--save-dir", type=Path, default=Path.home() / "Documents/My Games/Sid Meier's Civilization VI/Saves/Single")
    ap.add_argument("--mod-root", type=Path, action="append", default=[])
    args = ap.parse_args(argv)
    if args.action != "interactive" and not args.profile:
        ap.error("此操作需要 --profile")
    if args.action == "capture" and not args.save:
        ap.error("采集需要 --save")
    if args.action in ("restore", "delete-backup") and not args.backup:
        ap.error("此操作需要 --backup")
    try:
        profile = choose_profile() if args.action == "interactive" else args.profile
        if not profile:
            return 0
        with data_lock(args.root):
            if recover(args.root):
                print("已恢复上次中断前的数据库。")
            if args.action == "interactive":
                interactive(args, profile)
            elif args.action == "capture":
                print(json.dumps(capture(args.profile, args.save, args.cache_dir, args.game_root,
                                         root=args.root, mod_roots=args.mod_root), ensure_ascii=False, indent=2))
            elif args.action == "list-backups":
                print(json.dumps(list_backups(args.profile, args.root), ensure_ascii=False, indent=2))
            elif args.action == "restore":
                restore(args.profile, args.backup, args.root)
                print("回档成功，请重新启动复盘工具。")
            else:
                delete_backup(args.profile, args.backup, args.root)
        return 0
    except (ValueError, OSError, sqlite3.Error, ET.ParseError, ParseError, KeyError) as exc:
        print(f"[错误] {exc}；未完成数据切换。")
        return 1
    except (EOFError, KeyboardInterrupt):
        print("已取消。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
