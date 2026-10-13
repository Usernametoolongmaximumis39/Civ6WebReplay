"""Profile-isolated, bundled policy and civilization/leader ability text."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "data/gamedb"


class RuleText:
    def __init__(self, doc=None):
        self.doc = doc or {}
        self.entries = self.doc.get("entries", {})

    def entry(self, h):
        row = self.entries.get(str(int(h) & 0xFFFFFFFF))
        if not row:
            return None
        zh, en = row.get("zh", {}), row.get("en", {})
        return {"type": row["type"], "kind": row["kind"],
                "name": zh.get("name") or en.get("name") or "",
                "description": zh.get("description") or en.get("description") or ""}

    def abilities(self, civilization, leader):
        def skills(hashes):
            out = []
            for h in dict.fromkeys(hashes):
                row = self.entries.get(str(h), {})
                entry = self.entry(h)
                # Internal traits and unique-content gates have no player-facing
                # skill description. Keep named skills even if their text is missing.
                tag = row.get("descriptionTag") or ""
                if (entry and entry["name"] and tag and not row.get("internalOnly")
                        and not row.get("uniqueContent")
                        and not tag.startswith("LOC_LOADING_UNIQUE_")):
                    out.append(entry)
            return out
        civ_key, leader_key = (str(int(h or 0) & 0xFFFFFFFF) for h in (civilization, leader))
        leader_traits, visited = [], set()
        while leader_key and leader_key not in visited:
            visited.add(leader_key)
            leader_traits.extend(self.doc.get("leaders", {}).get(leader_key, []))
            leader_key = self.doc.get("leaderParents", {}).get(leader_key)
        return {"civilization": skills(self.doc.get("civilizations", {}).get(civ_key, [])),
                "leader": skills(leader_traits)}


def rule_text_token():
    return tuple((p.parent.name, p.stat().st_mtime_ns, p.stat().st_size)
                 for p in sorted(ROOT.glob("*/rule-text.json")))


@lru_cache(maxsize=8)
def _load(path, modified, size):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return RuleText(doc) if doc.get("profile") == Path(path).parent.name else RuleText()


def get_rule_text(profile):
    if profile not in ("vanilla", "bbg", "ccb"):
        return RuleText()
    path = ROOT / profile / "rule-text.json"
    if not path.is_file():
        return RuleText()
    stamp = path.stat()
    return _load(str(path), stamp.st_mtime_ns, stamp.st_size)
