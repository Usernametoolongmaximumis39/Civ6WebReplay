"""Balance package identity, release channel and title version are independent.

Names describe roles. Historical IDs only supplement missing legacy identity
metadata; neither identity nor channel requires a fixed ID.
"""
from functools import lru_cache
import re
import unicodedata

CORE_IDS = {"bbg": "cb84075d-5007-4207-b662-c35a5f7be260",
            "ccb": "8af4fe8e-5406-7d72-d9d6-a8f5d1b66e00"}
EXPANSION_IDS = {"bbg": "2a0aa96a-a31c-4ce2-87ec-09152f6f3e00",
                 "ccb": "8af4fe8e-5406-7d72-d9d6-a8f5d1b66e30"}
# Compatibility for old captured sources which only stored an ID. A readable
# title always takes precedence. Historical manifests reuse IDs across channels,
# so these aliases must never imply Beta, WIP or release status.
_LEGACY_ROLES = {**{identity: (family, "core") for family, identity in CORE_IDS.items()},
                 **{identity: (family, "expansion") for family, identity in EXPANSION_IDS.items()}}
_FAMILY = re.compile(r"^(?P<bbg>Better\s+Balanced\s+Game|BBG)|^(?P<ccb>CCB|和而不同)", re.I)
_TOKEN = re.compile(
    r"(?P<expansion>(?:文明\s*)?(?:Expanded|Expansion|拓展|扩展))"
    r"|(?P<core>基础|核心|Core|Base)"
    r"|(?P<beta>BETA|测试版|公测版|β)"
    r"|(?P<wip>Work\s+in\s+Progress|WIP|开发版)"
    r"|(?P<alpha>ALPHA|内测版)"
    r"|(?P<rc>RC)"
    r"|(?P<release>RELEASE|LIVE|正式版)"
    r"|(?P<version>v?\d+(?:\.\d+)*(?:[ab]\d*(?![a-z]))?)", re.I)
_SEPARATOR = re.compile(r"[\s:：()\[\]【】_-]*")
CHANNEL_LABELS = {"beta": "Beta", "wip": "WIP", "alpha": "Alpha", "rc": "RC"}


def clean_title(title):
    text = unicodedata.normalize("NFKC", str(title or ""))
    text = re.sub(r"\[(?:COLOR[^\]]*|ENDCOLOR)\]", "", text, flags=re.I)
    return " ".join(text.split())


@lru_cache(maxsize=2048)
def _title_identity(title):
    family = _FAMILY.match(title)
    if not family:
        return None
    rest, roles, channels, versions = title[family.end():], set(), set(), []
    while rest:
        rest = rest[_SEPARATOR.match(rest).end():]
        if not rest:
            break
        token = _TOKEN.match(rest)
        if not token:
            return None  # maps, MPH, compatibility patches and unknown suffixes
        kind = token.lastgroup
        if kind in ("core", "expansion"):
            roles.add(kind)
        elif kind == "version":
            versions.append(token.group().lstrip("vV"))
        else:
            channels.add(kind)
        rest = rest[token.end():]
    if len(roles) > 1 or len(versions) > 1:
        return None
    channel = next(iter(channels)) if len(channels) == 1 else "conflict" if channels else None
    return (family.lastgroup, next(iter(roles), "core"), channel, next(iter(versions), None))


def identify_package(package):
    if isinstance(package, str):
        package = {"name": package}
    titles = [clean_title(package.get(k)) for k in ("name", "key") if package.get(k)]
    parsed = [p for t in titles if (p := _title_identity(t))]
    known = _LEGACY_ROLES.get(str(package.get("id", "")).lower())
    if not parsed:
        # ID-only old capture metadata remains readable, but IDs cannot override
        # an actual title such as "CCB map" or "BBG compatibility patch".
        if not known or any(not t.startswith("LOC_") for t in titles):
            return None
        parsed = [(*known, None, None)]
    if len({p[:2] for p in parsed}) != 1:
        return None
    family, role = parsed[0][:2]
    channels = {p[2] for p in parsed if p[2]}
    channel_source = "title" if channels else None
    if not channels:
        description = clean_title(package.get("description"))
        # Read declarations about this build, not arbitrary mentions of Beta
        # in changelogs, compatibility notes or dependencies.
        match = re.match(r"^(BETA|WIP|ALPHA|RC|RELEASE|LIVE)\s+(?:build|version)\b", description, re.I)
        if match:
            channels.add({"live": "release"}.get(match[1].lower(), match[1].lower()))
            channel_source = "description"
    channel = next(iter(channels)) if len(channels) == 1 else "conflict" if channels else None
    versions = {p[3] for p in parsed if p[3]}
    return {"family": family, "role": role, "channel": channel,
            "channelSource": channel_source,
            "isBeta": None if channel in (None, "conflict") else channel == "beta",
            "version": next(iter(versions)) if len(versions) == 1 else None}


def component_role(package, profile):
    identity = identify_package(package)
    return identity["role"] if identity and identity["family"] == profile else ""


def balance_profile(packages, default="vanilla", *, include_expansions=False):
    rows = [identify_package(p) for p in packages or ()]
    # CCB's merged rules take precedence when a BBG dependency is also present.
    for family in ("ccb", "bbg"):
        if any(r and r["family"] == family and (r["role"] == "core" or include_expansions) for r in rows):
            return family
    return default


def manifest_metadata(doc):
    root_version = doc.get("version")
    property_version = doc.findtext("Properties/Version")
    return {"id": (doc.get("id") or "").lower(), "name": doc.findtext("Properties/Name", ""),
            "key": doc.findtext("Properties/Name", ""),
            "description": doc.findtext("Properties/Description", ""),
            "version": property_version or root_version,
            "rootVersion": root_version, "propertyVersion": property_version}
