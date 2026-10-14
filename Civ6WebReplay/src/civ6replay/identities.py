"""Static TYPE -> identity lookup (name / icon / kind / city-state flavour).

The bundled ``data/vanilla/identities.json`` artifact is produced by
``tools/build_identities.py``.  Hashes are recomputed from the stored TYPE
strings while loading, so the file stays a plain, reviewable list of TYPE
strings and names.

``data/shared/identities.json`` supplements it with mod additions. Both BBG
and CCB share TYPE keys and PNGs; ``profiles.ccb`` carries translated names
and the Tibetan UU icon variant. Runtime needs no installed mods.

The directory is intentionally independent from the live game install: it
covers the 77 leaders (matching ``colors.LEADER_COLORS``), every major
civilization, the 54 city-states (matching ``colors.CITY_STATE_FLAVOUR``),
free cities / barbarians, and the terrain / feature rows that are missing from
stripped ``DebugGameplay.sqlite`` caches.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from .hash import crc32_type

IDENTITIES_JSON = (Path(__file__).resolve().parents[2] / "data" / "vanilla"
                   / "identities.json")
SHARED_IDENTITIES_JSON = (Path(__file__).resolve().parents[2] / "data" / "shared"
                          / "identities.json")


class Identities:
    def __init__(self, path: Path | str = IDENTITIES_JSON,
                 shared_path: Path | str | None = None):
        self.path = Path(path)
        self.entries: Dict[int, dict] = {}
        self.by_type: Dict[str, dict] = {}
        paths = [self.path]
        if shared_path is not None:
            paths.append(Path(shared_path))
        elif self.path.resolve() == IDENTITIES_JSON.resolve():
            paths.append(SHARED_IDENTITIES_JSON)
        for source in paths:
            if not source.exists():
                continue
            doc = json.loads(source.read_text(encoding="utf-8"))
            for row in doc.get("entries", []):
                type_str = row.get("type")
                if not type_str:
                    continue
                h = crc32_type(type_str) & 0xFFFFFFFF
                # A shared entry may only add an icon to an existing identity;
                # preserve base attributes such as civilization and flavour.
                row = {**self.by_type.get(type_str, {}), **row}
                row["hash"] = h
                self.entries[h] = row
                self.by_type[type_str] = row

    @property
    def available(self) -> bool:
        return bool(self.entries)

    # --- lookups -----------------------------------------------------------
    def entry(self, h, profile: str = "") -> Optional[dict]:
        row = self.entries.get(h & 0xFFFFFFFF)
        override = row.get("profiles", {}).get(profile.lower()) if row else None
        return {**row, **override} if override else row

    def name_zh(self, h, profile: str = "") -> str:
        e = self.entry(h, profile)
        return e.get("zh", "") if e else ""

    def name_en(self, h, profile: str = "") -> str:
        e = self.entry(h, profile)
        return e.get("en", "") if e else ""

    def name(self, h, profile: str = "", lang: str = "zh") -> str:
        e = self.entry(h, profile)
        if not e:
            return ""
        if lang == "en":
            base = self.entries.get(h & 0xFFFFFFFF, {})
            override = base.get("profiles", {}).get(profile.lower(), {})
            if override.get("zh") and override.get("zh") != base.get("zh") and not override.get("en"):
                return override["zh"]
        return (e.get(lang) or e.get("zh") or e.get("en") or "")

    def type_str(self, h) -> str:
        e = self.entry(h)
        return e.get("type", "") if e else ""

    def icon(self, h, profile: str = "") -> Optional[str]:
        e = self.entry(h, profile)
        return e.get("icon") if e else None

    def kind(self, h) -> str:
        e = self.entry(h)
        return e.get("kind", "") if e else ""

    def flavour(self, h) -> str:
        """City-state flavour (Simplified Chinese) for a civ hash."""
        e = self.entry(h)
        return e.get("flavour", "") if e else ""


_SINGLETON: Optional[Identities] = None


def get_identities() -> Identities:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Identities()
    return _SINGLETON
