"""Build ``data/vanilla/identities.json`` (static TYPE -> name/icon lookup).

The runtime snapshot (``data/gamedb/vanilla/gamedb.sqlite``) is derived from the
player's ``DebugGameplay.sqlite`` and is missing a number of identity rows in the
incomplete installs we support (``TERRAIN_LAKE``, ``FEATURE_REEF`` and friends
never make it into the ``Types`` table of a stripped cache).  This tool builds a
*static* identity directory instead, so the app never depends on the live game
install at runtime:

* ``backup.sqlite`` from the read-only CivVIReplay reference build supplies the
  ``Types`` / ``Leaders`` / ``Civilizations`` / ``Features`` tables (TYPE string
  + hash),
* ``CivVIParser.cpp`` supplies the 54 city-state ``CIVILIZATION_*`` strings that
  upstream keys its ``cityState`` table by,
* the curated dictionary below supplies the official Simplified-Chinese names,
  cross-checked against ``DebugLocalization.sqlite`` when it is available (the
  game cache wins on conflict, matching the tool's degradation policy),
* ``assets/icons/`` supplies the vendored icon path per TYPE string.

Every row is asserted to satisfy ``crc32_type(TYPE) == hash`` before it is
written.  Usage::

    python tools/build_identities.py [--ref ...] [--cpp ...] [--loc ...]
"""
from __future__ import annotations

import argparse
import binascii
import datetime as _dt
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "vanilla" / "identities.json"
DEFAULT_REF = ROOT.parent / "CivVIReplay_v6.0" / "image" / "database" / "backup.sqlite"
DEFAULT_CPP = ROOT.parent / "CivVIReplay-src" / "src" / "CivVIParser.cpp"
DEFAULT_LOC_JSON = ROOT / "data" / "vanilla" / "loc.json"
ICONS_DIR = ROOT / "assets" / "icons"


def _crc32_type(text: str) -> int:
    return (~binascii.crc32(text.encode("ascii")) & 0xFFFFFFFF)


def default_loc() -> Path:
    import os
    local = os.environ.get("LOCALAPPDATA", "")
    return (Path(local) / "Firaxis Games" / "Sid Meier's Civilization VI"
            / "Cache" / "DebugLocalization.sqlite")


# --------------------------------------------------------------------------
# curated Simplified-Chinese dictionary (official in-game translations)
# --------------------------------------------------------------------------
LEADER_ZH = {
    "LEADER_ABRAHAM_LINCOLN": "亚伯拉罕·林肯",
    "LEADER_ALEXANDER": "亚历山大",
    "LEADER_AMANITORE": "阿曼妮托尔",
    "LEADER_AMBIORIX": "安比奥里克斯",
    "LEADER_BARBAROSSA": "弗雷德里克·巴巴罗萨",
    "LEADER_BASIL": "巴西尔二世",
    "LEADER_CATHERINE_DE_MEDICI": "凯瑟琳·德·美第奇",
    "LEADER_CATHERINE_DE_MEDICI_ALT": "凯瑟琳·德·美第奇（华丽）",
    "LEADER_CHANDRAGUPTA": "旃陀罗笈多",
    "LEADER_CLEOPATRA": "克利欧佩特拉",
    "LEADER_CLEOPATRA_ALT": "克利欧佩特拉（托勒密）",
    "LEADER_CYRUS": "居鲁士",
    "LEADER_DIDO": "狄多",
    "LEADER_ELEANOR_ENGLAND": "阿基坦的埃莉诺（英格兰）",
    "LEADER_ELEANOR_FRANCE": "阿基坦的埃莉诺（法国）",
    "LEADER_ELIZABETH": "伊丽莎白一世",
    "LEADER_GANDHI": "甘地",
    "LEADER_GENGHIS_KHAN": "成吉思汗",
    "LEADER_GILGAMESH": "吉尔伽美什",
    "LEADER_GITARJA": "加查·马达",
    "LEADER_GORGO": "戈耳戈",
    "LEADER_HAMMURABI": "汉谟拉比",
    "LEADER_HARALD_ALT": "哈拉尔德·哈德拉达（瓦兰吉）",
    "LEADER_HARDRADA": "哈拉尔德·哈德拉达",
    "LEADER_HOJO": "北条时宗",
    "LEADER_JADWIGA": "雅德维加",
    "LEADER_JAYAVARMAN": "阇耶跋摩七世",
    "LEADER_JOAO_III": "若昂三世",
    "LEADER_JOHN_CURTIN": "约翰·科廷",
    "LEADER_JULIUS_CAESAR": "尤利乌斯·凯撒",
    "LEADER_KRISTINA": "克里斯蒂娜",
    "LEADER_KUBLAI_KHAN_CHINA": "忽必烈（中国）",
    "LEADER_KUBLAI_KHAN_MONGOLIA": "忽必烈（蒙古）",
    "LEADER_KUPE": "库佩",
    "LEADER_LADY_SIX_SKY": "六天夫人",
    "LEADER_LADY_TRIEU": "赵妪",
    "LEADER_LAURIER": "威尔弗里德·劳雷尔",
    "LEADER_LAUTARO": "劳塔罗",
    "LEADER_LUDWIG": "路德维希二世",
    "LEADER_MANSA_MUSA": "曼萨·穆萨",
    "LEADER_MATTHIAS_CORVINUS": "马加什·科尔温",
    "LEADER_MENELIK": "孟尼利克二世",
    "LEADER_MONTEZUMA": "蒙特祖玛",
    "LEADER_MVEMBA": "姆本巴·恩津加",
    "LEADER_NADER_SHAH": "纳迪尔沙",
    "LEADER_NZINGA_MBANDE": "恩津加·姆班德",
    "LEADER_PACHACUTI": "帕查库特克",
    "LEADER_PEDRO": "佩德罗二世",
    "LEADER_PERICLES": "伯里克利",
    "LEADER_PETER_GREAT": "彼得大帝",
    "LEADER_PHILIP_II": "腓力二世",
    "LEADER_POUNDMAKER": "制磅者",
    "LEADER_QIN": "秦始皇",
    "LEADER_QIN_ALT": "秦始皇（统一者）",
    "LEADER_RAMSES": "拉美西斯二世",
    "LEADER_ROBERT_THE_BRUCE": "罗伯特·布鲁斯",
    "LEADER_SALADIN": "萨拉丁",
    "LEADER_SALADIN_ALT": "萨拉丁（维齐尔）",
    "LEADER_SEJONG": "世宗大王",
    "LEADER_SEONDEOK": "善德女王",
    "LEADER_SHAKA": "沙卡",
    "LEADER_SIMON_BOLIVAR": "西蒙·玻利瓦尔",
    "LEADER_SULEIMAN": "苏莱曼一世",
    "LEADER_SULEIMAN_ALT": "苏莱曼一世（立法者）",
    "LEADER_SUNDIATA_KEITA": "松迪亚塔·凯塔",
    "LEADER_TAMAR": "塔玛丽",
    "LEADER_THEODORA": "狄奥多拉",
    "LEADER_TOKUGAWA": "德川家康",
    "LEADER_TOMYRIS": "托米丽司",
    "LEADER_TRAJAN": "图拉真",
    "LEADER_T_ROOSEVELT": "西奥多·罗斯福",
    "LEADER_T_ROOSEVELT_ROUGHRIDER": "西奥多·罗斯福（莽骑兵）",
    "LEADER_VICTORIA": "维多利亚",
    "LEADER_VICTORIA_ALT": "维多利亚（蒸汽时代）",
    "LEADER_WILHELMINA": "威廉明娜",
    "LEADER_WU_ZETIAN": "武则天",
    "LEADER_YONGLE": "永乐",
}

CIV_ZH = {
    "CIVILIZATION_AMERICA": "美国",
    "CIVILIZATION_ARABIA": "阿拉伯",
    "CIVILIZATION_AUSTRALIA": "澳大利亚",
    "CIVILIZATION_AZTEC": "阿兹特克",
    "CIVILIZATION_BABYLON_STK": "巴比伦",
    "CIVILIZATION_BRAZIL": "巴西",
    "CIVILIZATION_BYZANTIUM": "拜占庭",
    "CIVILIZATION_CANADA": "加拿大",
    "CIVILIZATION_CHINA": "中国",
    "CIVILIZATION_CREE": "克里",
    "CIVILIZATION_EGYPT": "埃及",
    "CIVILIZATION_ENGLAND": "英格兰",
    "CIVILIZATION_ETHIOPIA": "埃塞俄比亚",
    "CIVILIZATION_FRANCE": "法国",
    "CIVILIZATION_GAUL": "高卢",
    "CIVILIZATION_GEORGIA": "格鲁吉亚",
    "CIVILIZATION_GERMANY": "德国",
    "CIVILIZATION_GRAN_COLOMBIA": "大哥伦比亚",
    "CIVILIZATION_GREECE": "希腊",
    "CIVILIZATION_HUNGARY": "匈牙利",
    "CIVILIZATION_INCA": "印加",
    "CIVILIZATION_INDIA": "印度",
    "CIVILIZATION_INDONESIA": "印度尼西亚",
    "CIVILIZATION_JAPAN": "日本",
    "CIVILIZATION_KHMER": "高棉",
    "CIVILIZATION_KONGO": "刚果",
    "CIVILIZATION_KOREA": "朝鲜",
    "CIVILIZATION_LIME_TEOTIHUACAN": "特奥蒂瓦坎",
    "CIVILIZATION_LIME_THULE": "图勒",
    "CIVILIZATION_MACEDON": "马其顿",
    "CIVILIZATION_MALI": "马里",
    "CIVILIZATION_MAORI": "毛利",
    "CIVILIZATION_MAPUCHE": "马普切",
    "CIVILIZATION_MAYA": "玛雅",
    "CIVILIZATION_MONGOLIA": "蒙古",
    "CIVILIZATION_NETHERLANDS": "荷兰",
    "CIVILIZATION_NORWAY": "挪威",
    "CIVILIZATION_NUBIA": "努比亚",
    "CIVILIZATION_OTTOMAN": "奥斯曼",
    "CIVILIZATION_PERSIA": "波斯",
    "CIVILIZATION_PHOENICIA": "腓尼基",
    "CIVILIZATION_POLAND": "波兰",
    "CIVILIZATION_PORTUGAL": "葡萄牙",
    "CIVILIZATION_ROME": "罗马",
    "CIVILIZATION_RUSSIA": "俄罗斯",
    "CIVILIZATION_SCOTLAND": "苏格兰",
    "CIVILIZATION_SCYTHIA": "斯基泰",
    "CIVILIZATION_SPAIN": "西班牙",
    "CIVILIZATION_SPECTATOR": "旁观者",
    "CIVILIZATION_SUK_SWAHILI": "斯瓦希里",
    "CIVILIZATION_SUK_TIBET": "吐蕃",
    "CIVILIZATION_SUMERIA": "苏美尔",
    "CIVILIZATION_SWEDEN": "瑞典",
    "CIVILIZATION_VIETNAM": "越南",
    "CIVILIZATION_ZULU": "祖鲁",
    "CIVILIZATION_FREE_CITIES": "自由城市",
    "CIVILIZATION_BARBARIAN": "蛮族",
}

CITY_STATE_ZH = {
    "CIVILIZATION_AMSTERDAM": "阿姆斯特丹",
    "CIVILIZATION_BRUSSELS": "布鲁塞尔",
    "CIVILIZATION_BUENOS_AIRES": "布宜诺斯艾利斯",
    "CIVILIZATION_CARTHAGE": "迦太基",
    "CIVILIZATION_GENEVA": "日内瓦",
    "CIVILIZATION_HATTUSA": "哈图沙",
    "CIVILIZATION_HONG_KONG": "香港",
    "CIVILIZATION_JAKARTA": "雅加达",
    "CIVILIZATION_JERUSALEM": "耶路撒冷",
    "CIVILIZATION_KABUL": "喀布尔",
    "CIVILIZATION_KANDY": "康提",
    "CIVILIZATION_KUMASI": "库马西",
    "CIVILIZATION_LA_VENTA": "拉本塔",
    "CIVILIZATION_LISBON": "里斯本",
    "CIVILIZATION_MOHENJO_DARO": "摩亨佐-达罗",
    "CIVILIZATION_NAN_MADOL": "南马都尔",
    "CIVILIZATION_PRESLAV": "普雷斯拉夫",
    "CIVILIZATION_SEOUL": "首尔",
    "CIVILIZATION_STOCKHOLM": "斯德哥尔摩",
    "CIVILIZATION_TORONTO": "多伦多",
    "CIVILIZATION_VALLETTA": "瓦莱塔",
    "CIVILIZATION_VILNIUS": "维尔纽斯",
    "CIVILIZATION_YEREVAN": "埃里温",
    "CIVILIZATION_ZANZIBAR": "桑给巴尔",
    "CIVILIZATION_AKKAD": "阿卡德",
    "CIVILIZATION_BOLOGNA": "博洛尼亚",
    "CIVILIZATION_CAHOKIA": "卡霍基亚",
    "CIVILIZATION_CARDIFF": "加的夫",
    "CIVILIZATION_FEZ": "非斯",
    "CIVILIZATION_MEXICO_CITY": "墨西哥城",
    "CIVILIZATION_NAZCA": "纳斯卡",
    "CIVILIZATION_NGAZARGAMU": "恩加扎尔加穆",
    "CIVILIZATION_RAPA_NUI": "拉帕努伊",
    "CIVILIZATION_AYUTTHAYA": "阿瑜陀耶",
    "CIVILIZATION_CHINGUETTI": "欣盖提",
    "CIVILIZATION_JOHANNESBURG": "约翰内斯堡",
    "CIVILIZATION_NALANDA": "那烂陀",
    "CIVILIZATION_SAMARKAND": "撒马尔罕",
    "CIVILIZATION_WOLIN": "沃林",
    "CIVILIZATION_ANTIOCH": "安条克",
    "CIVILIZATION_BABYLON": "巴比伦",
    "CIVILIZATION_AUCKLAND": "奥克兰",
    "CIVILIZATION_ANTANANARIVO": "塔那那利佛",
    "CIVILIZATION_ARMAGH": "阿马",
    "CIVILIZATION_GRANADA": "格拉纳达",
    "CIVILIZATION_MUSCAT": "马斯喀特",
    "CIVILIZATION_PALENQUE": "帕伦克",
    "CIVILIZATION_CAGUANA": "卡瓜纳",
    "CIVILIZATION_HUNZA": "罕萨",
    "CIVILIZATION_LAHORE": "拉合尔",
    "CIVILIZATION_SINGAPORE": "新加坡",
    "CIVILIZATION_TARUGA": "塔鲁加",
    "CIVILIZATION_VATICAN_CITY": "梵蒂冈",
    "CIVILIZATION_VENICE": "威尼斯",
}

TERRAIN_ZH = {
    "TERRAIN_GRASS": "草原",
    "TERRAIN_GRASS_HILLS": "草原丘陵",
    "TERRAIN_GRASS_MOUNTAIN": "草原山脉",
    "TERRAIN_PLAINS": "平原",
    "TERRAIN_PLAINS_HILLS": "平原丘陵",
    "TERRAIN_PLAINS_MOUNTAIN": "平原山脉",
    "TERRAIN_DESERT": "沙漠",
    "TERRAIN_DESERT_HILLS": "沙漠丘陵",
    "TERRAIN_DESERT_MOUNTAIN": "沙漠山脉",
    "TERRAIN_TUNDRA": "苔原",
    "TERRAIN_TUNDRA_HILLS": "苔原丘陵",
    "TERRAIN_TUNDRA_MOUNTAIN": "苔原山脉",
    "TERRAIN_SNOW": "雪原",
    "TERRAIN_SNOW_HILLS": "雪原丘陵",
    "TERRAIN_SNOW_MOUNTAIN": "雪原山脉",
    "TERRAIN_COAST": "海岸",
    "TERRAIN_OCEAN": "海洋",
    "TERRAIN_LAKE": "湖泊",
}

FEATURE_ZH = {
    "FEATURE_FOREST": "森林",
    "FEATURE_JUNGLE": "丛林",
    "FEATURE_MARSH": "沼泽",
    "FEATURE_OASIS": "绿洲",
    "FEATURE_ICE": "冰",
    "FEATURE_REEF": "礁石",
    "FEATURE_FLOODPLAINS": "泛滥平原",
    "FEATURE_FLOODPLAINS_GRASSLAND": "泛滥平原（草原）",
    "FEATURE_FLOODPLAINS_PLAINS": "泛滥平原（平原）",
    "FEATURE_VOLCANO": "火山",
    "FEATURE_VOLCANIC_SOIL": "火山土",
    "FEATURE_GEOTHERMAL_FISSURE": "地热裂缝",
    "FEATURE_BURNING_FOREST": "燃烧的森林",
    "FEATURE_BURNT_FOREST": "烧毁的森林",
    "FEATURE_BURNING_JUNGLE": "燃烧的丛林",
    "FEATURE_BURNT_JUNGLE": "烧毁的丛林",
    "FEATURE_BARRIER_REEF": "大堡礁",
    "FEATURE_BARRINGER_CRATER": "巴林杰陨石坑",
    "FEATURE_BERMUDA_TRIANGLE": "百慕大三角",
    "FEATURE_BIOLUMINESCENT_BAY": "荧光海湾",
    "FEATURE_CERRO_DE_POTOSI": "波托西银矿",
    "FEATURE_CHOCOLATEHILLS": "巧克力山",
    "FEATURE_CLIFFS_DOVER": "多佛白崖",
    "FEATURE_CRATER_LAKE": "火山口湖",
    "FEATURE_DALLOL": "达洛尔",
    "FEATURE_DEAD_SEA": "死海",
    "FEATURE_DELICATE_ARCH": "精致拱门",
    "FEATURE_DEVILSTOWER": "魔鬼塔",
    "FEATURE_EVEREST": "珠穆朗玛峰",
    "FEATURE_EYE_OF_THE_SAHARA": "撒哈拉之眼",
    "FEATURE_EYJAFJALLAJOKULL": "埃亚菲亚德拉冰盖",
    "FEATURE_FOUNTAIN_OF_YOUTH": "青春之泉",
    "FEATURE_GALAPAGOS": "加拉帕戈斯群岛",
    "FEATURE_GIANTS_CAUSEWAY": "巨人之路",
    "FEATURE_GIBRALTAR": "直布罗陀巨岩",
    "FEATURE_GOBUSTAN": "戈布斯坦",
    "FEATURE_GRAND_MESA": "大台地",
    "FEATURE_HA_LONG_BAY": "下龙湾",
    "FEATURE_IKKIL": "伊克基尔",
    "FEATURE_KAILASH": "冈仁波齐峰",
    "FEATURE_KILIMANJARO": "乞力马扎罗山",
    "FEATURE_KRAKATOA": "喀拉喀托",
    "FEATURE_LAKE_RETBA": "玫瑰湖",
    "FEATURE_LAKE_VICTORIA": "维多利亚湖",
    "FEATURE_LENCOIS_MARANHENSES": "伦索伊斯·马拉年塞斯",
    "FEATURE_LYSEFJORDEN": "吕瑟峡湾",
    "FEATURE_MATTERHORN": "马特洪峰",
    "FEATURE_MOSI_OA_TUNYA": "莫西奥图尼亚瀑布",
    "FEATURE_MOTLATSE_CANYON": "莫特拉策峡谷",
    "FEATURE_NAMIB": "纳米布沙漠",
    "FEATURE_OLD_FAITHFUL": "老忠实泉",
    "FEATURE_OUNIANGA": "乌尼昂加",
    "FEATURE_PAITITI": "帕伊蒂蒂",
    "FEATURE_PAMUKKALE": "棉花堡",
    "FEATURE_PANTANAL": "潘塔纳尔湿地",
    "FEATURE_PIOPIOTAHI": "皮奥皮奥塔希",
    "FEATURE_RORAIMA": "罗赖马山",
    "FEATURE_SALAR_DE_UYUNI": "乌尤尼盐沼",
    "FEATURE_SINAI": "西奈山",
    "FEATURE_SRI_PADA": "亚当峰",
    "FEATURE_TORRES_DEL_PAINE": "百内角",
    "FEATURE_TSINGY": "黥基·德·贝马拉哈",
    "FEATURE_UBSUNUR_HOLLOW": "乌布苏盆地",
    "FEATURE_ULURU": "乌鲁鲁",
    "FEATURE_VESUVIUS": "维苏威火山",
    "FEATURE_VREDEFORT_DOME": "弗里德堡陨石坑",
    "FEATURE_WHITEDESERT": "白沙漠",
    "FEATURE_WULINGYUAN": "武陵源",
    "FEATURE_YOSEMITE": "优胜美地",
    "FEATURE_ZHANGYE_DANXIA": "张掖丹霞",
}

# districts (v0.22): cache names win, curated fills UD/expansion gaps
DISTRICT_ZH = {
    "DISTRICT_CITY_CENTER": "市中心",
    "DISTRICT_CAMPUS": "学院",
    "DISTRICT_HOLY_SITE": "圣地",
    "DISTRICT_ENCAMPMENT": "军营",
    "DISTRICT_HARBOR": "港口",
    "DISTRICT_COMMERCIAL_HUB": "商业中心",
    "DISTRICT_THEATER": "剧院广场",
    "DISTRICT_INDUSTRIAL_ZONE": "工业区",
    "DISTRICT_ENTERTAINMENT_COMPLEX": "娱乐中心",
    "DISTRICT_AQUEDUCT": "水渠",
    "DISTRICT_NEIGHBORHOOD": "住宅区",
    "DISTRICT_SPACEPORT": "太空竞赛区",
    "DISTRICT_GOVERNMENT": "政府广场",
    "DISTRICT_DIPLOMATIC_QUARTER": "外交区",
    "DISTRICT_CANAL": "运河",
    "DISTRICT_DAM": "水坝",
    "DISTRICT_PRESERVE": "自然保护区",
    "DISTRICT_AERODROME": "飞机场",
    "DISTRICT_WATER_ENTERTAINMENT_COMPLEX": "水上娱乐中心",
    "DISTRICT_ACROPOLIS": "卫城",
    "DISTRICT_BATH": "浴场",
    "DISTRICT_HANSA": "汉萨",
    "DISTRICT_LAVRA": "拉夫拉",
    "DISTRICT_MBANZA": "姆班扎",
    "DISTRICT_COTHON": "科托",
    "DISTRICT_ROYAL_NAVY_DOCKYARD": "皇家海军船坞",
    "DISTRICT_HIPPODROME": "赛马场",
    "DISTRICT_IKANDA": "伊坎达",
    "DISTRICT_STREET_CARNIVAL": "街头狂欢",
    "DISTRICT_WATER_STREET_CARNIVAL": "水上街头狂欢",
    "DISTRICT_THANH": "城寨",
    "DISTRICT_SUGUBA": "苏古巴",
    "DISTRICT_SEOWON": "书院",
    "DISTRICT_OBSERVATORY": "天文台",
    "DISTRICT_OPPIDUM": "山寨",
    "DISTRICT_SUK_DZONG": "宗堡",
    "DISTRICT_LIME_TEO_TOLLAN": "托兰",
    "DISTRICT_WONDER": "奇观",
}

# governors (v0.22); the game cache carries no GOVERNOR_* name tag in stripped
# installs, so these are curated official Simplified-Chinese display names.
GOVERNOR_ZH = {
    "GOVERNOR_THE_DEFENDER": "维克多",
    "GOVERNOR_THE_EDUCATOR": "平伽拉",
    "GOVERNOR_THE_CARDINAL": "穆克沙",
    "GOVERNOR_THE_MERCHANT": "瑞纳",
    "GOVERNOR_THE_AMBASSADOR": "阿玛尼",
    "GOVERNOR_THE_BUILDER": "马格努斯",
    "GOVERNOR_THE_RESOURCE_MANAGER": "梁",
    "GOVERNOR_IBRAHIM": "易卜拉欣",
}

# v0.31: the two WMD stockpile types.  The top bar / 军事 panel counts them, and
# the icons come from the icon-font atlas (``tools/vendor_wmd_icons.py``).
WMD_ZH = {
    "WMD_NUCLEAR_DEVICE": "核装置",
    "WMD_THERMONUCLEAR_DEVICE": "热核装置",
}

# city-state flavour token used by CivVIParser -> Simplified Chinese
FLAVOUR_ZH = {
    "TRADE": "商业",
    "RELIGIOUS": "宗教",
    "SCIENTIFIC": "科技",
    "INDUSTRIAL": "工业",
    "MILITARISTIC": "军事",
    "CULTURAL": "文化",
}

# religions (v0.25): the game tags ``RELIGION_BUDDHISM`` as
# ``LOC_RELIGION_BUDDHISM`` (no ``_NAME`` suffix), so the snapshot lookup needs
# the bare tag.  These curated names cover installs whose text snapshot is
# missing the row entirely (older ``DebugLocalization`` caches carry none).
RELIGION_ZH = {
    "RELIGION_BUDDHISM": "佛教",
    "RELIGION_CATHOLICISM": "天主教",
    "RELIGION_CONFUCIANISM": "儒教",
    "RELIGION_HINDUISM": "印度教",
    "RELIGION_ISLAM": "伊斯兰教",
    "RELIGION_JUDAISM": "犹太教",
    "RELIGION_ORTHODOXY": "东正教",
    # alias kept for the historical TYPE name, in case a save/mod uses it
    "RELIGION_EASTERN_ORTHODOXY": "东正教",
    "RELIGION_PROTESTANTISM": "新教",
    "RELIGION_SHINTO": "神道教",
    "RELIGION_SIKHISM": "锡克教",
    "RELIGION_TAOISM": "道教",
    "RELIGION_ZOROASTRIANISM": "琐罗亚斯德教",
    "RELIGION_PANTHEON": "万神殿",
}

# icons whose TYPE name does not match the vendored file stem
ICON_ALIASES = {
    "RELIGION_ORTHODOXY": "religion/Eastern_Orthodoxy.png",
    "RELIGION_EASTERN_ORTHODOXY": "religion/Eastern_Orthodoxy.png",
}

# golden-age dedication categories (v0.25).  A save stores the
# ``COMMEMORATION_<X>`` TYPE (``KIND_MOMENT_OUTCOME``) picked for the era; its
# display name is the ``LOC_MOMENT_CATEGORY_<X>`` tag, which only the MOD text
# snapshot carries in zh (the official English text keeps the dedication name).
# ``MOMENT_CATEGORY_<X>`` is emitted as well, so either encoding resolves.
MOMENT_CATEGORIES = (
    "MILITARY", "ECONOMIC", "CULTURAL", "SCIENTIFIC", "RELIGIOUS",
    "EXPLORATION", "INFRASTRUCTURE", "ESPIONAGE", "TOURISM",
    "AERONAUTICAL", "AUTOMATON", "INDUSTRIAL",
)

# A name harvested from a broken localization cache can be nothing but a LOC
# tag (``TERRAIN_PLAINS`` -> ``{LOC_CIVROYALE_TERRAIN_WASTELAND_NAME}``); such a
# value must never reach the snapshot.
_LOC_TAG_RE = re.compile(r"^\{?\s*LOC_[A-Z0-9_]*\s*\}?$")

# TYPE strings absent from the reference snapshot but present in game saves
EXTRA_TERRAINS = ["TERRAIN_LAKE"]
EXTRA_FEATURES = ["FEATURE_REEF", "FEATURE_VOLCANIC_SOIL", "FEATURE_VOLCANO",
                  "FEATURE_GEOTHERMAL_FISSURE", "FEATURE_FLOODPLAINS_PLAINS",
                  "FEATURE_FLOODPLAINS_GRASSLAND"]

CITY_STATE_RE = re.compile(
    r"\{\s*0x([0-9a-fA-F]+)\s*,\s*(\w+)\s*\}\s*,?\s*//\s*(CIVILIZATION_[A-Z_]+)")


def _first(value) -> str:
    if not value:
        return ""
    return str(value).split("|")[0].strip()


def _usable_name(value) -> str:
    """Empty for missing values and for names that are really raw LOC tags."""
    text = _first(value)
    if not text or _LOC_TAG_RE.match(text):
        return ""
    return text


def _lookup_loc(loc_data: dict, type_str: str, tag_hint: str | None = None) -> dict:
    """Cache name for a TYPE; ``LOC_<TYPE>_NAME``, ``_FRONTEND_NAME``, bare tag.

    Several city-states were renamed in-game (``CIVILIZATION_LISBON`` shows as
    Mogadishu, ``CIVILIZATION_ANTIOCH`` as Venice, ...) and only carry the
    ``_FRONTEND_NAME`` tag, so we must try both before falling back to curated.

    ``tag_hint`` (v0.24) is the tag the game's ``Civilizations.xml`` points at
    for that TYPE — it wins, because a few legacy TYPEs still carry their old
    text (``CIVILIZATION_JAKARTA`` -> ``LOC_CIVILIZATION_BANDAR_BRUNEI_NAME``).

    v0.25: religions (``LOC_RELIGION_BUDDHISM``) and moment categories
    (``LOC_MOMENT_CATEGORY_RELIGIOUS``) carry no ``_NAME`` suffix, so the bare
    ``LOC_<TYPE>`` tag is tried last.
    """
    if tag_hint:
        entry = loc_data.get(tag_hint)
        if entry:
            return {"zh": _first(entry.get("zh")), "en": _first(entry.get("en"))}
    # Expansion1_Governments.xml: POLICY_GOV_X uses LOC_POLICY_X_NAME.
    # Follow that actual Name tag rather than prettifying "Gov X".
    if type_str.startswith("POLICY_GOV_"):
        entry = loc_data.get("LOC_POLICY_" + type_str[len("POLICY_GOV_"):] + "_NAME")
        if entry:
            return {"zh": _first(entry.get("zh")), "en": _first(entry.get("en"))}
    for tag in ("LOC_" + type_str + "_NAME", "LOC_" + type_str + "_FRONTEND_NAME",
                "LOC_" + type_str):
        entry = loc_data.get(tag)
        if entry:
            return {"zh": _first(entry.get("zh")), "en": _first(entry.get("en"))}
    return {}


def _prettify_type(type_str: str, *prefixes: str) -> str:
    token = type_str
    for prefix in prefixes:
        if token.startswith(prefix):
            token = token[len(prefix):]
            break
    return token.replace("_", " ").title()


def load_loc(path: Path) -> dict:
    """Return ``{(tag): {"zh": ..., "en": ...}}`` from DebugLocalization."""
    out: dict = {}
    if not path.exists():
        return out
    con = sqlite3.connect(str(path))
    try:
        for lang, tag, text in con.execute(
                "select Language, Tag, Text from LocalizedText where Language in ('zh_Hans_CN','en_US')"):
            slot = out.setdefault(tag, {})
            slot["zh" if lang == "zh_Hans_CN" else "en"] = text
    except sqlite3.DatabaseError:
        return {}
    finally:
        con.close()
    return out


def icon_index(icons_dir: Path) -> dict:
    """(category_lower, stem_lower) -> relative path (mirrors vendor_icons).

    Colored variants win: ``district/GREY/<stem>.png`` is skipped so
    ``DISTRICT_*`` resolves to ``district/<stem>.png``.
    """
    idx: dict = {}
    if not icons_dir.exists():
        return idx
    for png in icons_dir.rglob("*.png"):
        rel = png.relative_to(icons_dir)
        if len(rel.parts) < 2:
            continue
        if any(part.upper() == "GREY" for part in rel.parts[1:-1]):
            continue
        idx[(rel.parts[0].lower(), png.stem.lower())] = str(rel).replace("\\", "/")
    return idx


def icon_for(type_str: str, idx: dict) -> str | None:
    category, _, name = type_str.partition("_")
    return idx.get((category.lower(), name.lower()))


def load_ref(ref: Path) -> dict:
    if not ref.exists():
        raise SystemExit(f"reference database not found: {ref}\n"
                         "CivVIReplay_v6.0/image/database/backup.sqlite is required.")
    con = sqlite3.connect(str(ref))
    con.row_factory = sqlite3.Row
    types = {r["Type"]: int(r["Hash"]) & 0xFFFFFFFF
             for r in con.execute("select Type, Hash from Types")}
    kinds = {r["Type"]: r["Kind"] for r in con.execute("select Type, Kind from Types")}
    leaders = {}
    for r in con.execute("select LeaderType, CivilizationType from CivilizationLeaders"):
        leaders.setdefault(r["LeaderType"], r["CivilizationType"])
    civ_level = {r["CivilizationType"]: r["StartingCivilizationLevelType"]
                 for r in con.execute(
                     "select CivilizationType, StartingCivilizationLevelType from Civilizations")}
    features = {r["FeatureType"]: int(r["NaturalWonder"] or 0)
                for r in con.execute("select FeatureType, NaturalWonder from Features")}
    commemorations = {}
    try:
        for r in con.execute("select CommemorationType, CategoryDescription "
                             "from CommemorationTypes"):
            commemorations[r["CommemorationType"]] = r["CategoryDescription"]
    except sqlite3.DatabaseError:
        pass
    governors = set()
    for tbl, col in (("Governors", "GovernorType"), ("Governors_XP2", "GovernorType")):
        try:
            governors |= {r[0] for r in con.execute(f"select {col} from [{tbl}]")}
        except sqlite3.DatabaseError:
            pass
    con.close()
    return {"types": types, "kinds": kinds, "leaders": leaders,
            "civ_level": civ_level, "features": features, "governors": governors,
            "commemorations": commemorations}


# gameplay TYPE kinds worth resolving in the replay UI (v0.24 gap fill)
_GAP_KINDS = {
    "KIND_UNIT": "unit",
    "KIND_BUILDING": "building",
    "KIND_DISTRICT": "district",
    "KIND_PROJECT": "project",
    "KIND_TECH": "tech",
    "KIND_CIVIC": "civic",
    "KIND_POLICY": "policy",
    "KIND_IMPROVEMENT": "improvement",
    "KIND_RESOURCE": "resource",
    "KIND_FEATURE": "feature",
    "KIND_TERRAIN": "terrain",
    "KIND_RELIGION": "religion",
    # v0.28.2: 教条 / 万神殿也要进名录 —— 之前它们只存在于
    # ``DebugGameplay.sqlite``（随当次 MOD 组合变化），换成 BBG / CCB 的一局之后
    # 存档里的 ``BELIEF_HOLY_WATERS``（神圣水域）就查不出来，界面只剩一个「—」。
    "KIND_BELIEF": "belief",
    "KIND_GOVERNOR": "governor",
    "KIND_GOVERNMENT": "government",
    "KIND_GREAT_PERSON_CLASS": "great_person_class",
}


def load_loc_snapshot(path: Path) -> tuple[dict, dict]:
    """``(tag -> {zh,en}, civ_TYPE -> tag)`` from the ``loc.json`` snapshot."""
    if not path.exists():
        return {}, {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}, {}
    tags: dict = {}
    for section in ("names", "city", "civ"):
        tags.update(doc.get(section) or {})
    return tags, dict(doc.get("civ_tag") or {})


def build(*, ref: Path, cpp: Path, loc: Path, icons: Path, out: Path,
          loc_json: Path | None = None) -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from civ6replay.colors import CITY_STATE_FLAVOUR, LEADER_COLORS

    ref_data = load_ref(ref)
    types = ref_data["types"]
    loc_data = load_loc(loc)
    # the XML-derived snapshot is authoritative for the names it carries
    snap_tags, civ_tags = load_loc_snapshot(loc_json or DEFAULT_LOC_JSON)
    loc_data = {**loc_data, **snap_tags}
    icons_idx = icon_index(icons)
    entries: list = []
    warnings: list = []
    conflicts = 0

    def emit(type_str: str, kind: str, curated: str | None,
             extra: dict | None = None, tag_hint: str | None = None) -> None:
        nonlocal conflicts
        h = _crc32_type(type_str)
        known = types.get(type_str)
        if known is not None:
            assert known == h, f"hash mismatch for {type_str}: {known:#x} != {h:#x}"
        cache = _lookup_loc(loc_data, type_str,
                            tag_hint or civ_tags.get(type_str))
        # v0.25: a name that is really a LOC tag (``{LOC_CIVROYALE_…}``) or an
        # unresolvable snapshot row is discarded so the curated / prettified
        # fallback wins instead of leaking the tag into the UI.
        cache_zh = _usable_name(cache.get("zh"))
        cache_en = _usable_name(cache.get("en"))
        for raw in (cache.get("zh"), cache.get("en")):
            if raw and not _usable_name(raw):
                warnings.append(f"{type_str}: discarded tag-valued name {raw!r}")
        if cache_zh and curated and cache_zh != curated:
            conflicts += 1
            warnings.append(f"{type_str}: curated {curated!r} != cache {cache_zh!r}")
        name_en = cache_en or _usable_name(curated) or _prettify_type(
            type_str, "LEADER_", "CIVILIZATION_", "TERRAIN_", "FEATURE_",
            "DISTRICT_", "GOVERNOR_", "BUILDING_", "UNIT_", "TECH_", "CIVIC_",
            "POLICY_", "PROJECT_", "IMPROVEMENT_", "RESOURCE_", "GOVERNMENT_",
            "RELIGION_", "GREAT_PERSON_CLASS_", "MOMENT_CATEGORY_", "ROUTE_")
        name_zh = cache_zh or _usable_name(curated) or name_en
        if type_str == "POLICY_GOV_AUTOCRACY":
            name_zh = "独裁传承"  # requested display wording for Autocratic Legacy
        assert name_zh, f"missing zh name for {type_str}"
        assert name_en, f"missing en name for {type_str}"
        assert not _LOC_TAG_RE.match(name_zh), f"tag-valued zh name for {type_str}"
        assert not _LOC_TAG_RE.match(name_en), f"tag-valued en name for {type_str}"
        row = {"type": type_str, "hash": h, "zh": name_zh, "en": name_en,
               "kind": kind}
        icon = ICON_ALIASES.get(type_str) or icon_for(type_str, icons_idx)
        if icon:
            row["icon"] = icon
        if extra:
            row.update(extra)
        entries.append(row)

    # --- leaders (must line up exactly with LEADER_COLORS) -----------------
    leader_hashes = set()
    for type_str, h in sorted(types.items()):
        if h in LEADER_COLORS:
            leader_hashes.add(h)
            emit(type_str, "leader", LEADER_ZH.get(type_str),
                 {"civ": ref_data["leaders"].get(type_str)})
    missing = set(LEADER_COLORS) - leader_hashes
    assert not missing, f"leaders missing from reference db: {[hex(x) for x in missing]}"
    assert len(leader_hashes) == len(LEADER_COLORS)

    # --- major civilizations / free cities / barbarians --------------------
    for type_str in sorted(ref_data["civ_level"]):
        level = ref_data["civ_level"][type_str]
        kind = {
            "CIVILIZATION_LEVEL_FULL_CIV": "major",
            "CIVILIZATION_LEVEL_TRIBE": "barbarian",
            "CIVILIZATION_LEVEL_FREE_CITIES": "free_cities",
        }.get(level)
        if kind:
            emit(type_str, kind, CIV_ZH.get(type_str))

    # --- city states (from the upstream parser's commented TYPE strings) ---
    if not cpp.exists():
        raise SystemExit(f"upstream parser not found: {cpp}")
    cpp_text = cpp.read_text(encoding="utf-8", errors="replace")
    cs_rows = CITY_STATE_RE.findall(cpp_text)
    cs_hashes = set()
    for literal, flavour, type_str in cs_rows:
        h = _crc32_type(type_str)
        assert int(literal, 16) == h, f"city-state hash mismatch for {type_str}"
        cs_hashes.add(h)
        emit(type_str, "city_state", CITY_STATE_ZH.get(type_str),
             {"flavour": FLAVOUR_ZH.get(flavour, flavour)})
    assert cs_hashes == set(CITY_STATE_FLAVOUR), (
        "city-state set differs from colors.CITY_STATE_FLAVOUR")

    # --- terrains ----------------------------------------------------------
    terrain_types = sorted(t for t in types
                           if t.startswith("TERRAIN_") and not t.startswith("TERRAIN_CLASS_"))
    for type_str in sorted(set(terrain_types) | set(EXTRA_TERRAINS)):
        emit(type_str, "terrain", TERRAIN_ZH.get(type_str))

    # --- features / natural wonders ---------------------------------------
    feature_types = set(t for t in types if t.startswith("FEATURE_"))
    feature_types |= set(ref_data["features"])
    feature_types |= set(EXTRA_FEATURES)
    for type_str in sorted(feature_types):
        emit(type_str, "feature", FEATURE_ZH.get(type_str),
             {"natural_wonder": bool(ref_data["features"].get(type_str, 0))})

    # --- districts (v0.22): all DISTRICT_* types incl. unique districts -----
    district_types = sorted(t for t in types
                            if t.startswith("DISTRICT_")
                            and not t.startswith("DISTRICT_CLASS_"))
    for type_str in district_types:
        emit(type_str, "district", DISTRICT_ZH.get(type_str))

    # --- governors (v0.22): assignable GOVERNOR_* types --------------------
    governor_types = set(ref_data["governors"]) | {
        t for t in types if t.startswith("GOVERNOR_") and "_PROMOTION_" not in t}
    for type_str in sorted(governor_types):
        emit(type_str, "governor", GOVERNOR_ZH.get(type_str))

    # --- WMD stockpile types (v0.31) ---------------------------------------
    # ``WMD_NUCLEAR_DEVICE`` / ``WMD_THERMONUCLEAR_DEVICE`` are KIND_WMD rows;
    # the 军事 panel shows their counts with the icon-font glyphs vendored by
    # ``tools/vendor_wmd_icons.py`` (``wmd/Nuclear_Device.png`` …).
    wmd_types = {t for t, k in ref_data["kinds"].items() if k == "KIND_WMD"}
    for type_str in sorted(wmd_types | set(WMD_ZH)):
        emit(type_str, "wmd", WMD_ZH.get(type_str))

    # --- religions (v0.25): zh names + the missing Orthodoxy icon ----------
    religion_types = sorted(t for t in types if t.startswith("RELIGION_"))
    religion_types += sorted(set(RELIGION_ZH) - set(religion_types))
    for type_str in religion_types:
        emit(type_str, "religion", RELIGION_ZH.get(type_str))

    # --- golden-age commemorations / dedication categories (v0.25) ---------
    # A save stores ``COMMEMORATION_<X>``; the display name is the
    # ``LOC_MOMENT_CATEGORY_<X>`` tag (MOD text snapshot).  Both encodings get
    # an entry so the front end can label whichever hash it is handed.
    commem = dict(ref_data["commemorations"])
    if not commem:
        commem = {f"COMMEMORATION_{c}": f"LOC_MOMENT_CATEGORY_{c}"
                  for c in MOMENT_CATEGORIES}
    for type_str, name_tag in sorted(commem.items()):
        category = type_str.split("_", 1)[1] if "_" in type_str else type_str
        icon = f"COMMEMORATION/{category.title()}.png"
        extra = {"icon": icon} if (ICONS_DIR / icon).exists() else {}
        emit(type_str, "commemoration", None, dict(extra), tag_hint=name_tag)
        emit(name_tag[len("LOC_"):] if name_tag.startswith("LOC_")
             else f"MOMENT_CATEGORY_{category}",
             "commemoration", None, dict(extra), tag_hint=name_tag)

    # --- v0.24: fill the gameplay TYPEs the stripped game cache omits -------
    # UNIT_PIKE_AND_SHOT / BUILDING_TAJ_MAHAL / TECH_REFINING … are missing
    # from DebugGameplay.sqlite, so real saves showed raw hashes for them.
    # The reference Types table (type + kind) plus the game text XML (name) and
    # the vendored icon set close every gap.
    seen_types = {row["type"] for row in entries}
    for type_str, kind in sorted((t, _GAP_KINDS[k]) for t, k in ref_data["kinds"].items()
                                 if k in _GAP_KINDS):
        if type_str not in seen_types:
            emit(type_str, kind, None)

    entries.sort(key=lambda r: (r["kind"], r["type"]))
    counts: dict = {}
    for row in entries:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1

    doc = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "generator": "tools/build_identities.py",
        "source_reference": str(ref),
        "name_conflicts": conflicts,
        "counts": counts,
        "entries": entries,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    if warnings:
        print(f"{len(warnings)} curated/cache name conflicts (cache wins):", file=sys.stderr)
        for line in warnings[:20]:
            print("  " + line, file=sys.stderr)
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref", default=str(DEFAULT_REF))
    ap.add_argument("--cpp", default=str(DEFAULT_CPP))
    ap.add_argument("--loc", default=str(default_loc()))
    ap.add_argument("--loc-json", default=str(DEFAULT_LOC_JSON))
    ap.add_argument("--icons", default=str(ICONS_DIR))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    doc = build(ref=Path(args.ref), cpp=Path(args.cpp), loc=Path(args.loc),
                icons=Path(args.icons), out=Path(args.out),
                loc_json=Path(args.loc_json))
    print(json.dumps({"out": args.out, "counts": doc["counts"],
                      "conflicts": doc["name_conflicts"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
