"""Version labels from captured data and save headers, never installed MODs."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

from .mod_identity import (CORE_IDS, EXPANSION_IDS, CHANNEL_LABELS, clean_title,
                           component_role, identify_package)

ROOT = Path(__file__).resolve().parents[2]


def component_versions(profile, packages, sources=()):
    if profile not in CORE_IDS:
        return []
    result = []
    for role, label in (("core", profile.upper()), ("expansion", profile.upper() + "拓展")):
        rows = [p for p in packages if component_role(p, profile) == role]
        origin = [s for s in sources if component_role(s, profile) == role]
        identities = [identify_package(p) for p in (*rows, *origin)]
        versions = {p["version"] for p in identities if p["version"]}
        channels = {p["channel"] for p in identities if p["channel"]}
        channel = next(iter(channels)) if len(channels) == 1 else "conflict" if channels else None
        source = origin[0] if len(origin) == 1 else {}
        result.append({"component": label, "role": role,
                       "version": next(iter(versions)) if len(versions) == 1 else None,
                       "installedVersion": source.get("version"),
                       "rootVersion": source.get("rootVersion"),
                       "propertyVersion": source.get("propertyVersion"),
                       "channel": channel,
                       "isBeta": None if channel in (None, "conflict") else channel == "beta",
                       **({"absent": True} if not rows and not origin else {})})
    return result


def format_versions(rows):
    def describe(row):
        label = row["component"]
        if row.get("absent"):
            return label + " 未启用"
        if channel := CHANNEL_LABELS.get(row.get("channel")):
            label += " " + channel
        elif row.get("channel") == "conflict":
            label += " 渠道冲突"
        return label + " " + (row.get("version") or
            ("安装版本 " + str(row["installedVersion"]) if row.get("installedVersion") else "未记录"))
    return "；".join(describe(row) for row in rows)


def database_versions(profile, root=ROOT):
    directory = Path(root) / "data/gamedb" / profile
    for name in ("capture.json", "tileyields.json", "adjacency.json"):
        try:
            doc = json.loads((directory / name).read_text(encoding="utf-8"))
            if doc.get("profile") != profile:
                continue
            packages = doc.get("enabledPackages", doc.get("packages", []))
            return component_versions(profile, packages, doc.get("sources", doc.get("modSources", [])))
        except (OSError, ValueError, TypeError):
            continue
    return []


def version_info(profile, packages, root=ROOT):
    return {"database": database_versions(profile, root),
            "save": component_versions(profile, packages)}


@lru_cache(maxsize=32)
def _file_digest(path, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata_token(root=ROOT):
    paths = [Path(root) / "data/mods/governor_promotions.json",
             Path(root) / "data/shared/identities.json"]
    paths += [Path(root) / "data/gamedb" / p / name
              for p in ("vanilla", "bbg", "ccb") for name in ("adjacency.json", "capture.json")]
    values = []
    for path in paths:
        try:
            st = path.stat()
            values.append(_file_digest(str(path), (st.st_mtime_ns, st.st_size)))
        except OSError:
            values.append("missing")
    return hashlib.sha256("|".join(values).encode()).hexdigest()
