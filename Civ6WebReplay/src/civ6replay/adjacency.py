"""District adjacency evaluated from separate official, CCB and BBG snapshots.

Only adjacency effects are evaluated: policy multipliers, yield copies, ordinary
district/building yields and specialist yields are intentionally outside this
calculation. An unavailable result is None, whereas a computed zero is {}.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import json
import math
import re
from pathlib import Path

from .hash import crc32_type as H, TYPE_CIV_CITY_STATE
from .model import NONE_U32
from .mods import balance_mod
from .gamedb import get_gamedb

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "data" / "gamedb" / "vanilla" / "adjacency.json"
WONDER = H("DISTRICT_WONDER")
CENTER = H("DISTRICT_CITY_CENTER")
EFFECTS = {
    "EFFECT_FEATURE_ADJACENCY": "AdjacentFeature",
    "EFFECT_TERRAIN_ADJACENCY": "AdjacentTerrain",
    "EFFECT_DISTRICT_ADJACENCY": "OtherDistrictAdjacent",
    "EFFECT_RIVER_ADJACENCY": "AdjacentRiver",
    "EFFECT_IMPROVEMENT_ADJACENCY": "AdjacentImprovement",
    "EFFECT_ADJUST_DISTRICT_YIELD_BASED_ON_APPEAL": "appeal",
}
# These existing UI tools do not change gameplay adjacency. Unknown packages
# are deliberately not assumed to use the official rules.
UI_TITLES = {"Multiplayer Toolkits (UI)", "联机工具箱", "顶部面板拓展",
             "Better Spectator Mod", "Better Spectator Mod (BSM)",
             "Advanced Cheat Menu (Light)", "Advanced Cheat Menu (Light) Hotseat patch"}


def _official_package(title, rules):
    title = re.sub(r"\[(?:COLOR[^\]]*|ENDCOLOR)\]", "", str(title)).strip()
    return (title in rules.official_titles or title in UI_TITLES
            or bool(re.fullmatch(r"Better Spectator Mod v[\d.]+", title)))


def _profile_package(package, rules):
    if _official_package(package["key"], rules) or _official_package(package["name"], rules):
        return True
    # Exact captured package/version names; a future CCB title does not silently
    # inherit the current snapshot. Color markup is presentation, not identity.
    clean = lambda s: re.sub(r"\[(?:COLOR[^\]]*|ENDCOLOR)\]", "", s).strip()
    return any(clean(package["key"]) == clean(p["key"]) or
               clean(package["name"]) == clean(p["name"]) for p in rules.packages)


def _index(rows, key):
    return {r[key]: r for r in rows}


def _groups(rows, key, value):
    out = defaultdict(list)
    for row in rows:
        out[row[key]].append(row[value])
    return out


class AdjacencyRules:
    def __init__(self, document):
        if document.get("format") != 1 or document.get("profile") not in ("official", "ccb", "bbg"):
            raise ValueError("unsupported adjacency snapshot")
        # YieldRules inherits the metadata reader with its own profile name.
        if not hasattr(self, "profile"):
            self.profile = document["profile"]
        self.packages = document.get("packages", [])
        self.fingerprint = document["fingerprint"]
        self.official_titles = set(document["officialTitles"])
        t = document["tables"]
        self.types = {H(r["Type"]): r["Type"] for r in t["Types"]}
        self.rules = _index(t["Adjacency_YieldChanges"], "ID")
        self.by_district = _groups(t["District_Adjacencies"], "DistrictType", "YieldChangeId")
        self.replaces = {r["CivUniqueDistrictType"]: r["ReplacesDistrictType"]
                         for r in t["DistrictReplaces"]}
        self.excluded = _groups(t["ExcludedAdjacencies"], "TraitType", "YieldChangeId")
        self.civ_traits = _groups(t["CivilizationTraits"], "CivilizationType", "TraitType")
        self.leader_traits = _groups(t["LeaderTraits"], "LeaderType", "TraitType")
        self.leaders = _index(t["Leaders"], "LeaderType")
        self.trait_mods = _groups(t["TraitModifiers"], "TraitType", "ModifierId")
        self.belief_mods = _groups(t["BeliefModifiers"], "BeliefType", "ModifierID")
        self.building_mods = _groups(t["BuildingModifiers"], "BuildingType", "ModifierId")
        self.district_mods = _groups(t["DistrictModifiers"], "DistrictType", "ModifierId")
        self.governor_mods = _groups(t.get("GovernorModifiers", ()), "GovernorType", "ModifierId")
        self.governor_promotion_mods = _groups(t.get("GovernorPromotionModifiers", ()),
                                             "GovernorPromotionType", "ModifierId")
        self.custom_adjacencies = t.get("Ruivo_New_Adjacency", ())
        self.modifiers = _index(t["Modifiers"], "ModifierId")
        self.dynamic = _index(t["DynamicModifiers"], "ModifierType")
        self.args = defaultdict(dict)
        for row in t["ModifierArguments"]:
            self.args[row["ModifierId"]][row["Name"]] = row["Value"]
        self.requirements = _index(t["Requirements"], "RequirementId")
        self.req_args = defaultdict(dict)
        for row in t["RequirementArguments"]:
            self.req_args[row["RequirementId"]][row["Name"]] = row["Value"]
        self.req_sets = _index(t["RequirementSets"], "RequirementSetId")
        self.req_members = _groups(t["RequirementSetRequirements"], "RequirementSetId", "RequirementId")
        self.features = _index(t["Features"], "FeatureType")
        self.terrains = _index(t["Terrains"], "TerrainType")
        self.resources = _index(t["Resources"], "ResourceType")
        self.buildings = _index(t["Buildings"], "BuildingType")
        self.districts = _index(t["Districts"], "DistrictType")
        self.expansion_key = ("LOC_EXPANSION2_MOD_TITLE" if "DISTRICT_DAM" in self.districts else
                              "LOC_EXPANSION1_MOD_TITLE" if "DISTRICT_GOVERNMENT" in self.districts else None)
        self._modifier_rules = {mid: self._compile(mid) for mid in self.modifiers}

    def _compile(self, mid, visiting=()):
        if mid in visiting:
            return []
        m = self.modifiers.get(mid)
        if not m:
            return []
        dyn = self.dynamic.get(m["ModifierType"], {})
        effect = dyn.get("EffectType")
        args = self.args[mid]
        field = EFFECTS.get(effect)
        if field:
            row = {"ID": mid, "YieldType": args["YieldType"],
                   "YieldChange": int(args.get("Amount", args.get("YieldChange", 0))),
                   "TilesRequired": int(args.get("TilesRequired", 1)),
                   "target": args["DistrictType"], "scope": dyn["CollectionType"],
                   "conditions": [(m.get("OwnerRequirementSetId"), m.get("SubjectRequirementSetId"))]}
            if field == "appeal":
                row["RequiredAppeal"] = int(args["RequiredAppeal"])
            elif field in ("OtherDistrictAdjacent", "AdjacentRiver"):
                row[field] = 1
            else:
                row[field] = args[{"AdjacentFeature": "FeatureType", "AdjacentTerrain": "TerrainType",
                                   "AdjacentImprovement": "ImprovementType"}[field]]
            return [row]
        # Follow only attachment chains that lead to an adjacency effect.
        if "ATTACH_MODIFIER" in (effect or "") and args.get("ModifierId"):
            children = self._compile(args["ModifierId"], (*visiting, mid))
            return [{**r, "conditions": [(m.get("OwnerRequirementSetId"),
                                           m.get("SubjectRequirementSetId")), *r["conditions"]]}
                    for r in children]
        return []

    def traits(self, info):
        civ = self.types.get(info.civ & NONE_U32)
        # The header uses the civ hash as the display/color identity of a city
        # state; its gameplay leader still has the original LEADER_* string.
        leader = info.leaderStr if info.leaderStr in self.leaders else self.types.get(info.leader & NONE_U32)
        minor = (info.typeCiv & NONE_U32) == TYPE_CIV_CITY_STATE
        if (civ not in self.civ_traits and not minor) or leader not in self.leaders:
            return None
        traits = set(self.civ_traits.get(civ, ()))
        seen = set()
        while leader and leader not in seen:
            seen.add(leader)
            traits.update(self.leader_traits.get(leader, ()))
            leader = self.leaders.get(leader, {}).get("InheritFrom")
        return traits

    def matches_district(self, actual, expected):
        return actual == expected or self.replaces.get(actual) == expected


@lru_cache(maxsize=3)
def get_rules(profile="official"):
    if profile not in ("official", "ccb", "bbg"):
        return None
    path = SNAPSHOT if profile == "official" else ROOT / f"data/gamedb/{profile}/adjacency.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("profile") != profile:
            return None
        return AdjacencyRules(document)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def district_hit_points(profile="official"):
    """District HP caps from the selected rules snapshot, including zero-HP districts."""
    rules = get_rules(profile)
    if not rules:
        return {}
    return {str(H(typ)): max(0, int(row["HitPoints"]))
            for typ, row in rules.districts.items() if row.get("HitPoints") is not None}


@lru_cache(maxsize=1)
def _wrap_map():
    try:
        return json.loads((ROOT / "data" / "vanilla" / "mapwrap.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def neighbors(x, y, width, height, wrap_x):
    # Same odd-row coordinates as hexmap.js. Deduplicate on tiny wrapped maps.
    offsets = ((0, -1), (1, 0), (0, 1), (-1, 1), (-1, 0), (-1, -1))
    seen = {y * width + x}
    for dx, dy in offsets:
        nx, ny = x + dx + (int(y % 2 == 1) if dy else 0), y + dy
        if not 0 <= ny < height:
            continue
        if wrap_x:
            nx %= width
        if 0 <= nx < width and ny * width + nx not in seen:
            seen.add(ny * width + nx)
            yield ny * width + nx


class _Turn:
    def __init__(self, state, rules, wrap_x):
        self.state, self.rules, self.wrap_x = state, rules, wrap_x
        self.players = {p.iPlayer: p for p in state.players if p.iPlayer >= 0}
        self.info = {p.iPlayer: p for p in state.playersInfo}
        self.cities = {(p.iPlayer, c.id): c for p in self.players.values() for c in p.cities}
        self.religions = {r.iSymbol & NONE_U32: r for r in state.religions}
        self.built_districts = {}
        self.wonders = set()
        self.player_buildings = defaultdict(list)
        for p in self.players.values():
            for d in p.districts:
                if d.built and (d.type & NONE_U32) != WONDER and self.valid(d.x, d.y):
                    self.built_districts[d.y * state.width + d.x] = self.name(d.type)
            for c in p.cities:
                for bh, tile in c.built.items():
                    tile = int(tile) & 0xFFFF
                    if tile == 0xFFFF or not 0 <= tile < len(state.tiles):
                        continue
                    bt = self.name(bh)
                    if rules.buildings.get(bt, {}).get("IsWonder"):
                        self.wonders.add(tile)
                    if not c.pillagedBuildings.get(bh):
                        self.player_buildings[p.iPlayer].append((c.id, bt))
        self.traits = {pid: rules.traits(self.info[pid]) if pid in self.info else None
                       for pid in self.players}

    def name(self, value):
        return self.rules.types.get(int(value) & NONE_U32)

    def source_label(self, row):
        if row.get("Self"):
            return "区域基础加成"
        if "RequiredAppeal" in row:
            return "地块魅力 ≥ " + str(row["RequiredAppeal"])
        if row.get("AdjacentRiver"):
            return "濒临河流"
        if row.get("OtherDistrictAdjacent"):
            return "相邻已建区域"
        if row.get("AdjacentNaturalWonder"):
            return "相邻自然奇观"
        if row.get("AdjacentWonder"):
            return "相邻已建奇观"
        if row.get("AdjacentSeaResource"):
            return "相邻海洋资源"
        if row.get("AdjacentResource"):
            return "相邻资源"
        cls = row.get("AdjacentResourceClass", "NO_RESOURCECLASS")
        if cls != "NO_RESOURCECLASS":
            return {"RESOURCECLASS_STRATEGIC": "相邻战略资源", "RESOURCECLASS_LUXURY": "相邻奢侈资源",
                    "RESOURCECLASS_BONUS": "相邻加成资源"}.get(cls, "相邻资源")
        for field in ("AdjacentTerrain", "AdjacentFeature", "AdjacentImprovement", "AdjacentDistrict"):
            typ = row.get(field)
            if typ:
                if field == "AdjacentTerrain" and typ.endswith("_MOUNTAIN"):
                    return "相邻山脉"
                return "相邻" + get_gamedb().name(H(typ))
        return "相邻加成"

    def valid(self, x, y):
        return 0 <= x < self.state.width and 0 <= y < self.state.height

    def beliefs(self, p, c):
        religion = self.religions.get(c.religion & NONE_U32)
        if religion:
            values = list(religion.beliefs)
            founder = self.players.get(religion.iPlayer)
            if founder:
                values.append(founder.pantheon)
        elif (c.religion & NONE_U32) == NONE_U32:
            values = [p.pantheon]
        else:
            return None
        return {self.name(v) for v in values if (int(v) & NONE_U32) != NONE_U32}

    def condition(self, set_id, p, c, d, beliefs, visiting=()):
        if not set_id:
            return True
        rules = self.rules
        if set_id not in rules.req_sets or set_id in visiting:
            return None
        values = []
        for rid in rules.req_members.get(set_id, ()):
            row = rules.requirements[rid]
            typ, args = row["RequirementType"], rules.req_args[rid]
            if typ == "REQUIREMENT_CITY_FOLLOWS_PANTHEON":
                value = bool(beliefs)
            elif typ == "REQUIREMENT_PLAYER_HAS_PANTHEON":
                value = (int(p.pantheon) & NONE_U32) != NONE_U32
            elif typ == "REQUIREMENT_PLAYER_HAS_TECHNOLOGY":
                value = (bool(p.techDogmeInfo[0].found.get(H(args["TechnologyType"])))
                         if p.techDogmeInfo[0].found else None)
            elif typ == "REQUIREMENT_PLAYER_HAS_CIVIC":
                value = (bool(p.techDogmeInfo[1].found.get(H(args["CivicType"])))
                         if p.techDogmeInfo[1].found else None)
            elif typ == "REQUIREMENT_CITY_HAS_BUILDING":
                bh = H(args["BuildingType"])
                value = bh in c.built and (c.built[bh] & 0xFFFF) != 0xFFFF and not c.pillagedBuildings.get(bh)
            elif typ == "REQUIREMENT_REQUIREMENTSET_IS_MET":
                value = self.condition(args["RequirementSetId"], p, c, d, beliefs, (*visiting, set_id))
            elif typ == "REQUIREMENT_DISTRICT_TYPE_MATCHES":
                value = rules.matches_district(self.name(d.type), args["DistrictType"])
            elif typ == "REQUIREMENT_PLOT_APPEAL_BETWEEN":
                appeal = self.state.tiles[d.y * self.state.width + d.x].appeal
                value = int(args.get("MinimumAppeal", -1000)) <= appeal <= int(args.get("MaximumAppeal", 1000))
            else:
                return None
            values.append(not value if value is not None and row.get("Inverse") else value)
        any_of = rules.req_sets[set_id]["RequirementSetType"] == "REQUIREMENTSET_TEST_ANY"
        decisive = True if any_of else False
        if any(v is decisive for v in values):
            return decisive
        return None if None in values else not decisive

    def count(self, row, p, d, adjacent, explicit_districts, matched_tiles=None):
        tiles, rules = self.state.tiles, self.rules
        origin = tiles[d.y * self.state.width + d.x]
        if row.get("Self"):
            return 1
        if "RequiredAppeal" in row:
            return int(origin.appeal >= row["RequiredAppeal"])
        if row.get("AdjacentRiver"):
            return int(bool(origin.river & 0x3F))
        count = 0
        for index in adjacent:
            tile = tiles[index]
            matched = False
            if row.get("OtherDistrictAdjacent"):
                matched |= index in self.built_districts
            if row.get("AdjacentDistrict"):
                actual = self.built_districts.get(index)
                expected = row["AdjacentDistrict"]
                # Prefer an explicit unique-district rule when present; other
                # official rules (e.g. Hansa next to Bath/Suguba) inherit the
                # base selector. Never count both base and explicit variants.
                matched |= actual == expected or (
                    rules.replaces.get(actual) == expected
                    and (actual, row["YieldType"]) not in explicit_districts)
            if row.get("AdjacentTerrain"):
                matched |= self.name(tile.terrain) == row["AdjacentTerrain"]
            if row.get("AdjacentFeature"):
                matched |= self.name(tile.feature) == row["AdjacentFeature"]
            if row.get("AdjacentImprovement"):
                matched |= self.name(tile.improvment) == row["AdjacentImprovement"]
            if row.get("AdjacentNaturalWonder"):
                matched |= bool(rules.features.get(self.name(tile.feature), {}).get("NaturalWonder"))
            if row.get("AdjacentWonder"):
                matched |= index in self.wonders
            resource = rules.resources.get(self.name(tile.resource), {})
            tech = resource.get("PrereqTech")
            revealed = bool(resource) and (not tech or bool(p.techDogmeInfo[0].found.get(H(tech))))
            if row.get("AdjacentResource"):
                matched |= revealed
            resource_class = row.get("AdjacentResourceClass", "NO_RESOURCECLASS")
            if resource_class != "NO_RESOURCECLASS":
                matched |= revealed and resource.get("ResourceClassType") == resource_class
            if row.get("AdjacentSeaResource"):
                matched |= revealed and bool(rules.terrains.get(self.name(tile.terrain), {}).get("Water"))
            count += int(matched)
            if matched and matched_tiles is not None:
                matched_tiles.append(index)
        return count

    def calculate(self, p, d):
        rules = self.rules
        if not self.valid(d.x, d.y) or (d.type & NONE_U32) == WONDER:
            return None
        actual = self.name(d.type)
        traits = self.traits.get(p.iPlayer)
        c = self.cities.get((p.iPlayer, d.cityId))
        if actual not in rules.districts or traits is None or c is None:
            return None
        adjacent = list(neighbors(d.x, d.y, self.state.width, self.state.height, self.wrap_x))
        for index in [d.y * self.state.width + d.x, *adjacent]:
            tile = self.state.tiles[index]
            if self.name(tile.terrain) not in rules.terrains:
                return None
            if (tile.feature & NONE_U32) != NONE_U32 and self.name(tile.feature) not in rules.features:
                return None
        excluded = {rid for trait in traits for rid in rules.excluded.get(trait, ())}
        active = [rules.rules[rid] for rid in rules.by_district.get(actual, ()) if rid not in excluded]
        origins = {}
        civ_traits = rules.civ_traits.get(self.name(self.info[p.iPlayer].civ), ())
        for trait in sorted(traits):
            for mid in rules.trait_mods.get(trait, ()):
                origins[mid] = "文明能力" if trait in civ_traits else "领袖能力"
        roots = set(origins)
        beliefs = self.beliefs(p, c)
        if beliefs is None:
            return None
        for belief in sorted(b for b in beliefs if b):
            for mid in rules.belief_mods.get(belief, ()):
                roots.add(mid)
                origins[mid] = "信仰：" + get_gamedb().name(H(belief))
        for mid in rules.district_mods.get(actual, ()):
            roots.add(mid)
            origins[mid] = "区域能力"
        candidates = [(mid, None, None, origins[mid]) for mid in sorted(roots)]
        candidates += [(mid, city_id, None, "建筑：" + get_gamedb().name(H(bt)))
                       for city_id, bt in self.player_buildings[p.iPlayer]
                       for mid in rules.building_mods.get(bt, ())]
        for g in p.governors:
            if g.city == c.id:
                mids = list(rules.governor_mods.get(self.name(g.type), ()))
                mids += [mid for promo in g.promotions
                         for mid in rules.governor_promotion_mods.get(self.name(promo), ())]
                candidates += [(mid, c.id, g, "总督晋升") for mid in mids]
        seen = set()
        for mid, source_city, governor, origin in candidates:
            for row in rules._modifier_rules.get(mid, ()):
                if not rules.matches_district(actual, row["target"]):
                    continue
                if source_city is not None and row["scope"] == "COLLECTION_OWNER" and source_city != c.id:
                    continue
                applicable = [self.condition(s, p, c, d, beliefs)
                              for pair in row["conditions"] for s in pair]
                if governor is not None:
                    applicable.append(vars(governor).get("established"))
                if any(v is False for v in applicable):
                    continue
                if None in applicable:
                    if not self.count(row, p, d, adjacent, set()):
                        continue  # a missing gate cannot affect a zero contribution
                    return None
                if not all(applicable) or row["ID"] in seen:
                    continue
                seen.add(row["ID"])
                active.append({**row, "origin": origin})
        yields = defaultdict(int)
        sources = []
        explicit_districts = {(r["AdjacentDistrict"], r["YieldType"])
                              for r in active if r.get("AdjacentDistrict")}
        for row in active:
            required = max(1, int(row.get("TilesRequired", 1)))
            for field, kind in (("PrereqTech", 0), ("PrereqCivic", 1)):
                if row.get(field) and not p.techDogmeInfo[kind].found.get(H(row[field])):
                    break
            else:
                if any(row.get(field) and p.techDogmeInfo[kind].found.get(H(row[field]))
                       for field, kind in (("ObsoleteTech", 0), ("ObsoleteCivic", 1))):
                    continue
                matches = []
                count = self.count(row, p, d, adjacent, explicit_districts, matches)
                rate = int(row["YieldChange"])
                amount = (count // required) * rate
                yh = str(H(row["YieldType"]))
                yields[yh] += amount
                if count:
                    sources.append({"rule": row["ID"], "label": self.source_label(row),
                                    "origin": row.get("origin", "区域规则"), "yield": yh,
                                    "amount": amount, "count": count, "required": required,
                                    "rate": rate, "tiles": matches})
        for row in rules.custom_adjacencies:
            if actual != row["DistrictType"] and not (
                    row.get("ApplyForUniqueDistricts") and rules.matches_district(actual, row["DistrictType"])):
                continue
            if row.get("TraitType") and row["TraitType"] not in traits and not row.get("DistrictModifiers"):
                continue
            # All six modules in the captured CCB session use this Lua path.
            # Its statistic counts completed human wonders, not natural wonders,
            # nor the synthetic District.built flag of an unfinished wonder.
            if (row["ProvideType"] != "SelfBonus" or row["AdjacencyType"] != "FROM_ADJACENT_WONDERS"
                    or row["ModifierOwner"] != "DistrictModifiers" or row.get("FreeCompose")
                    or row["Only"] != "Human&AI" or row["Rings"] != 1):
                return None
            matches = [index for index in adjacent if index in self.wonders]
            rate = float(row["YieldChange"])
            amount = math.floor(len(matches) * rate)
            yh = str(H(row["YieldType"]))
            yields[yh] += amount
            if matches:
                sources.append({"rule": row["ID"], "label": "相邻已建奇观", "origin": "领袖能力",
                                "yield": yh, "amount": amount, "count": len(matches),
                                "required": 1, "rate": rate, "tiles": matches})
        for yh, amount in yields.items():
            if amount < 0:
                sources.append({"rule": "zero_floor", "label": "负值按 0 计", "origin": "结果处理",
                                "yield": yh, "amount": -amount, "count": None,
                                "required": None, "rate": None, "tiles": []})
        return {"yields": {key: value for key, value in yields.items() if value > 0}, "sources": sources}


def calculate_adjacencies(state, *, wrap_x=None, rules=None, include_sources=False):
    """Return {id(record): yields_or_None}; include_sources adds the source report.

    Reports contain ``yields`` and ``sources`` from the same calculation. This
    keeps the map total and the city/tile source panels in agreement.
    """
    records = [d for p in state.players if p.iPlayer >= 0 for d in p.districts]
    unavailable = {id(d): None for d in records}
    packages = state.modPackages or [{"key": m, "name": m} for m in state.mods]
    # CCB's merged database takes precedence if a dependency also names BBG.
    is_ccb = any(re.search(r"\bCCB\b|和而不同", p["name"], re.I) for p in packages)
    mode = "CCB" if is_ccb else balance_mod(state.mods) or state.balanceMod
    profile = {"CCB": "ccb", "BBG": "bbg"}.get(mode, "official")
    rules = rules or (get_rules(profile) if profile != "official" else get_rules())
    if (not rules or state.unsupported
            or rules.profile != profile
            or (profile == "ccb" and not any(re.match(r"^CCB\s+\d", m["name"]) for m in packages))
            or (profile == "bbg" and not any(re.search(r"^Better\s+Balanced\s+Game\b|^BBG\s+\d", m["name"], re.I) for m in packages))
            or any(not _profile_package(m, rules) for m in packages)
            or any(getattr(e, "section", "") in ("map", "players_info", "links") for e in state.layerErrors)
            or state.width <= 0 or state.height <= 0 or len(state.tiles) != state.width * state.height):
        return unavailable
    if profile == "bbg":
        clean = lambda s: re.sub(r"\[(?:COLOR[^\]]*|ENDCOLOR)\]", "", s).strip()
        gameplay = lambda pkgs: {clean(m["name"]) for m in pkgs if not (
            _official_package(m["key"], rules) or _official_package(m["name"], rules))}
        if gameplay(packages) != gameplay(rules.packages):
            return unavailable
    if state.modPackages:
        keys = {m["key"] for m in packages}
        expansion = ("LOC_EXPANSION2_MOD_TITLE" if "LOC_EXPANSION2_MOD_TITLE" in keys else
                     "LOC_EXPANSION1_MOD_TITLE" if "LOC_EXPANSION1_MOD_TITLE" in keys else None)
        if expansion != rules.expansion_key:
            return unavailable
    if wrap_x is None:
        wrap_x = bool(_wrap_map().get(state.map_key, True))
    turn = _Turn(state, rules, wrap_x)
    results = {id(d): turn.calculate(p, d) for p in turn.players.values() for d in p.districts}
    if include_sources:
        return results
    return {key: report["yields"] if report is not None else None for key, report in results.items()}
