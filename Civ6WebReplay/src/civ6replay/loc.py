"""Runtime access to the bundled localization snapshot (``data/vanilla/loc.json``).

The artifact is produced by ``tools/build_loc.py`` from the game's ``Text`` XML
so the app can render city / civilization names without depending on the live
install (the game's own ``DebugLocalization.sqlite`` cache is missing several
rows, e.g. ``LOC_CITY_NAME_AYUTTHAYA``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

LOC_JSON = Path(__file__).resolve().parents[2] / "data" / "vanilla" / "loc.json"


class Loc:
    def __init__(self, path: Path | str = LOC_JSON):
        self.path = Path(path)
        self.source = ""
        self.city: Dict[str, dict] = {}
        self.civ: Dict[str, dict] = {}
        self.names: Dict[str, dict] = {}
        self.civ_tag: Dict[str, str] = {}
        if self.path.exists():
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = {}
            self.source = doc.get("source", "")
            self.city = doc.get("city", {}) or {}
            self.civ = doc.get("civ", {}) or {}
            self.names = doc.get("names", {}) or {}
            self.civ_tag = doc.get("civ_tag", {}) or {}

    @property
    def available(self) -> bool:
        return bool(self.city or self.civ or self.names)

    @staticmethod
    def _pair(section: Dict[str, dict], tag: str) -> Tuple[str, str]:
        rec = section.get(tag)
        if not rec:
            return "", ""
        return (rec.get("zh") or "", rec.get("en") or "")

    def city_name(self, tag: str) -> Tuple[str, str]:
        """City LOC tag -> ``(zh, en)`` (either side may be empty)."""
        if not tag:
            return "", ""
        zh, en = self._pair(self.city, tag)
        if not zh and not en and not tag.startswith("LOC_"):
            zh, en = self._pair(self.city, "LOC_CITY_NAME_" + tag)
            if not zh and not en:
                zh, en = self._pair(self.city, "LOC_CITY_" + tag)
        return zh, en

    def name(self, tag: str) -> str:
        """Any snapshotted LOC tag -> display string (units / buildings / …)."""
        if not tag:
            return ""
        for section in (self.names, self.civ, self.city):
            zh, en = self._pair(section, tag)
            if zh or en:
                return zh or en
        return ""

    def civ_name(self, tag: str) -> str:
        """Civilization display name for a LOC tag or a bare ``CIVILIZATION_X``."""
        if not tag:
            return ""
        if tag.startswith("LOC_"):
            zh, en = self._pair(self.civ, tag)
            return zh or en
        # the gameplay XML is authoritative: a few legacy TYPEs point at another
        # name tag (``CIVILIZATION_JAKARTA`` -> Bandar Brunei / 斯里巴加湾)
        hint = self.civ_tag.get(tag)
        if hint:
            zh, en = self._pair(self.civ, hint)
            if zh or en:
                return zh or en
        for suffix in ("_NAME", "_FRONTEND_NAME"):
            zh, en = self._pair(self.civ, "LOC_" + tag + suffix)
            if zh or en:
                return zh or en
        return ""


_SINGLETON: Loc | None = None


def get_loc() -> Loc:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Loc()
    return _SINGLETON
