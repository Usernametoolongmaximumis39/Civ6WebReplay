"""Read selected text sources and detect untranslated mod overrides."""
from __future__ import annotations
import re
from build_loc import _harvest
from audit_mod_additions import read_sql


def read_labels(db, tags=None):
    labels = {}
    ordered = list(tags) if tags is not None else None
    batches = [None] if ordered is None else [ordered[i:i+800] for i in range(0, len(ordered), 800)]
    for batch in batches:
        clause = " WHERE Tag IN (" + ",".join("?" for _ in batch) + ")" if batch is not None else ""
        for tag, text in db.execute("SELECT Tag,Text FROM BaseGameText" + clause, batch or []):
            labels.setdefault(tag, {})["en"] = text
        sql = "SELECT Language,Tag,Text FROM LocalizedText WHERE Language IN ('en_US','en_us','en','zh_Hans_CN','zh_hans_cn','zh_Hans','zh_hans')"
        if clause:
            sql += " AND " + clause.removeprefix(" WHERE ")
        for lang, tag, text in db.execute(sql, batch or []):
            key = {"en_us": "en", "en": "en", "zh_hans_cn": "zh", "zh_hans": "zh"}.get((lang or "").lower())
            if key and text:
                labels.setdefault(tag, {})[key] = text
    return labels


def apply_profile_text(db, file, apply, *, is_mod, changes):
    raw = read_sql(file) if is_mod else ""
    tags = set(re.findall(r"\bLOC_[A-Za-z0-9_]+\b", raw))
    dynamic = bool(re.search(r"\b(?:UPDATE|DELETE)\s+(?:LocalizedText|BaseGameText)\b", raw, re.I))
    before = read_labels(db, None if dynamic else tags) if is_mod else {}
    apply(db, file)
    if is_mod:
        after = read_labels(db, None if dynamic else tags)
        for language in ("zh", "en"):
            changes[language].update(tag for tag, pair in after.items()
                                     if pair.get(language) and pair.get(language) != before.get(tag, {}).get(language))
        provided = {}
        _harvest(provided, file, overwrite=False)
        changes["en"].update(tag for tag, pair in provided.items() if pair.get("en"))


def finish_labels(db, changes):
    labels = read_labels(db)
    protected = changes["zh"] - changes["en"]
    for tag in protected:
        if tag in labels:
            labels[tag]["en"] = ""
    return labels, protected
