"""Build offline English display catalogs without changing gameplay snapshots.

Replays each captured text source in its recorded order. Unavailable or changed
sources fail the export rather than borrowing text from another mod version.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import html
import json
from pathlib import Path
import re

from build_loc import default_game_dir, _harvest, _iter_base_text, _iter_dlc_text
from build_rule_text import apply_text, text_db
from localization_sources import apply_profile_text, finish_labels

ROOT = Path(__file__).resolve().parents[1]


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve(labels, tag, lang):
    value = labels.get(tag, {}).get(lang, "") or ""
    for _ in range(12):
        updated = re.sub(r"\{(LOC_[A-Za-z0-9_]+)\}",
                         lambda m: labels.get(m[1], {}).get(lang) or m[0], value)
        if updated == value:
            break
        value = updated
    return "" if value.startswith("LOC_") or "{LOC_" in value else html.unescape(value).strip()


def build(game):
    official = {}
    for file in [*_iter_base_text(game), *_iter_dlc_text(game)]:
        _harvest(official, file, overwrite=False)
    # Only compact game names and display tags; never bundle pedia paragraphs.
    common = {tag: pair for tag, pair in official.items()
              if tag.startswith(("LOC_MAP_", "LOC_MAPSIZE_", "LOC_GAMESPEED_", "LOC_CONTINENT_"))
              or tag.endswith(("_NAME", "_FRONTEND_NAME"))}
    profiles, missing = {}, []
    for profile in ("vanilla", "bbg", "ccb"):
        path = ROOT / f"data/gamedb/{profile}/rule-text.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        with closing(text_db()) as db:
            changes = {"zh": set(), "en": set()}
            for source in doc.get("sources", []):
                file = Path(source["path"])
                if not file.is_file():
                    raise ValueError(f"Captured text source unavailable: {file}")
                if hashlib.sha256(file.read_bytes()).hexdigest() != source["sha256"]:
                    raise ValueError(f"Captured text source changed: {file}")
                apply_profile_text(db, file, apply_text,
                                   is_mod="workshop" in file.parts or "scripts" in file.parts,
                                   changes=changes)
            labels, untranslated_mod_tags = finish_labels(db, changes)
        needed = set()
        for row in doc["entries"].values():
            en = row.setdefault("en", {})
            for field, tag_key in (("name", "nameTag"), ("description", "descriptionTag")):
                tag = row.get(tag_key) or ""
                if field == "name":
                    needed.add(tag)
                # Preserve captured English when text came from a cache-only row.
                en[field] = "" if tag in untranslated_mod_tags else (resolve(labels, tag, "en") or en.get(field) or "")
                if row.get("zh", {}).get(field) and not en[field] and not row.get("internalOnly"):
                    missing.append({"profile": profile, "type": row["type"], "field": field,
                                    "tag": tag, "original": row["zh"][field],
                                    "reason": "No English in captured ruleset text sources"})
        for name in ("tileyields", "adjacency"):
            file = ROOT / f"data/gamedb/{profile}/{name}.json"
            if file.exists():
                rules = json.loads(file.read_text(encoding="utf-8"))
                needed.update(rules.get("nameKeys", {}).values())
        # Profile labels win; common names only fill labels the profile did not
        # change. Never fill a mod's missing English with vanilla English.
        selected = {}
        for tag in sorted(needed - {""}):
            pair = labels.get(tag)
            if pair:
                selected[tag] = {lang: resolve(labels, tag, lang) for lang in ("zh", "en")}
            elif tag in common:
                selected[tag] = common[tag]
        profiles[profile] = selected
        write(path, doc)
        by_tag = {item["tag"] for item in missing if item["profile"] == profile and item["field"] == "name"}
        for tag, pair in selected.items():
            if pair.get("zh") and not pair.get("en") and tag not in by_tag:
                missing.append({"profile": profile, "type": "", "field": "sourceName", "tag": tag,
                                "original": pair["zh"], "reason": "No English in selected source-name text"})
        identities = json.loads((ROOT / "data/shared/identities.json").read_text(encoding="utf-8"))
        known = {item["type"] for item in missing if item["profile"] == profile and item["field"] == "name"}
        for identity in identities["entries"]:
            variant = identity.get("profiles", {}).get(profile, {})
            row = next((row for row in doc["entries"].values() if row["type"] == identity["type"]), {})
            if (variant.get("zh") and not variant.get("en") and identity["type"] not in known
                    and not row.get("en", {}).get("name")):
                missing.append({"profile": profile, "type": identity["type"], "field": "identityName",
                                "tag": row.get("nameTag", ""), "original": variant["zh"],
                                "reason": "Profile identity override has no English"})
    catalog = {"format": 1, "official": common, "profiles": profiles}
    write(ROOT / "data/ui/game-text.json", catalog)
    write(ROOT / "data/ui/missing-english.json", missing)
    ui = json.loads((ROOT / "data/ui/strings.json").read_text(encoding="utf-8"))
    icons_source = (ROOT / "web/js/rule-text-icons.js").read_text(encoding="utf-8")
    icons = json.loads(icons_source[icons_source.index("{"):icons_source.rindex("}") + 1])
    for icon in icons.values():
        label = icon["label"]
        if label not in ui:
            pair = next((p for p in official.values() if p.get("zh") == label and p.get("en")), None)
            if pair:
                ui[label] = pair["en"]
    # The game's own terms replace matching UI terminology where unambiguous.
    tags = {"文化胜利": "LOC_VICTORY_CULTURE_NAME", "食物": "LOC_YIELD_FOOD_NAME",
            "产能": "LOC_YIELD_PRODUCTION_NAME", "科技": "LOC_YIELD_SCIENCE_NAME",
            "文化": "LOC_YIELD_CULTURE_NAME", "金币": "LOC_YIELD_GOLD_NAME",
            "信仰": "LOC_YIELD_FAITH_NAME", "旅游业绩": "LOC_TOURISM_NAME",
            "市中心": "LOC_DISTRICT_CITY_CENTER_NAME", "万神殿": "LOC_PANTHEON_NAME"}
    provenance = {}
    for zh, tag in tags.items():
        text = official.get(tag, {}).get("en")
        if text:
            ui[zh] = text
            provenance[zh] = tag
    for zh, tag in (("黑暗时代", "LOC_ERA_DARK_AGE"), ("黄金时代", "LOC_ERA_GOLDEN_AGE")):
        if official.get(tag, {}).get("en"):
            ui[zh] = official[tag]["en"]
            provenance[zh] = tag
    (ROOT / "web/js/ui-text.js").write_text(
        "/* Generated by tools/build_web_localization.py. */\nwindow.Civ6UIStrings = " +
        json.dumps(ui, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    write(ROOT / "data/ui/game-ui-sources.json", provenance)
    review = ROOT / "data/ui/translation-review.md"
    review.parent.mkdir(parents=True, exist_ok=True)
    counts = {profile: sum(item["profile"] == profile for item in missing) for profile in profiles}
    review.write_text("""# 英文翻译待核对清单

已确认：TYPE标签 → TYPE；探索栏 → Map Tools；数据栏 → Statistics；左右联通 → Wraparound。

以下是项目自有 UI 的暂定译法，不是游戏原文：

| 中文 | 暂定英文 | 界面 | 待核对原因 |
|---|---|---|---|
| 楼层 | Player Order | 文明排序 | 实际含义是存档中的玩家顺序，并非楼层。 |
| 格子面板 | Tile Details | 布局菜单 | 采用详情名称，与中文“面板”称呼略有不同。 |
| 已计算产出 | Calculated Yields | 地块产出 | 是当前能够计算的部分，不表示所有条件已覆盖。 |
| 部分解析层不可用（已降级） | Some save data could not be read | 提示栏 | 用可读描述替代解析层术语。 |
| 解析降级 | Save Data Warnings | 探索栏 | 改为说明实际用途的标题。 |
| 金币流水（打钱 / 吸钱 / 净金币交易） | Gold Transfers (sent / received / net) | 金币详情 | “打钱 / 吸钱”采用支付和收取的方向来表达。 |
| 预计相邻 | Estimated Adjacency | 未建成区域详情 | 指完成后的预期基础相邻加成。 |

游戏与模组文本优先使用实际文本来源；中文改写而未提供配套英文的模组效果保留中文，避免展示原版的不同效果。

## 缺失英文的游戏与模组文本

完整机器可读清单位于 [missing-english.json](missing-english.json)，包含规则集、TYPE、本地化标签、字段、原文和原因。
清单同时包含名称、说明、产出来源名称和身份覆盖；同一实体可能出现多个字段，数量不代表可见条目数量。

""" + "\n".join(f"- {profile}: {count} 个缺失字段" for profile, count in counts.items()) + "\n",
                      encoding="utf-8")
    return {"missingEnglishFields": len(missing), "uiStrings": len(ui),
            "profileLabels": {k: len(v) for k, v in profiles.items()}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, default=default_game_dir())
    print(json.dumps(build(parser.parse_args().game_dir)))
