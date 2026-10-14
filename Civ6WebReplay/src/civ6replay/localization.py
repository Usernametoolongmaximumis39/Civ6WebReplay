"""Localized response views of shared, language-neutral replay calculations."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4)
def _catalogs(stamps):
    return tuple(json.loads(Path(path).read_text(encoding="utf-8")) for path, _, _ in stamps)


def catalogs():
    paths = [ROOT / "data/ui/strings.json", ROOT / "data/ui/game-text.json"]
    return _catalogs(tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in paths))


def display_token():
    paths = [ROOT / "data/ui/strings.json", ROOT / "data/ui/game-text.json",
             ROOT / "data/vanilla/loc.json", ROOT / "data/vanilla/identities.json",
             ROOT / "data/mods/governor_promotions.json", ROOT / "data/shared/identities.json",
             *sorted((ROOT / "data/gamedb").glob("*/rule-text.json"))]
    return hashlib.sha256("|".join(f"{p}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in paths if p.exists()).encode()).hexdigest()[:16]


def ui(value, lang="zh"):
    """Only call on developer-authored annotations, never custom names/paths."""
    if lang != "en" or not isinstance(value, str):
        return value
    strings = catalogs()[0]
    if value in strings:
        return strings[value]
    for template, translated in strings.items():
        if "%d" not in template and "%s" not in template:
            continue
        pattern = re.escape(template).replace("%d", r"(-?\d+)").replace("%s", r"(.*?)")
        match = re.fullmatch(pattern, value)
        if match:
            parts = iter(match.groups())
            return re.sub(r"%[sd]", lambda _: next(parts), translated)
    # F-string fragments in generated diagnostic annotations.
    pattern = ui_pattern(tuple(strings))
    return pattern.sub(lambda m: strings[m[0]], value)


@lru_cache(maxsize=4)
def ui_pattern(keys):
    return re.compile("|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True)) or r"(?!)")


def game_text(tag, profile="vanilla", lang="zh"):
    from .rule_text import get_rule_text
    current = get_rule_text(profile).labels
    if tag in current:
        pair = current[tag]
        return pair.get(lang) or pair.get("zh") or pair.get("en") or ""
    catalog = catalogs()[1]
    selected = catalog.get("profiles", {}).get(profile, {})
    # A profile's missing translation must not borrow another ruleset's text.
    pair = selected.get(tag) if tag in selected else catalog.get("official", {}).get(tag, {})
    return pair.get(lang) or pair.get("zh") or pair.get("en") or ""


def city_name(raw, fallback, lang):
    if not raw or not raw.startswith("LOC_"):
        return fallback
    from .loc import get_loc
    zh, en = get_loc().city_name(raw)
    return (en or zh or fallback) if lang == "en" else (zh or en or fallback)


def map_name(value, key="", lang="zh"):
    if lang != "en":
        return value
    if key.startswith("LOC_"):
        translated = game_text(key, lang=lang)
        if translated:
            return translated
    for tag, pair in catalogs()[1]["official"].items():
        if tag.startswith("LOC_MAP_") and pair.get("zh") == value and pair.get("en"):
            return pair["en"]
    return value


def localize_replays(records, lang):
    if lang == "zh":
        return records
    return [{**r, "mapName": r.get("mapNameEn") or map_name(r.get("mapName", ""), r.get("mapKey", ""), lang),
             "mapSize": ui(r.get("mapSize", ""), lang),
             "gameSpeed": ui(r.get("gameSpeed", ""), lang)} for r in records]


def localize_static(info, lang):
    if lang == "zh":
        return info
    from .server import _name_of
    from .rule_text import get_rule_text
    from .governors import get_governors
    from .hash import YIELD_NAMES
    profile = info.get("identityProfile", "vanilla")
    out = deepcopy(info)
    out["mapName"] = info.get("mapNameEn") or map_name(info.get("mapName", ""), info.get("mapKey", ""), lang)
    for field in ("mapSize", "gameSpeed"):
        out[field] = ui(info.get(field, ""), lang)
    for player in out.get("players", []):
        for field, type_field in (("civName", "civ"), ("leaderName", "leader")):
            player[field] = _name_of(player[type_field], profile, lang) or player.get(field, "")
        player["typeCivName"] = ui(player.get("typeCivName", ""), lang)
        player["flavour"] = ui(player.get("flavour", ""), lang)
        player["abilities"] = get_rule_text(profile).abilities(player["civ"], player["leader"], lang)
    from .server import ROUTE_TAGS
    out["routeNames"] = {str(index): game_text(tag, profile, lang) or ui(value, lang)
                         for index, tag in ROUTE_TAGS.items()
                         if (value := info.get("routeNames", {}).get(index, info.get("routeNames", {}).get(str(index))))}
    promotions = get_governors().table(info.get("mods", []), lang)
    out["governorPromotions"] = {**out.get("governorPromotions", {}),
                                "names": {str(h): _name_of(h, profile, lang) or name
                                          for h, name in promotions["names"].items()}}
    for h, meta in out.get("yieldMeta", {}).items():
        meta["name"] = ui(meta.get("name", YIELD_NAMES.get(int(h), "")), lang)
    if out.get("unsupported"):
        for field in ("title", "message"):
            out["unsupported"][field] = ui(out["unsupported"].get(field, ""), lang)
        out["unsupported"]["lines"] = [ui(v, lang) for v in out["unsupported"].get("lines", [])]
    return out


def localize_turn(payload, profile, lang):
    if lang == "zh":
        return payload
    from .server import _name_of
    from .tileyields import get_rules
    rules = get_rules(profile)
    # Copy only display-bearing branches; large numeric tile arrays are shared.
    out = {**payload, "players": deepcopy(payload.get("players", [])),
           "tileYields": deepcopy(payload.get("tileYields", {}))}
    for player in out["players"]:
        for city in player.get("cities", []):
            city["name"] = city_name(city.get("nameKey"), city.get("name", ""), lang)
        for district in player.get("districts", []):
            for source in district.get("adjacencySources") or []:
                typ = source.get("labelType")
                if typ and source.get("label", "") != "相邻山脉":
                    from .hash import crc32_type
                    source["label"] = ui("相邻", lang) + _name_of(crc32_type(typ), profile, lang)
                else:
                    source["label"] = ui(source.get("label", ""), lang)
                source["origin"] = ui(source.get("origin", ""), lang)
    def translate_report(node):
        if isinstance(node, list):
            for value in node:
                translate_report(value)
        elif isinstance(node, dict):
            for key in ("source", "note", "reason", "message"):
                if key in node:
                    node[key] = ui(node[key], lang)
            if "missing" in node:
                node["missing"] = [ui(v, lang) for v in node["missing"]]
            typ = node.get("sourceType") or node.get("type")
            if typ and "name" in node and rules:
                tag = rules.name_keys.get(typ)
                node["name"] = game_text(tag, profile, lang) or node["name"]
            for value in node.values():
                if isinstance(value, (dict, list)):
                    translate_report(value)
    translate_report(out["tileYields"])
    return out


def localize_share(view, lang):
    if lang == "zh":
        return view
    out = deepcopy(view)
    for field in ("hint", "note"):
        if field in out:
            out[field] = ui(out[field], lang)
    if isinstance(out.get("reach"), dict):
        for field in ("message", "text", "note", "detail"):
            if field in out["reach"]:
                out["reach"][field] = ui(out["reach"][field], lang)
    # Candidate names include real network adapter names: keep those verbatim.
    for candidate in out.get("candidates", []):
        from .share import label_of
        label = label_of(candidate.get("ip", ""), "", candidate.get("kind", ""), candidate.get("source", "nic"))
        tail = f" ({candidate['name']})" if candidate.get("name") else ""
        candidate["label"] = ui(label, lang) + tail
    return out
