"""Vendor CivVIReplay's MIT icon set into ``assets/icons/`` and build an index.

Copies ``CivVIReplay_v6.0/image/**.png`` to ``assets/icons/<category>/`` and
writes ``assets/icons/index.json`` mapping ``hash -> relative path`` so the
front-end never depends on filesystem case sensitivity.

The index is built from two sources:

1. ``data/gamedb/vanilla/gamedb.sqlite`` (TYPE -> hash, category = first token),
2. ``data/vanilla/identities.json`` which also carries the identity rows that
   are missing from stripped game caches (``TERRAIN_LAKE``, ``FEATURE_REEF``,
   ``FEATURE_FLOODPLAINS_PLAINS``, ``FEATURE_VOLCANIC_SOIL``, natural wonders…).

Usage::

    python tools/vendor_icons.py [--source CivVIReplay_v6.0/image]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "CivVIReplay_v6.0" / "image"
OUT = ROOT / "assets" / "icons"
GAMEDB = ROOT / "data" / "gamedb" / "vanilla" / "gamedb.sqlite"
IDENTITIES = ROOT / "data" / "vanilla" / "identities.json"
SHARED_IDENTITIES = ROOT / "data" / "shared" / "identities.json"

LICENSE = """Civ6 WebReplay - bundled icon assets
======================================

The legacy PNG icons under assets/icons/ are copied from the CivVIReplay project
(https://github.com/Keride/CivVIReplay), which is distributed under the MIT
License.  Copyright (c) the CivVIReplay authors.  See the upstream repository
for the full license text.

Shared mod art (assets/icons/shared/)
-----------------------------------
These PNGs are extracted from the locally installed Civilization VI / SDK and
mod textures by tools/vendor_shared_mod_icons.py. Original artwork belongs to
Firaxis and the respective mod artists; the CivVIReplay MIT notice above does
not relicense it. data/shared/identities.json records source files and hashes.
"""


def _stem_index(src: Path, out: Path) -> tuple[dict, int]:
    """(category_lower, stem_lower) -> relative path, copying files as we go.

    Variant sub-directories (``district/GREY/<stem>.png``) are copied but never
    indexed, so the colored ``district/<stem>.png`` wins; the front-end derives
    the grey path by convention instead.
    """
    stem_index: dict = {}
    n = 0
    for png in src.rglob("*.png"):
        rel = png.relative_to(src)
        if len(rel.parts) < 2:
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(png, dest)
        variant = any(part.upper() == "GREY" for part in rel.parts[1:-1])
        if not variant:
            stem_index[(rel.parts[0].lower(), png.stem.lower())] = str(rel).replace("\\", "/")
        n += 1
    return stem_index, n


def _rel_for(type_str: str, stem_index: dict) -> str | None:
    category, _, name = type_str.partition("_")
    return stem_index.get((category.lower(), name.lower()))


def _index_from_gamedb(stem_index: dict) -> dict:
    index: dict = {}
    if not GAMEDB.exists():
        return index
    con = sqlite3.connect(str(GAMEDB))
    try:
        for h, typ in con.execute("select hash, type from types"):
            if not typ:
                continue
            rel = _rel_for(typ, stem_index)
            if rel:
                index[str(int(h) & 0xFFFFFFFF)] = rel
    finally:
        con.close()
    return index


def _index_from_identities(index: dict, path: Path = IDENTITIES) -> int:
    """Add/enforce the static identity rows (they win over the gamedb index)."""
    if not path.exists():
        return 0
    doc = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for row in doc.get("entries", []):
        rel, h = row.get("icon"), row.get("hash")
        if rel and h is not None:
            index[str(int(h) & 0xFFFFFFFF)] = rel
            n += 1
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    src = Path(args.source)
    out = Path(args.out)
    if not src.exists():
        raise SystemExit(f"icon source not found: {src}")

    out.mkdir(parents=True, exist_ok=True)
    stem_index, copied = _stem_index(src, out)
    index = _index_from_gamedb(stem_index)
    from_identities = _index_from_identities(index)
    from_identities += _index_from_identities(index, SHARED_IDENTITIES)

    (out / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8"
    )
    (out / "LICENSE").write_text(LICENSE, encoding="utf-8")
    print(f"copied {copied} icons; indexed {len(index)} type hashes "
          f"({from_identities} from identities) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
