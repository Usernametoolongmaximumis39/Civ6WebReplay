"""总督晋升词条名：按存档实际启用的规则集（原版 / BBG / CCB）选表。

存档里每座城市的总督记录了**点过哪些晋升**——一小组
``GOVERNOR_PROMOTION_*`` 的类型哈希（见 :mod:`civ6replay.state` 的
``governorPromotionHashes``）。但**同一个晋升在不同 MOD 下叫法不同**：

* ``共享知识``（CCB） / ``知识共享``（BBG）
* ``外汇资金``（CCB） / ``国际贸易``（BBG）
* ``住房扩建``（CCB 改名） / ``自来水工程``（原版）
* CCB 另有两个领袖专属总督（易卜拉欣 / 西雅赫·卡克），词条只存在于 MOD 文本里

所以名称不能写死在快照里，得按存档自己的 MOD 列表（:mod:`civ6replay.mods`
的 ``balance_mod``）去 ``data/mods/governor_promotions.json`` 里选对应规则集。
该文件由 ``tools/build_governors.py`` 生成。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .hash import crc32_type
from .mods import balance_mod

GOVERNOR_PROMOTIONS_JSON = (Path(__file__).resolve().parents[2] / "data" / "mods"
                            / "governor_promotions.json")

# 平衡 MOD 名（``mods.balance_mod`` 的返回值）-> 数据文件里的规则集 key
MOD_KEYS = {"CCB": "ccb", "BBG": "bbg"}
# 存档没有平衡 MOD 时用的规则集
FALLBACK_KEY = "vanilla"


class GovernorPromotions:
    """``{规则集: {晋升哈希 -> 名称}}`` + 每个总督的显示顺序。"""

    def __init__(self, path: Path | str = GOVERNOR_PROMOTIONS_JSON):
        self.path = Path(path)
        self.tables: Dict[str, dict] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        for key, block in (doc.get("mods") or {}).items():
            names: Dict[int, str] = {}
            english: Dict[int, str] = {}
            order: Dict[int, List[int]] = {}
            for gov in block.get("governors") or []:
                gov_hash = crc32_type(gov["type"])
                seq: List[int] = []
                for promo in gov.get("promotions") or []:
                    h = crc32_type(promo["type"]) & 0xFFFFFFFF
                    seq.append(h)
                    label = promo.get("name_zh") or promo.get("name_en") or ""
                    if label and h not in names:      # 同一类型只归一次
                        names[h] = label
                        english[h] = promo.get("name_en") or label
                order[gov_hash] = seq
            self.tables[key] = {
                "label": block.get("label") or key,
                "verified": block.get("verified_in_game"),
                "names": names,
                "english": english,
                "order": order,
            }

    @property
    def available(self) -> bool:
        return bool(self.tables)

    def keys(self) -> List[str]:
        return sorted(self.tables)

    def key_for(self, mods: Optional[Iterable[str]] = None) -> str:
        """存档 MOD 列表 -> 规则集 key；该规则集还没记录时退回原版表。"""
        key = MOD_KEYS.get(balance_mod(mods) or "", "")
        if key in self.tables:
            return key
        if FALLBACK_KEY in self.tables:
            return FALLBACK_KEY
        return next(iter(self.tables), "")

    def table(self, mods: Optional[Iterable[str]] = None, lang: str = "zh") -> dict:
        table = self.tables.get(
            self.key_for(mods), {"label": "", "verified": None, "names": {}, "order": {}})
        return {**table, "names": table.get("english", table["names"])} if lang == "en" else table

    def name(self, h, mods: Optional[Iterable[str]] = None) -> str:
        return self.table(mods)["names"].get(int(h) & 0xFFFFFFFF, "")

    def names(self, hashes: Iterable[int],
              mods: Optional[Iterable[str]] = None) -> Dict[int, str]:
        return {int(h) & 0xFFFFFFFF: self.name(h, mods) for h in hashes}

    def sort_key(self, governor_hash, mods: Optional[Iterable[str]] = None):
        """排序用的 key 工厂：按数据文件里该总督的显示顺序（城市总督页）。"""
        seq = self.table(mods)["order"].get(int(governor_hash) & 0xFFFFFFFF, [])
        index = {h: i for i, h in enumerate(seq)}
        unknown = len(index)
        return lambda h: index.get(int(h) & 0xFFFFFFFF, unknown)


_SINGLETON: Optional[GovernorPromotions] = None


def get_governors() -> GovernorPromotions:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = GovernorPromotions()
    return _SINGLETON
