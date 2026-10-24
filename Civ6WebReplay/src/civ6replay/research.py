"""Saved research investments and profile/world-era adjusted research prices."""
from functools import lru_cache
import json
import math
from pathlib import Path

from .hash import crc32_type

ERAS = ('ERA_ANCIENT', 'ERA_CLASSICAL', 'ERA_MEDIEVAL', 'ERA_RENAISSANCE',
        'ERA_INDUSTRIAL', 'ERA_MODERN', 'ERA_ATOMIC', 'ERA_INFORMATION', 'ERA_FUTURE')
ERA_HASHES = {crc32_type(era): era for era in ERAS}
RULES_PATH = Path(__file__).resolve().parents[2] / 'data/research-costs.json'


@lru_cache(maxsize=1)
def rules():
    return json.loads(RULES_PATH.read_text(encoding='utf-8'))['profiles']


def research_cost(h, tree, profile, speed, world_era):
    config = rules().get(profile, {})
    row = config.get('items', {}).get(str(h & 0xffffffff))
    multiplier = config.get('speeds', {}).get(speed)
    if (not row or row.get('repeatable') or multiplier is None
            or world_era not in ERAS or row['era'] not in ERAS):
        return None
    era_delta = ERAS.index(row['era']) - ERAS.index(world_era)
    percent = 0
    if era_delta:
        suffix = 'AFTER' if era_delta > 0 else 'BEFORE'
        percent = config.get('parameters', {}).get(f'{tree}_COST_PERCENT_CHANGE_{suffix}_GAME_ERA')
        if percent is None:
            return None
    # The engine applies each multiplier to 1/256 fixed-point values, then
    # returns the integer part. Era distance does not compound the adjustment.
    fixed = int(row['cost']) * 256
    fixed = fixed * (100 + percent) // 100
    fixed = fixed * multiplier // 100
    return max(1, fixed // 256)


def research_details(player, profile, speed, world_era):
    result = {}
    for index, (key, tree) in enumerate((('tech', 'TECH'), ('civic', 'CIVIC'))):
        info = player.techDogmeInfo[index]
        entries = {}
        for raw in info.current:
            h = raw & 0xffffffff
            progress = info.progress.get(h)
            # Sparse save maps omit untouched items. An absent map is unknown.
            if progress is None and info.found and h in info.found:
                progress = 0
            if progress is not None and (not math.isfinite(progress) or progress < 0):
                progress = None
            entries[str(h)] = {'progress': progress,
                              'cost': research_cost(h, tree, profile, speed, world_era)}
        result[key + 'Research'] = entries
    return result
