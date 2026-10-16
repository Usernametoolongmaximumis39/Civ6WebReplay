"""Production prices from saved player costs and distributable rules.

Production-rate bonuses (policies, Congress, etc.) change progress per turn,
not the required production. They must never be divided into this price.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from .gamedb import get_gamedb

RULES_PATH = Path(__file__).resolve().parents[2] / "data/production-costs.json"


@lru_cache(maxsize=1)
def _load_rules():
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8")).get("profiles", {})
    except (OSError, ValueError, TypeError):
        return {}


def rules_for(profile):
    return _load_rules().get(profile, {})


def game_progress(player):
    """Whole percentage, using the more advanced research tree (including future nodes)."""
    fractions = []
    for tree in player.techDogmeInfo:
        if not tree.found:
            return None
        fractions.append(sum(bool(v) for v in tree.found.values()) / len(tree.found))
    return min(100, math.floor(100 * max(fractions)))


def formation_discount(player, city, domain, rules, civilization):
    buildings = {k & 0xFFFFFFFF for k, v in city.built.items()
                 if v & 0xFFFF != 0xFFFF and not city.pillagedBuildings.get(k)}
    districts = {d.type & 0xFFFFFFFF for d in player.districts
                 if d.cityId == city.id and d.built and not d.pillage}
    civics = player.techDogmeInfo[1].found
    total = 0
    for rule in rules.get("formationDiscounts", []):
        if rule["domain"] != domain:
            continue
        if "BuildingType" in rule and rule["BuildingType"] not in buildings:
            continue
        if "DistrictType" in rule and rule["DistrictType"] not in districts:
            continue
        if "CivicType" in rule and not civics:
            return None
        if "civilizations" in rule and civilization is None:
            return None
        if "CivicType" in rule and not civics.get(rule["CivicType"]):
            continue
        if "civilizations" in rule and civilization not in rule["civilizations"]:
            continue
        total += rule["amount"]
    return min(100, total)


def current_cost(player, city, profile, speed, civilization=None):
    if not city.currentProds:
        return None
    h = city.currentProds[0] & 0xFFFFFFFF
    rules = rules_for(profile)
    row = rules.get("items", {}).get(str(h), {})
    typ = row.get("type") or get_gamedb().type_str(h)
    if typ.startswith("DISTRICT_"):
        return next((d.cost for d in player.districts
                     if d.cityId == city.id and d.type & 0xFFFFFFFF == h and d.cost > 0), None)
    is_unit = typ.startswith("UNIT_") or (city.currentProdKinds and city.currentProdKinds[0] == 0)
    # These are already integer prices after game speed and dynamic escalation.
    cost = player.unitCosts.get(h) if is_unit else None
    if cost is None:
        cost = row.get("cost")
        if cost is None and profile == "vanilla" and typ.startswith("BUILDING_"):
            cost = (get_gamedb().row("buildings", h) or {}).get("cost")
            row = {"model": "NO_PROGRESSION_MODEL"}
        if cost is None or cost <= 0:
            return None
        model, param = row.get("model"), row.get("param", 0)
        if model == "COST_PROGRESSION_PREVIOUS_COPIES":
            if h not in player.unitCopies:
                return None
            cost += param * player.unitCopies[h]
        elif model == "COST_PROGRESSION_GAME_PROGRESS":
            progress = game_progress(player)
            if progress is None:
                return None
            cost *= 1 + (param / 100 - 1) * progress / 100
        elif model not in ("NO_COST_PROGRESSION", "NO_PROGRESSION_MODEL"):
            return None
        multiplier = rules.get("speeds", {}).get(speed)
        if multiplier is None:
            return None
        # The game truncates (65 production on Online is 32, not 33).
        cost = math.floor(cost * multiplier / 100 + 1e-9)
    if cost <= 0:
        return None
    formation = city.currentProdFormations[0] if city.currentProdFormations else 0
    if is_unit and formation:
        if formation not in (1, 2):
            return None
        domain = row.get("domain") or (get_gamedb().row("units", h) or {}).get("domain")
        if not domain or not rules:
            return None
        discount = formation_discount(player, city, domain, rules, civilization)
        if discount is None:
            return None
        cost = math.floor(cost * (formation + 1) * (100 - discount) / 100 + 1e-9)
    return max(1, cost)
