"""Civ6 type-hash helpers.

Civ6 identifies gameplay ``TYPE`` strings by a CRC32 of the ASCII name:
``hash(TYPE) = ~crc32(TYPE) & 0xFFFFFFFF`` using the standard reflected
polynomial ``0xEDB88320``.  ``0xFFFFFFFF`` is the "none" sentinel.
"""
from __future__ import annotations

import binascii

NONE = 0xFFFFFFFF


def crc32_type(text: str) -> int:
    return (~binascii.crc32(text.encode("ascii")) & 0xFFFFFFFF)


YIELD_FOOD = crc32_type("YIELD_FOOD")
YIELD_PRODUCTION = crc32_type("YIELD_PRODUCTION")
YIELD_SCIENCE = crc32_type("YIELD_SCIENCE")
YIELD_CULTURE = crc32_type("YIELD_CULTURE")
YIELD_FAITH = crc32_type("YIELD_FAITH")
YIELD_GOLD = crc32_type("YIELD_GOLD")

YIELD_ORDER = [
    YIELD_FOOD,
    YIELD_PRODUCTION,
    YIELD_GOLD,
    YIELD_SCIENCE,
    YIELD_CULTURE,
    YIELD_FAITH,
]

YIELD_NAMES = {
    YIELD_FOOD: "食物",
    YIELD_PRODUCTION: "产能",
    YIELD_GOLD: "金币",
    YIELD_SCIENCE: "科技",
    YIELD_CULTURE: "文化",
    YIELD_FAITH: "信仰",
}

YIELD_COLORS = {
    YIELD_FOOD: "#6fbf4a",
    YIELD_PRODUCTION: "#cd7f32",
    YIELD_GOLD: "#e8c341",
    YIELD_SCIENCE: "#4aa3d6",
    YIELD_CULTURE: "#b06fd6",
    YIELD_FAITH: "#e0e0e0",
}

TYPE_CIV_FULL = 0x253718B0
TYPE_CIV_CITY_STATE = 0xC2577075
TYPE_CIV_FREE_CITIES = 0x04E6B0A0
TYPE_CIV_TRIBE = 0xD959EC24

CIV_TYPE_NAMES = {
    TYPE_CIV_FULL: "完整文明",
    TYPE_CIV_CITY_STATE: "城邦",
    TYPE_CIV_FREE_CITIES: "自由城市",
    TYPE_CIV_TRIBE: "蛮族",
}
