"""Offline plot yields, with explicit unknown conditions and source accounting.

Disaster fertility and city-wide yield multipliers are outside this calculation.
Unknown save state is never substituted by zero/False or inferred from tech era.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import re
from pathlib import Path

from .adjacency import AdjacencyRules, neighbors, _wrap_map
from .gamedb import get_gamedb
from .hash import crc32_type as H
from .hash import TYPE_CIV_CITY_STATE, TYPE_CIV_FREE_CITIES, TYPE_CIV_FULL
from .model import NONE_U32
from .mods import balance_mod, blacklisted_mods

ROOT = Path(__file__).resolve().parents[2] / "data/gamedb"
PROFILES = ("vanilla", "bbg", "ccb")
PLOT_EFFECT = "EFFECT_ADJUST_PLOT_YIELD"
TERRACE_EFFECT = "EFFECT_ADJUST_TERRAIN_YIELD_FROM_ADJACENT_IMPROVEMENTS"
TERRAIN_CITIES_EFFECT = "EFFECT_ADJUST_CITY_YIELD_PER_TERRAIN_CLASS_CITIES_IMPROVEMENT"
PLOT_YIELD_EFFECTS = {PLOT_EFFECT, TERRACE_EFFECT, TERRAIN_CITIES_EFFECT}
SIX = {"YIELD_" + name for name in ("FOOD", "PRODUCTION", "GOLD", "SCIENCE", "CULTURE", "FAITH")}
ROOT_TABLES = {
    "trait": ("TraitModifiers", "TraitType"),
    "belief": ("BeliefModifiers", "BeliefType"),
    "building": ("BuildingModifiers", "BuildingType"),
    "improvement": ("ImprovementModifiers", "ImprovementType"),
    "policy": ("PolicyModifiers", "PolicyType"),
    "government": ("GovernmentModifiers", "GovernmentType"),
    "governor": ("GovernorPromotionModifiers", "GovernorPromotionType"),
    "tech": ("TechnologyModifiers", "TechnologyType"),
    "civic": ("CivicModifiers", "CivicType"),
    "commemoration": ("CommemorationModifiers", "CommemorationType"),
    "district": ("DistrictModifiers", "DistrictType"),
}
# These require runtime state not yet verified in the binary parser.
UNKNOWN_REQUIREMENTS = {
    "REQUIREMENT_PLAYER_ERA_AT_LEAST": "玩家时代尚未解析",
    "REQUIREMENT_GAME_ERA_ATLEAST_EXPANSION": "世界时代尚未解析",
    "REQUIREMENT_PLAYER_IS_AT_PEACE": "外交战争状态尚未解析",
    "REQUIREMENT_PLAYER_IS_SUZERAIN_BONUS_ENABLED": "宗主加成是否生效尚未解析",
    "REQUIREMENT_PLOT_IS_OWNER_CAPITAL_CONTINENT": "首都所在大陆尚未解析",
}


def combine(values, any_of=False):
    """Three-valued AND/OR. A decisive False/True suppresses unrelated unknowns."""
    decisive = True if any_of else False
    if any(v is decisive for v, _ in values):
        return decisive, set()
    missing = set().union(*(m for v, m in values if v is None)) if values else set()
    if any(v is None for v, _ in values):
        return None, missing
    return not decisive, set()


def _group(rows, key):
    out = defaultdict(list)
    for row in rows:
        out[row[key]].append(row)
    return out


class YieldRules(AdjacencyRules):
    def __init__(self, document):
        if document.get("format") != 1 or document.get("profile") not in PROFILES:
            raise ValueError("unsupported plot-yield snapshot")
        self.profile = document["profile"]
        self.enabled_packages = document.get("enabledPackages", [])
        self.labels = document.get("labels", {})
        super().__init__({**document, "profile": "official"})
        t = self.tables = document["tables"]
        self.improvements = {r["ImprovementType"]: r for r in t["Improvements"]}
        self.base = {kind: _group(t[table], field) for kind, table, field in (
            ("terrain", "Terrain_YieldChanges", "TerrainType"),
            ("feature", "Feature_YieldChanges", "FeatureType"),
            ("resource", "Resource_YieldChanges", "ResourceType"),
            ("improvement", "Improvement_YieldChanges", "ImprovementType"))}
        self.bonuses = _group(t["Improvement_BonusYieldChanges"], "ImprovementType")
        self.improvement_adj = _group(t["Improvement_Adjacencies"], "ImprovementType")
        self.feature_adj = _group(t["Feature_AdjacentYields"], "FeatureType")
        self.tags = defaultdict(set)
        for row in t["TypeTags"]:
            self.tags[row["Type"]].add(row["Tag"])
        self.terrain_classes = defaultdict(set)
        for row in t["TerrainClass_Terrains"]:
            self.terrain_classes[row["TerrainClassType"]].add(row["TerrainType"])
        self.valid_resources = defaultdict(set)
        for row in t["Improvement_ValidResources"]:
            self.valid_resources[row["ImprovementType"]].add(row["ResourceType"])
        self.params = {row["Name"]: row["Value"] for row in t["GlobalParameters"]}
        self.name_keys = {row[key]: row.get("Name") for table, key in (
            ("Terrains", "TerrainType"), ("Features", "FeatureType"),
            ("Resources", "ResourceType"), ("Improvements", "ImprovementType"),
            ("Buildings", "BuildingType"), ("Districts", "DistrictType"),
            ("Leaders", "LeaderType")) for row in t[table]}
        self.name_keys.update(document.get("nameKeys", {}))
        self.roots = {kind: _group(t[table], field)
                      for kind, (table, field) in ROOT_TABLES.items()}
        self.source_types = {row.get("ModifierId", row.get("ModifierID")): typ
                             for mapping in self.roots.values() for typ, rows in mapping.items()
                             for row in rows}
        self.chains = {mid: self._chains(mid) for mid in self.modifiers}
        self.improvement_yield_gaps = {
            typ: set().union(*(self._yield_gaps(row.get("ModifierId", row.get("ModifierID")))
                               for row in rows))
            for typ, rows in self.roots["improvement"].items()
        }
        relevant = {mid for chain in self.chains.values() for path in chain for mid in path}
        sets = {self.modifiers[mid][key] for mid in relevant
                for key in ("OwnerRequirementSetId", "SubjectRequirementSetId")
                if self.modifiers[mid].get(key)}
        while True:
            before = len(sets)
            sets.update(self.req_args[rid]["RequirementSetId"] for sid in tuple(sets)
                        for rid in self.req_members.get(sid, ())
                        if self.req_args[rid].get("RequirementSetId"))
            if len(sets) == before:
                break
        self.coverage = {
            "effects": sorted({self.dynamic[self.modifiers[mid]["ModifierType"]]["EffectType"]
                               for mid in relevant}),
            "requirements": sorted({self.requirements[rid]["RequirementType"]
                                    for sid in sets for rid in self.req_members.get(sid, ())}),
            "runtimeMissing": UNKNOWN_REQUIREMENTS,
            "requirementIds": sorted({rid for sid in sets for rid in self.req_members.get(sid, ())}),
        }

    def _chains(self, mid, visiting=()):
        if mid in visiting or mid not in self.modifiers:
            return []
        m = self.modifiers[mid]
        effect = self.dynamic.get(m["ModifierType"], {}).get("EffectType", "")
        args = self.args[mid]
        if effect in PLOT_YIELD_EFFECTS and any(
                y.strip() in SIX for y in args.get("YieldType", "").split(",")):
            return [(mid,)]
        if "ATTACH_MODIFIER" in effect and args.get("ModifierId"):
            return [(mid, *path) for path in self._chains(args["ModifierId"], (*visiting, mid))]
        return []

    def _yield_gaps(self, mid, visiting=()):
        # Some mods deliberately delete Modifiers but retain their old links.
        # Such links have no gameplay effect; do not invent missing yields.
        if mid not in self.modifiers or mid in visiting:
            return set()
        mod = self.modifiers[mid]
        effect = self.dynamic.get(mod["ModifierType"], {}).get("EffectType", "")
        args = self.args[mid]
        if "ATTACH_MODIFIER" in effect and args.get("ModifierId"):
            return self._yield_gaps(args["ModifierId"], (*visiting, mid))
        if effect not in PLOT_YIELD_EFFECTS and any(
                y.strip() in SIX for y in args.get("YieldType", "").split(",")):
            return {"未覆盖改良产出效果：" + (effect or mod["ModifierType"])}
        return set()

    def traits(self, info):
        # Minor civilizations' bonuses live on their inherited leader; unlike
        # major civs they need not have any CivilizationTraits rows.
        if (info.typeCiv & NONE_U32) != TYPE_CIV_CITY_STATE:
            return super().traits(info)
        leader = info.leaderStr if info.leaderStr in self.leaders else self.types.get(info.leader & NONE_U32)
        traits, seen = set(), set()
        if leader not in self.leaders:
            return None
        while leader and leader not in seen:
            seen.add(leader)
            traits.update(self.leader_traits.get(leader, ()))
            leader = self.leaders.get(leader, {}).get("InheritFrom")
        return traits


@lru_cache(maxsize=3)
def _load_rules(profile, stamp):
    try:
        return YieldRules(json.loads((ROOT / profile / "tileyields.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def get_rules(profile="vanilla"):
    path = ROOT / profile / "tileyields.json"
    try:
        st = path.stat()
        return _load_rules(profile, (st.st_mtime_ns, st.st_size))
    except OSError:
        return None


def rules_token():
    """Cache namespace includes all installed profile fingerprints (and missing ones)."""
    values = [get_rules(p).fingerprint if get_rules(p) else "missing" for p in PROFILES]
    from .database_versions import metadata_token
    values.append(metadata_token())
    return hashlib.sha256(("plot-engine-11|" + "|".join(values)).encode()).hexdigest()[:20]


def result(yields=None, breakdown=None, missing=(), unavailable=False):
    return {"yields": yields or {}, "breakdown": breakdown or [],
            "status": "unavailable" if unavailable else "partial" if missing else "complete",
            "missing": sorted(set(missing))}


class TurnYields:
    def __init__(self, state, rules, wrap_x):
        self.state, self.r, self.wrap = state, rules, wrap_x
        self.players = {p.iPlayer: p for p in state.players if p.iPlayer >= 0}
        self.infos = {p.iPlayer: p for p in state.playersInfo}
        self.cities = {(p.iPlayer, c.id): c for p in self.players.values() for c in p.cities}
        self.palace_capitals = {}
        for p in self.players.values():
            capitals = [(c.x, c.y) for c in p.cities
                        if c.built.get(H("BUILDING_PALACE")) == c.y * state.width + c.x]
            if len(capitals) == 1:
                self.palace_capitals[p.iPlayer] = capitals[0]
        self.religions = {r.iSymbol & NONE_U32: r for r in state.religions}
        self.districts, self.buildings = {}, defaultdict(list)
        for p in self.players.values():
            for d in p.districts:
                if 0 <= d.x < state.width and 0 <= d.y < state.height:
                    self.districts[d.y * state.width + d.x] = (p.iPlayer, d)
            for c in p.cities:
                for bh, index in c.built.items():
                    if 0 <= (index := int(index) & 0xFFFF) < len(state.tiles):
                        self.buildings[index].append((p, c, self.name(bh), bool(c.pillagedBuildings.get(bh))))
        self.city_roots = {}
        for (pid, cid), c in self.cities.items():
            self.city_roots[pid, cid] = self._roots(self.players[pid], c)
        self.public_roots = [(row["ModifierId"], None, None, None)
                             for row in rules.tables["GameModifiers"]]
        self.neighbor_cache = {}
        self.terrain_city_counts = {}
        self.city_improvement_roots = defaultdict(list)
        for index, tile in enumerate(state.tiles):
            imp = self.improvement(tile)
            for row in rules.roots["improvement"].get(imp, ()):
                mid = row.get("ModifierId", row.get("ModifierID"))
                if any(rules.dynamic[rules.modifiers[chain[-1]]["ModifierType"]]["EffectType"] == TERRAIN_CITIES_EFFECT
                       for chain in rules.chains.get(mid, ())):
                    self.city_improvement_roots[tile.iPlayer, tile.iCity].append((mid, index))

    def terrain_city_count(self, p):
        """Count distinct city-center terrain classes, merging hills/flat land."""
        if p.iPlayer not in self.terrain_city_counts:
            classes, missing = set(), set()
            for city in p.cities:
                if not (0 <= city.x < self.state.width and 0 <= city.y < self.state.height):
                    missing.add("建城地形统计：城市中心坐标缺失")
                    continue
                terrain = self.name(self.state.tiles[city.y * self.state.width + city.x].terrain)
                matching = {typ for typ, terrains in self.r.terrain_classes.items() if terrain in terrains}
                if not matching:
                    missing.add("建城地形统计：城市中心地形类别缺失")
                classes.update(matching)
            self.terrain_city_counts[p.iPlayer] = (len(classes), missing)
        return self.terrain_city_counts[p.iPlayer]

    def name(self, value):
        return self.r.types.get(int(value) & NONE_U32)

    def label(self, typ):
        if not typ:
            return "未知对象"
        key = self.r.name_keys.get(typ) or "LOC_" + typ + "_NAME"
        return self.r.labels.get(key) or get_gamedb().name(H(typ))

    def adjacent(self, index):
        if index not in self.neighbor_cache:
            self.neighbor_cache[index] = list(neighbors(index % self.state.width, index // self.state.width,
                                                        self.state.width, self.state.height, self.wrap))
        return self.neighbor_cache[index]

    def researched(self, p, typ, civic=False):
        if not typ:
            return True
        if p is None or not p.techDogmeInfo[int(civic)].found:
            return None
        return bool(p.techDogmeInfo[int(civic)].found.get(H(typ)))

    def gate(self, row, p):
        vals = [(self.researched(p, row.get(field), civic), {"科技或市政完成状态缺失"})
                for field, civic in (("PrereqTech", False), ("PrereqCivic", True))]
        for field, civic in (("ObsoleteTech", False), ("ObsoleteCivic", True)):
            if row.get(field):
                v = self.researched(p, row[field], civic)
                vals.append((None if v is None else not v, {"科技或市政完成状态缺失"}))
        return combine(vals)

    def visible_resource(self, tile, p):
        res = self.r.resources.get(self.name(tile.resource))
        if not res:
            return False
        if p is None and tile.iPlayer == 0xFFFF:
            return True  # Unowned plots deliberately include all resource yields.
        return self.gate(res, p)[0]

    def has_skills(self, p):
        info = self.infos.get(p.iPlayer) if p else None
        # typePlayer describes the controller (1 = AI, 3 = human), not
        # civilization class. Both controllers retain a major civ's skills.
        return bool(p and (not info or (info.typeCiv & NONE_U32)
                    not in (TYPE_CIV_CITY_STATE, TYPE_CIV_FREE_CITIES)))

    def improvement(self, tile):
        return None if (tile.pillage & 1) else self.name(tile.improvment)

    def lake(self, tile):
        terrain = self.name(tile.terrain)
        if terrain == "TERRAIN_LAKE" or self.r.features.get(self.name(tile.feature), {}).get("Lake"):
            return True
        if terrain != "TERRAIN_COAST":
            return False
        # Coast is also used for ordinary lakes. The current parser does not
        # retain the engine's lake flag; never silently classify it as sea.
        return vars(tile).get("isLake")

    def beliefs(self, p, c):
        if c is None:
            return {self.name(p.pantheon)} if p else set()
        religion = self.religions.get(c.religion & NONE_U32)
        if religion:
            founder = self.players.get(religion.iPlayer)
            return {self.name(v) for v in [*religion.beliefs, *([founder.pantheon] if founder else [])]}
        if (c.religion & NONE_U32) == NONE_U32:
            return {self.name(p.pantheon)}
        return None

    def _roots(self, p, c):
        roots = []
        def add(kind, typ, source_p=p, source_c=None, extra=None):
            for row in self.r.roots[kind].get(typ, ()):
                mid = row.get("ModifierId", row.get("ModifierID"))
                if self.r.chains.get(mid):
                    roots.append((mid, source_p, source_c, extra))
        info = self.infos.get(p.iPlayer)
        traits = self.r.traits(info) if info else None
        skills = self.has_skills(p)
        for trait in (traits or ()) if skills else ():
            add("trait", trait)
        for typ in (self.beliefs(p, c) or ()) if skills else ():
            add("belief", typ, extra=("belief", typ))
        for slot in p.policies if skills else ():
            for typ in slot:
                add("policy", self.name(typ))
        if skills:
            add("government", self.name(p.government))
        # District-owned modifiers are evaluated at their plot, below.
        for civic, kind in ((False, "tech"), (True, "civic")):
            for typ, done in p.techDogmeInfo[int(civic)].found.items():
                if done:
                    add(kind, self.name(typ))
        for typ in p.commemorations if skills else ():
            add("commemoration", self.name(typ))
        for entries in self.buildings.values():
            for owner, city, typ, pillaged in entries:
                if owner is p and not pillaged:
                    add("building", typ, source_c=city)
        for g in p.governors if skills else ():
            if g.city == c.id:
                for typ in g.promotions:
                    add("governor", self.name(typ), source_c=c, extra=("governor", g))
        # City-state trait roots attach to eligible players; retain the source
        # city-state identity for suzerain requirements, including ties.
        for pid, csinfo in self.infos.items():
            cs = self.players.get(pid)
            if not skills or (csinfo.typeCiv & NONE_U32) != TYPE_CIV_CITY_STATE or not cs or not cs.cities:
                continue
            for trait in self.r.traits(csinfo) or ():
                add("trait", trait, source_p=cs, extra=("citystate", cs))
        return roots

    def condition(self, sid, index, p, c, source_p, source_c, extra, visiting=()):
        if not sid:
            return True, set()
        if sid in visiting or sid not in self.r.req_sets:
            return None, {"条件集合缺失或循环：" + sid}
        values = []
        for rid in self.r.req_members.get(sid, ()):
            row = self.r.requirements[rid]
            v, missing = self.requirement(row["RequirementType"], self.r.req_args[rid],
                                          index, p, c, source_p, source_c, extra, (*visiting, sid))
            if row.get("Inverse") and v is not None:
                v = not v
            values.append((v, missing))
        return combine(values, self.r.req_sets[sid]["RequirementSetType"] == "REQUIREMENTSET_TEST_ANY")

    def requirement(self, typ, a, index, p, c, sp, sc, extra, visiting):
        tile = self.state.tiles[index]
        terrain, feature = self.name(tile.terrain), self.name(tile.feature)
        tr, ft = self.r.terrains.get(terrain, {}), self.r.features.get(feature, {})
        improvement = self.improvement(tile)
        visible = self.visible_resource(tile, p)
        resource = self.name(tile.resource) if visible is True else None
        adjacent = self.adjacent(index)
        v = None
        missing = set()
        if typ in UNKNOWN_REQUIREMENTS:
            # Optional verified state can be supplied by future parsers/fixtures.
            field = {"REQUIREMENT_PLAYER_ERA_AT_LEAST": "eraType",
                     "REQUIREMENT_GAME_ERA_ATLEAST_EXPANSION": "eraType",
                     "REQUIREMENT_PLAYER_IS_AT_PEACE": "atPeace",
                     "REQUIREMENT_PLAYER_IS_SUZERAIN_BONUS_ENABLED": "suzerainBonusEnabled",
                     "REQUIREMENT_PLOT_IS_OWNER_CAPITAL_CONTINENT": "capitalContinent"}[typ]
            obj = self.state if typ == "REQUIREMENT_GAME_ERA_ATLEAST_EXPANSION" else p
            value = vars(obj).get(field) if obj else None
            if value is not None:
                if field == "eraType":
                    eras = {r["EraType"]: r["ChronologyIndex"] for r in self.r.tables["Eras"]}
                    v = eras[value] >= eras[a["EraType"]] if value in eras else None
                elif field == "capitalContinent":
                    v = tile.continent == value
                else:
                    v = bool(value)
            missing.add(UNKNOWN_REQUIREMENTS[typ])
        elif typ == "REQUIREMENT_PLAYER_HAS_TECHNOLOGY":
            v = self.researched(p, a["TechnologyType"])
            missing.add("科技完成状态缺失")
        elif typ == "REQUIREMENT_PLAYER_HAS_CIVIC":
            v = self.researched(p, a["CivicType"], True)
            missing.add("市政完成状态缺失")
        elif typ == "REQUIREMENT_REQUIREMENTSET_IS_MET":
            return self.condition(a["RequirementSetId"], index, p, c, sp, sc, extra, visiting)
        elif typ == "REQUIREMENT_CITY_FOLLOWS_PANTHEON":
            beliefs = self.beliefs(p, c)
            v = None if beliefs is None else bool(extra and extra[0] == "belief" and extra[1] in beliefs)
            missing.add("城市信仰状态缺失")
        elif typ == "REQUIREMENT_CITY_HAS_BUILDING":
            v = self.has_building(p, c, a["BuildingType"]) if c else None
            missing.add("所属城市缺失")
        elif typ == "REQUIREMENT_CITY_HAS_DISTRICT":
            v = None if not p or not c else any(
                d.cityId == c.id and d.built and self.r.matches_district(self.name(d.type), a["DistrictType"])
                and (a.get("MustBeFunctioning", "1") == "0" or not d.pillage)
                for d in p.districts)
            missing.add("所属城市缺失")
        elif typ in ("REQUIREMENT_PLOT_DISTRICT_TYPE_MATCHES", "REQUIREMENT_DISTRICT_TYPE_MATCHES"):
            d = self.districts.get(index)
            v = bool(d and d[1].built and self.r.matches_district(self.name(d[1].type), a["DistrictType"]))
            if not d and c and (c.x, c.y) == (index % self.state.width, index // self.state.width):
                v = a["DistrictType"] == "DISTRICT_CITY_CENTER"
        elif typ in ("REQUIREMENT_MAP_HAS_FEATURE", "REQUIREMENT_PLAYER_HAS_FEATURE"):
            v = any(self.name(t.feature) == a["FeatureType"] and (
                typ == "REQUIREMENT_MAP_HAS_FEATURE" or p and t.iPlayer == p.iPlayer)
                for t in self.state.tiles)
        elif typ == "REQUIREMENT_PLOT_PROPERTY_MATCHES":
            properties = vars(tile).get("properties")
            if properties is not None:
                value = properties.get(a["PropertyName"], 0)
                v = float(a.get("PropertyMinimum", "-inf")) <= value <= float(a.get("PropertyMaximum", "inf"))
            missing.add("Lua 地块属性尚未解析：" + a["PropertyName"])
        elif typ == "REQUIREMENT_PLOT_NEAR_CAPITAL":
            capital = (vars(p).get("capitalPosition") or self.palace_capitals.get(p.iPlayer)) if p else None
            if capital is not None:
                def axial(x, y):
                    return x - (y - (y & 1)) // 2, y
                x, y = index % self.state.width, index // self.state.width
                q1, r1 = axial(*capital)
                distances = []
                for dx in ((-self.state.width, 0, self.state.width) if self.wrap else (0,)):
                    q2, r2 = axial(x + dx, y)
                    distances.append(max(abs(q2-q1), abs(r2-r1), abs(q2+r2-q1-r1)))
                distance = min(distances)
                v = int(a.get("MinDistance", 0)) <= distance <= int(a.get("MaxDistance", 100000))
            missing.add("首都位置尚未解析")
        elif typ == "REQUIREMENT_CITY_HAS_SPECIFIC_GOVERNOR_PROMOTION_TYPE":
            gs = [g for g in p.governors if c and g.city == c.id
                  and H(a["GovernorPromotionType"]) in g.promotions] if self.has_skills(p) else []
            v = False if not gs else combine([(vars(g).get("established"), {"总督就任状态尚未解析"}) for g in gs], True)[0]
            missing.add("总督就任状态尚未解析")
        elif typ == "REQUIREMENT_PLAYER_OWNS_OBJECT":
            v = bool(p and sp and p.iPlayer == sp.iPlayer)
        elif typ == "REQUIREMENT_PLAYER_IS_SUZERAIN":
            if extra and extra[0] == "citystate" and p:
                counts = [(pid, count) for pid, count in enumerate(extra[1].emissaries)
                          if count and pid in self.infos
                          and (self.infos[pid].typeCiv & NONE_U32) == TYPE_CIV_FULL]
                top = max((count for _, count in counts), default=0)
                winners = [pid for pid, count in counts if count == top]
                v = top >= 3 and winners == [p.iPlayer]
            else:
                v = False
        elif typ in ("REQUIREMENT_PLOT_TERRAIN_TYPE_MATCHES", "REQUIREMENT_PLOT_FEATURE_TYPE_MATCHES",
                      "REQUIREMENT_PLOT_IMPROVEMENT_TYPE_MATCHES"):
            actual, key = {"REQUIREMENT_PLOT_TERRAIN_TYPE_MATCHES": (terrain, "TerrainType"),
                           "REQUIREMENT_PLOT_FEATURE_TYPE_MATCHES": (feature, "FeatureType"),
                           "REQUIREMENT_PLOT_IMPROVEMENT_TYPE_MATCHES": (improvement, "ImprovementType")}[typ]
            v = actual == a[key]
        elif typ in ("REQUIREMENT_PLOT_RESOURCE_TYPE_MATCHES", "REQUIREMENT_PLOT_RESOURCE_CLASS_TYPE_MATCHES",
                      "REQUIREMENT_PLOT_IMPROVED_RESOURCE_CLASS_TYPE_MATCHES", "REQUIREMENT_PLOT_RESOURCE_TAG_MATCHES"):
            if visible is None:
                missing.add("资源揭示状态缺失")
            elif typ.endswith("RESOURCE_TYPE_MATCHES"):
                v = resource == a["ResourceType"]
            elif typ.endswith("RESOURCE_TAG_MATCHES"):
                v = a["Tag"] in self.r.tags[resource]
            else:
                v = self.r.resources.get(resource, {}).get("ResourceClassType") == a["ResourceClassType"]
                if "IMPROVED" in typ:
                    v = v and resource in self.r.valid_resources[improvement]
        elif typ == "REQUIREMENT_PLOT_RESOURCE_VISIBLE":
            v = visible
            missing.add("资源揭示状态缺失")
        elif typ == "REQUIREMENT_PLOT_TERRAIN_CLASS_MATCHES":
            v = terrain in self.r.terrain_classes[a["TerrainClass"]]
        elif typ == "REQUIREMENT_PLOT_FEATURE_TAG_MATCHES":
            v = a["Tag"] in self.r.tags[feature]
        elif typ in ("REQUIREMENT_PLOT_HAS_ANY_FEATURE", "REQUIREMENT_PLOT_HAS_ANY_IMPROVEMENT", "REQUIREMENT_PLOT_HAS_ANY_RESOURCE"):
            v = bool({"REQUIREMENT_PLOT_HAS_ANY_FEATURE": feature,
                      "REQUIREMENT_PLOT_HAS_ANY_IMPROVEMENT": self.name(tile.improvment),
                      "REQUIREMENT_PLOT_HAS_ANY_RESOURCE": resource}[typ])
            if typ.endswith("RESOURCE") and visible is None:
                v, missing = None, {"资源揭示状态缺失"}
        elif typ == "REQUIREMENT_PLOT_IS_APPEAL_BETWEEN":
            v = int(a.get("MinimumAppeal", -1000)) <= tile.appeal <= int(a.get("MaximumAppeal", 1000))
        elif typ in ("REQUIREMENT_PLOT_IS_HILLS", "REQUIREMENT_PLOT_IS_MOUNTAIN", "REQUIREMENT_PLOT_IS_IMPASSABLE",
                      "REQUIREMENT_PLOT_IS_LAKE", "REQUIREMENT_PLOT_IS_COAST"):
            v = {"REQUIREMENT_PLOT_IS_HILLS": bool(tr.get("Hills")),
                 "REQUIREMENT_PLOT_IS_MOUNTAIN": bool(tr.get("Mountain")),
                 "REQUIREMENT_PLOT_IS_IMPASSABLE": bool(tr.get("Impassable") or ft.get("Impassable")),
                 "REQUIREMENT_PLOT_IS_LAKE": self.lake(tile),
                 "REQUIREMENT_PLOT_IS_COAST": terrain == "TERRAIN_COAST"}[typ]
            if typ == "REQUIREMENT_PLOT_IS_LAKE" and v is None:
                missing.add("湖泊与海岸区分状态尚未解析")
        elif typ in ("REQUIREMENT_PLOT_ADJACENT_TO_RIVER", "REQUIREMENT_PLOT_IS_FRESH_WATER"):
            v = bool(tile.river & 0x3F)
            if typ.endswith("FRESH_WATER"):
                v |= bool(ft.get("AddsFreshWater")) or any(
                    self.r.features.get(self.name(self.state.tiles[j].feature), {}).get("AddsFreshWater")
                    or self.lake(self.state.tiles[j]) is True for j in adjacent)
                if not v and any(self.lake(self.state.tiles[j]) is None for j in adjacent):
                    v = None
                    missing.add("相邻水体的湖泊状态尚未解析")
        elif typ.startswith("REQUIREMENT_PLOT_ADJACENT_"):
            vals = []
            for j in adjacent:
                t = self.state.tiles[j]
                if typ == "REQUIREMENT_PLOT_ADJACENT_TO_OWNER":
                    # Improvement-origin modifiers ask adjacency to that plot.
                    vj = extra is not None and extra[0] in ("plot", "district") and j == extra[1]
                elif typ.endswith("TO_LAKE"):
                    vj = self.lake(t)
                elif typ.endswith("TO_COAST"):
                    vj = self.name(t.terrain) == "TERRAIN_COAST"
                elif typ.endswith("TO_MOUNTAIN"):
                    vj = bool(self.r.terrains.get(self.name(t.terrain), {}).get("Mountain"))
                elif typ.endswith("TO_NATURAL_WONDER"):
                    vj = bool(self.r.features.get(self.name(t.feature), {}).get("NaturalWonder"))
                elif typ.endswith("TO_WONDER"):
                    vj = any(self.r.buildings.get(bt, {}).get("IsWonder") for _, _, bt, _ in self.buildings[j])
                elif typ.endswith("FEATURE_TYPE_MATCHES"):
                    vj = self.name(t.feature) == a["FeatureType"]
                elif typ.endswith("IMPROVEMENT_TYPE_MATCHES"):
                    vj = self.improvement(t) == a["ImprovementType"]
                elif typ.endswith("DISTRICT_TYPE_MATCHES"):
                    entry = self.districts.get(j)
                    vj = bool(entry and entry[1].built and self.r.matches_district(self.name(entry[1].type), a["DistrictType"])
                              and (a.get("MustBeFunctioning", "1") == "0" or not entry[1].pillage))
                elif typ.endswith("BUILDING_TYPE_MATCHES"):
                    vj = any(bt == a["BuildingType"] and not pillaged for _, _, bt, pillaged in self.buildings[j])
                elif typ.endswith("RESOURCE_CLASS_TYPE_MATCHES"):
                    vis = self.visible_resource(t, p)
                    vj = None if vis is None else vis and self.r.resources.get(self.name(t.resource), {}).get("ResourceClassType") == a["ResourceClassType"]
                else:
                    vj = None
                vals.append((vj, {"相邻条件状态缺失：" + typ}))
            return combine(vals, True)
        else:
            missing.add("未覆盖条件：" + typ)
        return v, missing if v is None else set()

    def has_building(self, p, c, typ):
        return bool(p and c and H(typ) in c.built and (c.built[H(typ)] & 0xFFFF) != 0xFFFF
                    and not c.pillagedBuildings.get(H(typ)))

    def terrain_workable(self, terrain, traits):
        for trait in traits or ():
            for row in self.r.roots["trait"].get(trait, ()):
                mid = row["ModifierId"]
                effect = self.r.dynamic.get(self.r.modifiers[mid]["ModifierType"], {}).get("EffectType")
                args = self.r.args[mid]
                if effect == "EFFECT_ADJUST_PLAYER_TERRAIN_WORK_IMPASSABLE_MODIFIER" and args.get("TerrainType") == terrain and args.get("Ignore") == "1":
                    return True
        return False

    def apply_bcy(self, index, p, c, sums, breakdown, add, missing):
        if self.r.profile == "vanilla":
            return
        scope, mode = self.state.bcy.get("scope"), self.state.bcy.get("mode")
        if scope == -1:
            breakdown.append({"source": "BCY：关闭"})
            return
        if scope not in (0, 1):
            missing.add("BCY 应用范围缺失或冲突")
            return
        if not p or not c:
            missing.add("BCY 所属城市状态缺失")
            return
        palace = c.built.get(H("BUILDING_PALACE"))
        is_capital = palace is not None and (int(palace) & 0xFFFF) == index
        if scope == 1 and not is_capital:
            breakdown.append({"source": "BCY：仅首都，该城市中心无宫殿，不计入"})
            return
        if mode not in (0, 1, 2):
            missing.add("BCY 产出模式缺失或冲突")
            return
        tile = self.state.tiles[index]
        terrain = self.name(tile.terrain)
        tr = self.r.terrains[terrain]
        if tr.get("Water") or tr.get("Mountain"):
            return
        base = defaultdict(int)
        for row in breakdown:
            if row.get("yield") and row["source"] in ("地形", "地貌", "资源", "城市中心最低产出"):
                base[row["yield"]] += row["amount"]
        target = {str(H("YIELD_FOOD")): 2 if tr.get("Hills") else 3,
                  str(H("YIELD_PRODUCTION")): 2 if tr.get("Hills") else 1}
        label = {0: "BCY：平衡", 1: "BCY：消除随机", 2: "BCY：最大值"}[mode]
        if mode == 0:
            resource_visible = self.visible_resource(tile, p)
            strategic = self.r.resources.get(self.name(tile.resource), {}).get("ResourceClassType") == "RESOURCECLASS_STRATEGIC"
            if strategic and resource_visible is None:
                missing.add("BCY 战略资源揭示状态缺失")
                return
            if (terrain in ("TERRAIN_GRASS", "TERRAIN_PLAINS")
                    and base[str(H("YIELD_FOOD"))] == 2 and base[str(H("YIELD_PRODUCTION"))] == 1
                    and not any(v for key, v in base.items() if key not in target)
                    and not (strategic and resource_visible)):
                add("YIELD_PRODUCTION", 1, label)
        elif mode == 2:
            for key, minimum in target.items():
                add(self.r.types[int(key)], max(0, minimum - base[key]), label)
        else:
            for yield_type in SIX:
                key = str(H(yield_type))
                add(yield_type, target.get(key, 0) - base[key], label)
        # Natural-wonder correction scripts can leave historical properties.
        if self.r.features.get(self.name(tile.feature), {}).get("NaturalWonder") or any(
                self.r.features.get(self.name(self.state.tiles[j].feature), {}).get("NaturalWonder")
                for j in self.adjacent(index)):
            missing.add("BCY 自然奇观 Lua 历史修正尚未解析")

    def modifiers(self, index, p, c, add, missing):
        tile = self.state.tiles[index]
        if tile.iPlayer == 0xFFFF:
            return  # Unowned plots have no skill/effect context by user policy.
        candidates = list(self.public_roots)
        if p and c:
            candidates += self.city_roots[p.iPlayer, c.id]
        # Both the target improvement and neighboring improvements can own
        # modifiers. Collection scope/requirements decide their recipients.
        for origin in [index, *self.adjacent(index)]:
            imp = self.improvement(self.state.tiles[origin])
            for row in self.r.roots["improvement"].get(imp, ()):
                candidates.append((row.get("ModifierId", row.get("ModifierID")), p, c, ("plot", origin)))
        # Each museum owns a city modifier. All active museums in this city
        # contribute, even when the source is beyond the target's neighbors.
        # This also reproduces the game's stacking when one city owns several.
        if p and c:
            candidates.extend((mid, p, c, ("plot", origin))
                              for mid, origin in self.city_improvement_roots[p.iPlayer, c.id])
        district = self.districts.get(index)
        if district and district[1].built and not district[1].pillage:
            for row in self.r.roots["district"].get(self.name(district[1].type), ()):
                candidates.append((row["ModifierId"], p, c, ("plot", index)))
        seen = set()
        expanded = []
        for candidate in candidates:
            root, sp, sc, extra = candidate
            if any(self.r.dynamic[self.r.modifiers[mid]["ModifierType"]]["CollectionType"] == "COLLECTION_PLAYER_DISTRICTS"
                   for chain in self.r.chains.get(root, ()) for mid in chain):
                for origin in self.adjacent(index):
                    entry = self.districts.get(origin)
                    if entry and p and entry[0] == p.iPlayer and entry[1].built and not entry[1].pillage:
                        expanded.append((root, sp, sc, ("district", origin)))
            else:
                expanded.append(candidate)
        for root, sp, sc, extra in expanded:
            for chain in self.r.chains.get(root, ()):
                terminal = chain[-1]
                m = self.r.modifiers[terminal]
                dyn = self.r.dynamic[m["ModifierType"]]
                scope, effect = dyn["CollectionType"], dyn["EffectType"]
                if effect == TERRAIN_CITIES_EFFECT:
                    args = self.r.args[terminal]
                    if not p or not c or self.improvement(tile) != args.get("ImprovementType"):
                        continue
                    if not extra or extra[0] != "plot":
                        missing.add("建城地形产出效果的来源改良缺失")
                        continue
                    source = self.state.tiles[extra[1]]
                    if (source.iPlayer, source.iCity) != (p.iPlayer, c.id):
                        continue
                if scope == "COLLECTION_SINGLE_PLOT_YIELDS" and (not extra or extra[0] != "plot" or extra[1] != index):
                    continue
                if scope in ("COLLECTION_PLAYER_PLOT_YIELDS", "COLLECTION_CITY_PLOT_YIELDS", "COLLECTION_PLAYER_CITIES") and not p:
                    continue
                if scope == "COLLECTION_CITY_PLOT_YIELDS" and len(chain) == 1 and sc and (not c or sc.id != c.id):
                    continue
                allowed_scope = scope in ("COLLECTION_SINGLE_PLOT_YIELDS", "COLLECTION_PLAYER_PLOT_YIELDS",
                                         "COLLECTION_CITY_PLOT_YIELDS", "COLLECTION_ALL_PLOT_YIELDS", "COLLECTION_PLAYER_CITIES")
                allowed_scope |= scope == "COLLECTION_OWNER" and effect == TERRAIN_CITIES_EFFECT
                if not allowed_scope:
                    missing.add("未覆盖作用范围：" + scope)
                    continue
                if extra and extra[0] == "plot" and scope == "COLLECTION_PLAYER_PLOT_YIELDS":
                    owner = self.state.tiles[extra[1]].iPlayer
                    if not p or owner != p.iPlayer:
                        continue
                vals = []
                for mid in chain:
                    mod = self.r.modifiers[mid]
                    intermediate_scope = self.r.dynamic[mod["ModifierType"]]["CollectionType"]
                    condition_index = extra[1] if extra and extra[0] == "district" and intermediate_scope == "COLLECTION_PLAYER_DISTRICTS" else index
                    vals += [self.condition(mod.get(key), condition_index, p, c, sp, sc, extra)
                             for key in ("OwnerRequirementSetId", "SubjectRequirementSetId")]
                if extra and extra[0] == "governor":
                    vals.append((vars(extra[1]).get("established"), {"总督就任状态尚未解析"}))
                eligible, reasons = combine(vals)
                if eligible is False:
                    continue
                args = self.r.args[terminal]
                if m.get("OwnerStackLimit") or m.get("SubjectStackLimit") or m.get("Repeatable"):
                    missing.add("特殊效果叠加状态尚未解析：" + root)
                    continue
                if effect == TERRACE_EFFECT:
                    if self.name(tile.terrain) != args.get("TerrainType"):
                        continue
                    count = sum(self.improvement(self.state.tiles[j]) == args["ImprovementType"] for j in self.adjacent(index))
                elif effect == TERRAIN_CITIES_EFFECT:
                    count, gaps = self.terrain_city_count(p)
                    if gaps:
                        missing.update(gaps)
                        continue
                else:
                    count = 1
                if not count:
                    continue
                identity = (root, terminal, sp.iPlayer if sp else None,
                            sc.id if sc else None, extra[1] if extra and extra[0] in ("plot", "district") else None)
                if identity in seen:
                    continue
                seen.add(identity)
                if eligible is None:
                    missing.update(reasons)
                    continue
                if any(self.r.modifiers[mid].get("RunOnce") or self.r.modifiers[mid].get("Permanent")
                       or self.r.modifiers[mid].get("NewOnly") for mid in chain):
                    missing.add("历史效果生效状态尚未解析：" + root)
                    continue
                for y, amount in zip(args.get("YieldType", "").split(","), args.get("Amount", "0").split(",")):
                    y = y.strip()
                    if y in SIX:
                        note = f"{count} 种城市中心地形，每种 +{amount}" if effect == TERRAIN_CITIES_EFFECT else None
                        add(y, int(amount) * count, "规则加成", root, note)

    def adjacency_count(self, row, index, p):
        if row.get("Self"):
            return 1
        if row.get("AdjacentRiver"):
            return int(bool(self.state.tiles[index].river & 0x3F))
        count, missing = 0, False
        for j in self.adjacent(index):
            t = self.state.tiles[j]
            d = self.districts.get(j)
            checks = []
            if row.get("OtherDistrictAdjacent"):
                checks.append(bool(d and d[1].built))
            if row.get("AdjacentDistrict"):
                checks.append(bool(d and d[1].built and self.name(d[1].type) == row["AdjacentDistrict"]))
            for field, actual in (("AdjacentTerrain", self.name(t.terrain)), ("AdjacentFeature", self.name(t.feature)),
                                  ("AdjacentImprovement", self.improvement(t))):
                if row.get(field):
                    checks.append(actual == row[field])
            if row.get("AdjacentNaturalWonder"):
                checks.append(bool(self.r.features.get(self.name(t.feature), {}).get("NaturalWonder")))
            if row.get("AdjacentWonder"):
                checks.append(any(self.r.buildings.get(bt, {}).get("IsWonder") for _, _, bt, _ in self.buildings[j]))
            cls = row.get("AdjacentResourceClass", "NO_RESOURCECLASS")
            if row.get("AdjacentResource") or row.get("AdjacentSeaResource") or cls != "NO_RESOURCECLASS":
                visible = self.visible_resource(t, p)
                checks.append(None if visible is None else visible and (
                    (bool(row.get("AdjacentResource")))
                    or (bool(row.get("AdjacentSeaResource")) and bool(self.r.terrains.get(self.name(t.terrain), {}).get("Water")))
                    or self.r.resources.get(self.name(t.resource), {}).get("ResourceClassType") == cls))
            matched, _ = combine([(v, set()) for v in checks], True)
            missing |= matched is None
            count += matched is True
        return None if missing else count

    def calculate(self, index):
        t, r = self.state.tiles[index], self.r
        p = self.players.get(t.iPlayer)
        c = self.cities.get((t.iPlayer, t.iCity))
        terrain, feature, imp = self.name(t.terrain), self.name(t.feature), self.improvement(t)
        if terrain not in r.terrains:
            return result(missing=["未知地形，无法计算"], unavailable=True)
        sums, breakdown, missing = defaultdict(int), [], set()
        def add(y, amount, source, typ=None, note=None):
            if y not in SIX:
                return
            if amount or note:
                key = str(H(y))
                sums[key] += amount
                entry = {"yield": key, "amount": amount, "source": source}
                if typ:
                    entry["type"] = typ
                    # Keep the effect ID for diagnostics, but group its yields
                    # under the belief/promotion/etc. that supplies the effect.
                    entry["sourceType"] = r.source_types.get(typ, typ)
                    entry["name"] = self.label(entry["sourceType"])
                if note:
                    entry["note"] = note
                breakdown.append(entry)
        d = self.districts.get(index)
        center = bool(d and self.name(d[1].type) == "DISTRICT_CITY_CENTER") or bool(c and c.x == index % self.state.width and c.y == index // self.state.width)
        if (d and not center) or any(r.buildings.get(bt, {}).get("IsWonder") for _, _, bt, _ in self.buildings[index]) or (t.wonder & NONE_U32) != NONE_U32:
            return result(breakdown=[{"source": "区域或奇观占地，不计可工作地块产出"}])
        if not p and t.iPlayer != 0xFFFF:
            missing.add("所属玩家状态缺失")
        elif not p:
            breakdown.append({"source": "无主地块：计入全部资源，不计技能加成"})
        elif not c:
            missing.add("所属城市状态缺失")
        if p and self.state.tailWarnings:
            missing.add("玩家状态解析不完整")
        if self.has_skills(p) and (p.iPlayer not in self.infos or r.traits(self.infos[p.iPlayer]) is None):
            missing.add("文明或领袖能力状态缺失")
        if self.has_skills(p) and c and self.beliefs(p, c) is None:
            missing.add("城市信仰状态缺失")
        ft = r.features.get(feature, {})
        if feature and feature not in r.features:
            missing.add("地貌规则缺失：" + feature)
        if imp and imp not in r.improvements:
            missing.add("改良规则缺失：" + imp)
        missing.update(r.improvement_yield_gaps.get(imp, ()))
        traits = r.traits(self.infos[p.iPlayer]) if self.has_skills(p) and p.iPlayer in self.infos else set()
        if ft.get("Impassable") or (r.terrains[terrain].get("Impassable") and not self.terrain_workable(terrain, traits)):
            return result(breakdown=[{"source": "不可工作地形或自然奇观"}], missing=missing)
        if imp and not r.improvements.get(imp, {}).get("Workable", 1):
            return result(breakdown=[{"source": "改良使地块不可工作", "type": imp}], missing=missing)
        # Workable natural wonders replace underlying terrain yields.
        if not ft.get("NaturalWonder"):
            for row in r.base["terrain"].get(terrain, ()):
                add(row["YieldType"], row["YieldChange"], "地形", terrain)
            if any(r.features.get(self.name(self.state.tiles[j].feature), {}).get("DoubleAdjacentTerrainYield") for j in self.adjacent(index)):
                for row in r.base["terrain"].get(terrain, ()):
                    add(row["YieldType"], row["YieldChange"], "自然奇观使地形产出翻倍", "FEATURE_TORRES_DEL_PAINE")
        for row in r.base["feature"].get(feature, ()):
            add(row["YieldType"], row["YieldChange"], "地貌", feature)
        for j in self.adjacent(index):
            for row in r.feature_adj.get(self.name(self.state.tiles[j].feature), ()):
                add(row["YieldType"], row["YieldChange"], "自然奇观相邻", row["FeatureType"])
        resource = self.name(t.resource)
        if (t.resource & NONE_U32) != NONE_U32 and resource not in r.resources:
            missing.add("资源规则缺失")
        if resource:
            visible = self.visible_resource(t, p)
            if visible is None:
                missing.add("资源揭示所需科技或市政状态缺失")
            for row in r.base["resource"].get(resource, ()):
                add(row["YieldType"], row["YieldChange"] if visible is True else 0, "资源", resource,
                    None if visible is True else "未揭示，不计入")
        if (t.pillage & 1) and (t.improvment & NONE_U32) != NONE_U32:
            breakdown.append({"source": "改良已被掠夺，改良产出与升级不计入", "type": self.name(t.improvment)})
        if imp and not center:
            for row in r.base["improvement"].get(imp, ()):
                add(row["YieldType"], row["YieldChange"], "改良", imp)
            for row in r.bonuses.get(imp, ()):
                active, reasons = self.gate(row, p)
                if active is None:
                    missing.update(reasons)
                add(row["YieldType"], row["BonusYieldChange"] if active is True else 0,
                    "科技／市政升级", row.get("PrereqTech") or row.get("PrereqCivic"),
                    None if active is True else "未完成或状态未知，不计入")
            for link in r.improvement_adj.get(imp, ()):
                row = r.rules[link["YieldChangeId"]]
                active, reasons = self.gate(row, p)
                if active is None:
                    missing.update(reasons)
                elif active:
                    count = self.adjacency_count(row, index, p)
                    if count is None:
                        missing.add("改良相邻资源揭示状态缺失")
                    else:
                        add(row["YieldType"], (count // max(1, row["TilesRequired"])) * row["YieldChange"], "改良相邻", imp)
            ir = r.improvements.get(imp, {})
            if ir.get("YieldFromAppeal"):
                add(ir["YieldFromAppeal"], max(0, t.appeal) * ir["YieldFromAppealPercent"] // 100, "魅力", imp)
        if center:
            for y in ("YIELD_FOOD", "YIELD_PRODUCTION"):
                minimum = int(r.params[y + "_CITY_TERRAIN_REPLACE"])
                add(y, max(0, minimum - sums[str(H(y))]), "城市中心最低产出")
            self.apply_bcy(index, p, c, sums, breakdown, add, missing)
        self.modifiers(index, p, c, add, missing)
        # Preserve buildings are tied to each neighboring built preserve, not
        # to the target city's buildings; two preserves can both contribute.
        if (t.improvment & NONE_U32) == NONE_U32:
            for j in self.adjacent(index):
                entry = self.districts.get(j)
                if not entry or not entry[1].built or entry[1].pillage:
                    continue
                for row in r.tables["Adjacent_AppealYieldChanges"]:
                    if self.name(entry[1].type) == row["DistrictType"] and row["MinimumValue"] <= t.appeal <= row["MaximumValue"]:
                        if any(bt == row["BuildingType"] and not pillaged for _, _, bt, pillaged in self.buildings[j]):
                            add(row["YieldType"], row["YieldChange"], "保护区建筑相邻", row["BuildingType"])
        for key, value in list(sums.items()):
            if value < 0:
                add(r.types[int(key)], -value, "产出下限")
        return result({k: v for k, v in sums.items() if v}, breakdown, missing)


def calculate_tile_yields(state, *, wrap_x=None, rules=None):
    # CCB can incorporate BBG as a dependency. Its final merged rules take
    # precedence over a BBG package name, without changing global MOD detection.
    titles = [*state.mods, *(str(m.get(field, "")) for m in state.modPackages
                            for field in ("key", "name"))]
    is_ccb = any(re.search(r"\bccb\b|和而不同", str(title), re.I) for title in titles)
    profile = "ccb" if is_ccb else (balance_mod(titles) or state.balanceMod or "vanilla").lower()
    rules = rules or get_rules(profile)
    reason = None
    if not rules or rules.profile != profile:
        reason = f"{profile.upper()} 单元格产出规则尚未采集"
    elif state.unsupported:
        reason = "该玩法不支持单元格产出计算"
    elif blacklisted_mods(titles):
        reason = "存档带有不支持的 MOD，无法计算单元格产出"
    elif any(getattr(e, "section", "") in ("map", "players_info", "links") for e in state.layerErrors):
        reason = "地图或归属状态解析失败"
    elif state.width <= 0 or state.height <= 0 or len(state.tiles) != state.width * state.height:
        reason = "地图尺寸不完整"
    if reason:
        return [result(missing=[reason], unavailable=True) for _ in state.tiles]
    if wrap_x is None:
        wrap_x = bool(_wrap_map().get(state.map_key, True))
    turn = TurnYields(state, rules, wrap_x)
    return [turn.calculate(i) for i in range(len(state.tiles))]
