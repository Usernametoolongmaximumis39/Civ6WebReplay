"""Names from the bundled official TYPE/Name-tag snapshot and profile catalogs."""
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def name_tags():
    path = Path(__file__).resolve().parents[2] / "data/vanilla/great-people.json"
    return json.loads(path.read_text(encoding="utf-8"))


def individual_name(typ, profile="vanilla", lang="zh"):
    from .localization import game_text
    return game_text(name_tags().get(typ, "LOC_" + typ + "_NAME"), profile or "vanilla", lang)
