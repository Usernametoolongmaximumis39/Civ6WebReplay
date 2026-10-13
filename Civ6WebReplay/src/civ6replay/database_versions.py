"""Version labels from captured data and save headers, never installed MODs."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
CORE_IDS = {"bbg": "cb84075d-5007-4207-b662-c35a5f7be260",
            "ccb": "8af4fe8e-5406-7d72-d9d6-a8f5d1b66e00"}
EXPANSION_IDS = {"bbg": "2a0aa96a-a31c-4ce2-87ec-09152f6f3e00",
                 "ccb": "8af4fe8e-5406-7d72-d9d6-a8f5d1b66e30"}


def clean_title(title):
    return re.sub(r"\[(?:COLOR[^\]]*|ENDCOLOR)\]", "", str(title or "")).strip()


def component_role(package, profile):
    identity = str(package.get("id", "")).lower()
    if identity == CORE_IDS[profile]:
        return "core"
    if identity == EXPANSION_IDS[profile]:
        return "expansion"
    for title in (package.get("key"), package.get("name")):
        title = clean_title(title)
        if profile == "bbg":
            if re.match(r"^(?:BBG\s*(?:Expanded|拓展|扩展)|Better Balanced Game\s*(?:Expanded|Expansion))", title, re.I):
                return "expansion"
            if re.match(r"^(?:Better\s+Balanced\s+Game|BBG)(?:\s+v?\d|$)", title, re.I):
                return "core"
        else:
            if re.match(r"^(?:CCB|和而不同)\s*(?:文明)?(?:拓展|扩展|Expanded|Expansion)", title, re.I):
                return "expansion"
            if re.match(r"^(?:CCB|和而不同)(?:\s+v?\d|$)", title, re.I):
                return "core"
    return ""


def component_versions(profile, packages, sources=()):
    if profile not in CORE_IDS:
        return []
    result = []
    for role, label in (("core", profile.upper()), ("expansion", profile.upper() + "拓展")):
        rows = [p for p in packages if component_role(p, profile) == role]
        origin = [s for s in sources if component_role(s, profile) == role]
        version = None
        for row in (*rows, *origin):
            for key in ("name", "key"):
                match = re.search(r"(?<![\w.])v?(\d+(?:\.\d+)*(?:[a-z]\d*)?)(?![\w.])", clean_title(row.get(key)), re.I)
                if match:
                    version = match[1]
                    break
            if version:
                break
        if rows or origin:
            result.append({"component": label, "role": role, "version": version,
                           "installedVersion": origin[0].get("version") if origin else None})
        else:
            result.append({"component": label, "role": role, "version": None,
                           "installedVersion": None, "absent": True})
    return result


def format_versions(rows):
    return "；".join(r["component"] + " " + ("未启用" if r.get("absent") else
                    r.get("version") or ("安装版本 " + str(r["installedVersion"]) if r.get("installedVersion") else "未记录"))
                    for r in rows)


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
