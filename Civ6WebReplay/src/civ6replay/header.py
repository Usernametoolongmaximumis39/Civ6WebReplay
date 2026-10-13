"""Header info: game seed, map/speed metadata, player identity & colours."""
from __future__ import annotations

import json
from typing import List

from .colors import (
    CITY_STATE_FLAVOUR,
    CULTURAL,
    INDUSTRIAL,
    leader_color_pair,
    player_color_profile,
    MILITARISTIC,
    NOT_CITY_STATE,
    RELIGIOUS,
    SCIENTIFIC,
    TRADE,
)
from .container import Packet
from .hash import TYPE_CIV_CITY_STATE, TYPE_CIV_FULL, TYPE_CIV_TRIBE, crc32_type
from .model import PlayerInfo

M_GAMESPEED = 0x05D9B099
M_MAPSIZE = 0x0B835C40
M_MAPFILE = 0x584C6027
M_MULTIPLAYER = 0x7C546F81
M_SEED = 0x7DD11279
M_SEED_VALUE = 0x96C5C77C

M_IPLAYER = 0x1A96522F
M_TYPEPLAYER = 0xCE42B995
M_TEAM = 0x0D8AB454
M_ICOLOR = 0xCFAF60EF
M_LEADER = 0x4C7FBA58
M_CIV = 0xC7D7515B
M_TYPECIV = 0x830FFC46
M_CIVSTR = 0x9D5E5C2F
M_LEADERSTR = 0xE8CD5E5F
M_PSEUDO = 0xDAB96BFD
M_PSEUDO_STEAM = 0x8E72249A
M_LOCCIVNAME = 0xB3EA1140

MULTIPLAYER_VALUE = 0x453F23E2

TYPE_PLAYER_AI = 1
TYPE_PLAYER_PLAYER = 3


def _decode(raw) -> str:
    if isinstance(raw, bytes):
        return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    return raw or ""


def parse_loc_json(raw) -> dict:
    text = _decode(raw).strip()
    if not text.startswith("{"):
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def loc_text(blob: dict, lang_order=("zh_Hans_CN", "en_US")) -> str:
    for _key, entries in blob.items():
        if not isinstance(entries, list):
            continue
        table = {e.get("locale"): e.get("text") for e in entries if isinstance(e, dict)}
        for lang in lang_order:
            if table.get(lang):
                return table[lang]
        for v in table.values():
            if v:
                return v
    return ""


def game_info(packets: List[Packet]) -> dict:
    p0 = packets[0]
    blob = parse_loc_json(p0.get_str(M_MAPFILE))
    return {
        "map_name": loc_text(blob) or _decode(p0.get_str(M_MAPFILE)),
        "map_key": next(iter(blob.keys()), ""),
        "map_size": _decode(p0.get_str(M_MAPSIZE)),
        "game_speed": _decode(p0.get_str(M_GAMESPEED)),
        "multiplayer": p0.get_int(M_MULTIPLAYER) == MULTIPLAYER_VALUE,
    }


def game_seed(packets: List[Packet]) -> int:
    p = packets[2].get_packet(M_SEED)
    if p is None:
        return 0
    return p.get_int(M_SEED_VALUE) & 0xFFFFFFFF


def _apply_colors(info: PlayerInfo, *, profile: str = "shared") -> None:
    if info.typeCiv == TYPE_CIV_FULL:
        pair = leader_color_pair(info.leader, info.iColor, profile=profile)
        if pair is None and info.leaderStr:
            pair = leader_color_pair(crc32_type(info.leaderStr), info.iColor, profile=profile)
        if pair is not None:
            info.primaryColor, info.secondaryColor = pair
    elif info.typeCiv == TYPE_CIV_CITY_STATE:
        info.primaryColor = (0.0, 0.0, 0.0, 1.0)
        info.secondaryColor = (1.0, 1.0, 1.0, 1.0)
        flavour = CITY_STATE_FLAVOUR.get(info.civ, NOT_CITY_STATE)
        info.secondaryColor = {
            TRADE: (247 / 255, 216 / 255, 1 / 255, 1.0),
            RELIGIOUS: (1.0, 1.0, 1.0, 1.0),
            SCIENTIFIC: (116 / 255, 163 / 255, 243 / 255, 1.0),
            INDUSTRIAL: (255 / 255, 129 / 255, 18 / 255, 1.0),
            MILITARISTIC: (202 / 255, 20 / 255, 21 / 255, 1.0),
            CULTURAL: (255 / 255, 0.0, 255 / 255, 1.0),
        }.get(flavour, info.secondaryColor)
    elif info.typeCiv == TYPE_CIV_TRIBE:
        info.primaryColor = (0.0, 0.0, 0.0, 1.0)
        info.secondaryColor = (1.0, 0.0, 0.0, 1.0)
    else:
        info.primaryColor = (1.0, 0.0, 0.0, 1.0)
        info.secondaryColor = (0.0, 0.0, 0.0, 1.0)


def players_info(packets: List[Packet], *, mods=()) -> List[PlayerInfo]:
    infos = [PlayerInfo(iPlayer=i) for i in range(64)]
    for _marker, p in packets[2].packets.items():
        i_player = p.get_int(M_IPLAYER) & 0xFFFFFFFF
        if i_player == 0xFFFFFFFF or i_player >= 64:
            continue
        info = infos[i_player]
        info.typePlayer = p.get_int(M_TYPEPLAYER) & 0xFFFFFFFF
        if info.typePlayer in (TYPE_PLAYER_PLAYER, TYPE_PLAYER_AI):
            info.team = p.get_int(M_TEAM) & 0xFFFFFFFF
            info.iColor = p.get_int(M_ICOLOR) & 0xFFFFFFFF
            info.leader = p.get_int(M_LEADER) & 0xFFFFFFFF
            if info.leader == 0xFFFFFFFF:
                info.leader = crc32_type(_decode(p.get_str(M_LEADERSTR)))
            info.civ = p.get_int(M_CIV) & 0xFFFFFFFF
            info.typeCiv = p.get_int(M_TYPECIV) & 0xFFFFFFFF
            info.civStr = _decode(p.get_str(M_CIVSTR))
            info.leaderStr = _decode(p.get_str(M_LEADERSTR))
            info.pseudo = _decode(p.get_str(M_PSEUDO))
            info.pseudoWithSteamId = _decode(p.get_str(M_PSEUDO_STEAM))
            info.locCivName = _decode(p.get_str(M_LOCCIVNAME))
    profile = player_color_profile(mods)
    for info in infos:
        _apply_colors(info, profile=profile)
    return infos
