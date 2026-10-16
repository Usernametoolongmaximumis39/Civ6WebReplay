"""Player / unit / city parsing (port of ``ParsePlayers``).

Adapted from the CivVIReplay offset walker (MIT), with local save-format fixes.
"""
from __future__ import annotations

from ._port_helpers import (
    END_IA_STUFF, END_PLAYER_STUFF, PROD_UNIT, TERRITORY_BUILDER,
    _check, _fail, _range, _rarray, _rmap, _seek, peek_byte, peek_int, peek_u32,
    promotions_items, readMapBool, readMapFloat, read_float, register_container,
    read_building_flags, resize,
)
from .binary import buff_to_int, read_int, read_string, u32
from .model import DARK, DOGME, GOLDEN, HEROIC, TECH, Player, Religion

# v0.32: offsets of the per-player *influence* block, relative to the position of
# the envoy-table count word (``it.pos`` right before ``count = read_int(it)``).
INFLUENCE_FIELDS = {
    "pointsEarned": -32,        # 当前这段影响力进度
    "pointsPerTurn": -28,       # Governments.xml: InfluencePointsPerTurn
    "pointsThreshold": -24,     # InfluencePointsThreshold（按游戏速度缩放）
    "tokensPerThreshold": -20,  # InfluenceTokensPerThreshold
    "tokensToGive": -16,        # 剩余使者 = 游戏顶栏 [ICON_Envoy] 旁边那个数
}


def read_governor_established(data, offset):
    """Read the 0/1 word at +28 in the fixed block following city IDs.

    Verified against CCB turns 22..26 (0,0,0,0,1), resident, relocating and
    unassigned governors of all seven base types. The residence counter is
    separate: it cannot be used to infer this flag (Victor can have 0 and True).
    Keep unknown layouts unknown rather than equating assignment with activity.
    """
    if offset < 0 or offset + 32 > len(data):
        return None
    value = u32(data, offset + 28)
    return bool(value) if value in (0, 1) else None


def read_influence_tokens(it) -> int:
    """剩余使者 - the unspent envoy tokens of the player ``it`` currently walks.

    The player record's fixed region carries the game's ``PlayerInfluence``
    fields in its last words, immediately before the envoy-table count:
    ``{pointsEarned, pointsPerTurn, pointsThreshold, tokensPerThreshold,
    tokensToGive}``.  ``tokensToGive`` is what the top bar draws next to
    ``[ICON_Envoy]`` and what ``Governments.xml`` feeds (1/100/1 Chiefdom …
    7/200/3 Democracy, scaled by the game speed: the ONLINE saves of this repo
    store 75/2 for the 150/2 governments).  Verified turn by turn on the
    ``AutoSave_00xx`` series: the counter steps by ``tokensPerThreshold`` whenever
    ``pointsEarned`` crosses ``pointsThreshold`` and drops by exactly the number of
    envoys sent (13 → 15 → 0 while a player dumps 15 envoys into one city-state).
    """
    return buff_to_int(it.data, it.pos + INFLUENCE_FIELDS["tokensToGive"], 4)


def parse_players(data, players, religions, warnings=None):
    """Parse the player records; returns the list of non-fatal tail warnings.

    v0.25: everything after the per-player records (``_parse_post_players``)
    runs under its own guard — a game patch or MOD that shifts those fields
    used to abort the whole players layer, throwing away the era / golden-age
    data *and* reporting a scary layer error.  Now the per-player data (cities,
    units, yields …) is always kept and the tail is reported as a warning.
    """
    if warnings is None:
        warnings = []
    register_container(players, Player)
    register_container(religions, Religion)
    it = _seek(data, TERRITORY_BUILDER)
    it.advance(16)
    it.advance(8)
    it.advance(8)
    count = read_int(it)
    resize(religions, count)
    for i in _range(count, it):
        _check(peek_u32(it) == 7, it)
        it.advance(4)
        # v0.25 (checked against a hexdump of AutoSave_0091): this field holds
        # the religion *TYPE* hash (``RELIGION_BUDDHISM`` …), not an icon index,
        # and the following field is the founder's iPlayer — both confirmed by
        # resolving the values through ``identities``.  The custom religion name
        # is not stored where the upstream walker expects it, so ``name`` stays
        # empty; the front end falls back to the TYPE lookup (``static_info``
        # publishes symbol + name for exactly that reason).
        religions[i].iSymbol = read_int(it)
        religions[i].iPlayer = read_int(it)
        it.advance(12)
        religions[i].name = read_string(it)
        count2 = read_int(it)
        for k in _range(count2, it):
            religions[i].beliefs.append(read_int(it))
        count2 = read_int(it)
        for i in _range(count2, it):
            read_int(it)
        count2 = read_int(it)
        for i in _range(count2, it):
            read_int(it)
        it.advance(11)
    _check(peek_u32(it) == 1, it)
    it.advance(4)
    playerCount = peek_u32(it)
    it.advance(4)
    resize(players, 64)
    for iPlayer in _range(playerCount, it):
        trueiPlayer = read_int(it)
        p = players[trueiPlayer]
        p.iPlayer = trueiPlayer
        _check(peek_u32(it) == 47, it)
        it.advance(4)
        it.advance(4)
        it.advance(4)
        it.advance(4)
        it.advance(56)
        for i in _range(10, it):
            it.advance(1)
        it.advance(4)
        for i in _range(7, it):
            it.advance(4)
        unitCount = peek_u32(it)
        it.advance(4)
        for iUnit in _range(unitCount, it):
            for i in _range(3, it):
                it.advance(4)
            it.advance(4)
            it.advance(4)
            it.advance(8)
            it.advance(12)
            count2 = peek_u32(it)
            it.advance(4)
            it.advance(8)
            for i in _range(count2, it):
                it.advance(20)
            count2 = peek_u32(it)
            it.advance(4)
            for i in _range(count2, it):
                it.advance(4)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(12)
        _rmap(it)
        it.advance(4)
        _rmap(it)
        it.advance(4)
        p.diploFavor = read_int(it)
        it.advance(20)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        _rarray(it, 4, 0)
        _rmap(it)
        it.advance(33)
        _check(peek_u32(it) == 0x10, it)
        it.advance(4)
        it.advance(4)
        cityCount = peek_u32(it)
        it.advance(4)
        resize(p.cities, cityCount)
        for iCity in _range(cityCount, it):
            city = p.cities[iCity]
            city.id = read_int(it)
            _check(peek_u32(it) == 0x33, it)
            it.advance(4)
            it.advance(4)
            city.x = read_int(it)
            city.y = read_int(it)
            it.advance(12)
            it.advance(4)
            it.advance(4)
            city.population = read_int(it)
            it.advance(2)
            it.advance(4)
            it.advance(8)
            it.advance(4)
            for i in _range(64, it):
                it.advance(4)
            it.advance(1)
            it.advance(18)
            for i in _range(13, it):
                _check(peek_u32(it) == 6, it)
                _rmap(it)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(20)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(16)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(8)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(12)
            it.advance(8)
            count = read_int(it)
            for i in _range(count, it):
                _check(peek_u32(it) == 0x33, it)
                it.advance(4)
                it.advance(4)
                it.advance(8)
                it.advance(4)
                it.advance(6)
                it.advance(4)
                it.advance(8)
                read_string(it)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(16)
            it.advance(17)
            _check(peek_u32(it) == 6, it)
            _rmap(it)
            it.advance(13)
            city.name = read_string(it)
            it.advance(8)
            it.advance(4)
            count = peek_u32(it)
            it.advance(4)
            for i in _range(count, it):
                it.advance(4)
            it.advance(8)
            _rarray(it, 4, 0)
            _rarray(it, 4, 0)
            _rarray(it)
            _rarray(it)
            it.advance(9)
            it.advance(36)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(22)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(20)
            it.advance(4)
            it.advance(25)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            it.advance(4)
            _rmap(it)
            _rmap(it)
            it.advance(5)
            _rarray(it, 4, 0)
            it.advance(33)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(8)
            it.advance(4)
            city.religion = read_int(it)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(17)
            it.advance(8)
            it.advance(18)
            it.advance(4)
            it.advance(16)
            _rmap(it)
            _rmap(it)
            it.advance(12)
            _rmap(it)
            _rmap(it)
            it.advance(4)
            count = peek_u32(it)
            it.advance(4)
            for i in _range(count, it):
                _check(peek_u32(it) == 0x2C0F4A46, it)
                it.advance(4)
                it.advance(4)
                it.advance(4)
                kind = read_int(it)
                city.currentProdKinds.append(kind)
                if not city.currentProds:
                    city.currentProdType = kind
                it.advance(4)
                if kind > 4:
                    _fail("assertT(0)", it)
                city.currentProds.append(read_int(it))
                formation = read_int(it) if kind == PROD_UNIT else 0
                city.currentProdFormations.append(formation)
                it.advance(12)
            it.advance(40)
            _rmap(it)
            _rmap(it)
            building_progress = _rmap(it)
            _rmap(it, 2)
            unit_progress = _rmap(it)
            district_progress = _rmap(it)
            project_progress = _rmap(it)
            if city.currentProds:
                current = city.currentProds[0] & 0xFFFFFFFF
                progress = (building_progress.get(current) or unit_progress.get(current)
                            or district_progress.get(current) or project_progress.get(current) or 0)
                city.currentProdProgress = progress / 256.0
            _rmap(it, 2)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            _rarray(it)
            it.advance(8)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(12)
            _rmap(it)
            _rmap(it)
            it.advance(9)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(12)
            it.advance(4)
            _rmap(it, city.built, 2)
            # Unlike the upstream walker, keep this
            # array away, but it is the city's {building hash: pillaged} map -
            # the game's ``pCityBuildings:IsPillaged`` state.  See
            # _port_helpers.read_building_flags for the byte-level evidence.
            city.pillagedBuildings = read_building_flags(it)
            _rmap(it, 2)
            _rmap(it, 2)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(12)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(12)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(12)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(8)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(4)
                count2 = read_int(it)
                for i in _range(count2, it):
                    it.advance(12)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(12)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(16)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(4)
            it.advance(4)
            it.advance(37)
            count = peek_u32(it)
            _check(count == 64, it)
            it.advance(4)
            for i in _range(count, it):
                it.advance(1)
            it.advance(4)
            for i in _range(14, it):
                _check(peek_u32(it) == 0x6, it)
                _rmap(it)
            it.advance(4)
            it.advance(1)
            it.advance(4)
            it.advance(3)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(13)
            it.advance(12)
            it.advance(49)
            it.advance(12)
            it.advance(4)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(24)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(20)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(16)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(32)
            it.advance(4)
            count = read_int(it, 3)
            it.advance(1)
            for i in _range(count, it):
                it.advance(8)
                count2 = read_int(it, 2)
                it.advance(count2)
                it.advance(12)
                count3 = read_int(it, 3)
                it.advance(1)
                for j in _range(count3, it):
                    count2 = read_int(it, 4)
                    for k in _range(count2, it):
                        it.advance(22)
            it.advance(8)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(4)
            _rarray(it, 4, 0)
            _rmap(it)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(8)
        it.advance(5)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(4)
        it.advance(8)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(8)
        _check(peek_u32(it) == 0x32, it)
        it.advance(4)
        it.advance(3137)
        _rmap(it)
        _rmap(it)
        it.advance(53)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(264)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(72)
        count = peek_u32(it)
        _check(count == 64, it)
        it.advance(4)
        for i in _range(count, it):
            count2 = peek_u32(it)
            it.advance(4)
            for k in _range(count2, it):
                it.advance(4)
                it.advance(4)
                it.advance(33)
                read_string(it)
                it.advance(4)
        it.advance(12)
        for i in _range(64, it):
            it.advance(16)
        for i in _range(64, it):
            it.advance(4)
        for i in _range(64, it):
            it.advance(4)
        it.advance(768)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(8)
        for i in _range(64, it):
            _check(peek_u32(it) == 0x32, it)
            it.advance(13)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(21)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(16)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(16)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
            it.advance(8)
        it.advance(86)
        count = read_int(it)
        _check(count == 64, it)
        for i in _range(count, it):
            it.advance(4)
        count = read_int(it)
        _check(count == 64, it)
        for i in _range(count, it):
            it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(16)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(8)
            count2 = read_int(it)
            for k in _range(count2, it):
                it.advance(8)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(14)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(8)
            count2 = read_int(it)
            for k in _range(count2, it):
                it.advance(20)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(8)
            count2 = read_int(it)
            for k in _range(count2, it):
                it.advance(4)
                count3 = read_int(it)
                for l in _range(count3, it):
                    it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(8)
            count2 = read_int(it)
            for k in _range(count2, it):
                it.advance(20)
        _rarray(it)
        _rarray(it, 4, 0)
        _rmap(it)
        it.advance(16)
        count = read_int(it)
        resize(p.districts, count)
        for i in _range(count, it):
            d = p.districts[i]
            read_int(it)
            _check(peek_u32(it) == 0x0f, it)
            it.advance(4)
            d.id = read_int(it, 2)
            it.advance(2)
            d.x = read_int(it)
            d.y = read_int(it)
            d.cityId = read_int(it, 2)
            it.advance(2)
            d.type = read_int(it)
            d.damage = read_int(it)
            d.wallDamage = read_int(it)
            it.advance(4)
            d.wall = read_int(it)
            d.cost = read_int(it)
            d.built = read_int(it)
            it.advance(1)
            for k in _range(3, it):
                _check(peek_u32(it) == 0x6, it)
                _rmap(it)
            it.advance(12)
            _check(peek_u32(it) == 0x6, it)
            _rmap(it)
            _check(peek_u32(it) == 0x6, it)
            _rmap(it)
            it.advance(4)
            count2 = peek_u32(it)
            it.advance(4)
            for k in _range(count2, it):
                it.advance(16)
            _rmap(it)
            it.advance(17)
            d.pillage = read_int(it, 1)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(8)
        it.advance(8)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(22)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(16)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        it.advance(4)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        _check(peek_u32(it) == count, it)
        it.advance(4)
        it.advance(count * 2)
        it.advance(4)
        p.government = read_int(it)
        it.advance(8)
        read_int(it)
        it.advance(4)
        it.advance(1)
        _rarray(it)
        _rmap(it)
        _rmap(it)
        for i in _range(5, it):
            _rarray(it)
        count = read_int(it)
        it.advance(4)
        for i in _range(count, it):
            policy = read_int(it)
            position = read_int(it)
            if position == 4:
                position = 3
            _check(position < 4, it)
            p.policies[position].append(policy)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(8)
        it.advance(4)
        it.advance(8)
        p.techDogmeInfo[DOGME].found = readMapBool(it)
        p.techDogmeInfo[DOGME].boost = readMapBool(it)
        readMapFloat(it)
        p.techDogmeInfo[DOGME].current = _rarray(it, 4, 0)
        it.advance(21)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            p.totalTourismByPlayer[i] = read_int(it)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            read_int(it, 1)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            read_int(it)
        it.advance(12)
        it.advance(12)
        it.advance(4)
        p.internalTourist = read_int(it)
        it.advance(8)
        count = read_int(it)
        _check(count == 0x40, it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(8)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
            it.advance(4)
            count2 = read_int(it)
            for j in _range(count2, it):
                it.advance(4)
                externalTourist = read_int(it)
                p.externalTourist += externalTourist
        count = read_int(it)
        for i in _range(count, it):
            it.advance(17)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        it.advance(1)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            _check(peek_u32(it) == 0x2D, it)
            it.advance(12)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            _check(peek_u32(it) == 0x2D, it)
            it.advance(13)
        it.advance(16)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(8)
        it.advance(4)
        it.advance(8)
        it.advance(8)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(13)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(16)
        _check(peek_u32(it) == 0x11, it)
        it.advance(8)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(24)
            count2 = read_int(it)
            for k in _range(count2, it):
                it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(40)
            count2 = read_int(it)
            for k in _range(count2, it):
                it.advance(4)
            it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(16)
        it.advance(4)
        it.advance(4)
        it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(44)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(16)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        _check(peek_u32(it) == 0x14, it)
        it.advance(4)
        it.advance(1)
        p.faith = read_int(it)
        it.advance(3)
        p.pantheon = read_int(it)
        it.advance(4)
        it.advance(8)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(24)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(13)
        it.advance(4)
        it.advance(44)
        it.advance(2)
        it.advance(4)
        it.advance(20)
        _rmap(it)
        it.advance(16)
        _rarray(it, 4,0)
        it.advance(4)
        _rarray(it)
        it.advance(13)
        # Luxury resources received from other sources are stored separately
        # from the current inventory amount; outgoing copies are already
        # reflected in that amount.
        count = read_int(it)
        for i in _range(count, it):
            resource = read_int(it)
            it.advance(4)
            p.resources[resource] = read_int(it)
            p.resourceReceived[resource] = read_int(it)
            read_int(it)  # given
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
            read_float(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(8)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
            read_int(it)
        _rmap(it)
        _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
            read_int(it)
        _rmap(it)
        _rmap(it)
        it.advance(32)
        it.advance(65)
        p.diploPoint = read_int(it, 3)
        it.advance(3)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(13)
            read_string(it)
            it.advance(22)
        it.advance(20)
        p.unitCopies = _rmap(it)
        _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        _rmap(it)
        it.advance(1888)
        p.techDogmeInfo[TECH].current = _rarray(it, 4, 0)
        it.advance(12)
        p.techDogmeInfo[TECH].found = readMapBool(it)
        p.techDogmeInfo[TECH].boost = readMapBool(it)
        readMapFloat(it)
        it.advance(8)
        it.advance(4)
        it.advance(4)
        it.advance(1)
        p.gold = read_int(it)
        it.advance(4)
        it.advance(4)
        it.advance(20)
        it.advance(4)
        it.advance(3)
        _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(8)
        it.advance(16)
        count = read_int(it)
        resize(p.units, count)
        for iUnit in _range(len(p.units), it):
            unit = p.units[iUnit]
            unit.id = read_int(it)
            count = peek_u32(it)
            it.advance(4)
            it.advance(4)
            unit.type = read_int(it)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            unit.x = read_int(it)
            unit.y = read_int(it)
            it.advance(17)
            unit.army = read_int(it)
            it.advance(8)
            unit.damage = read_int(it)
            it.advance(58)
            unit.fortified = read_int(it)
            it.advance(11)
            it.advance(199)
            for i in _range(4, it):
                it.advance(4)
            it.advance(4)
            it.advance(1)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(8)
            _rmap(it)
            _rarray(it)
            _rarray(it)
            _rarray(it)
            _rmap(it)
            _rmap(it)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(5)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(5)
            it.advance(6)
            unit.xp = read_int(it)
            unit.level = read_int(it)
            it.advance(12)
            _rarray(it)
            read_string(it)
            it.advance(77)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(12)
            it.advance(54)
            _check(peek_u32(it) == 6, it)
            _rmap(it)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(4)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            it.advance(66)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(13)
            count = read_int(it)
            for i in _range(count, it):
                it.advance(12)
            it.advance(70)
            count = peek_u32(it)
            it.advance(4)
            for i in _range(count, it):
                if peek_u32(it) == 0x580F2F68:
                    it.advance(44)
                elif peek_u32(it) == 0xb2cca377:
                    it.advance(44)
                elif peek_u32(it) == 0x8374D954:
                    it.advance(56)
                elif peek_u32(it) == 0x9C0B44C6:
                    it.advance(44)
                elif peek_u32(it) == 0x09d0292a:
                    it.advance(44)
                elif peek_u32(it) == 0x1d60e778:
                    it.advance(40)
                elif peek_u32(it) == 0x886ffcd1:
                    it.advance(44)
                elif peek_u32(it) == 0x4885d724:
                    it.advance(40)
                elif peek_u32(it) == 0x7fa205d1:
                    it.advance(44)
                elif peek_u32(it) == 0xcfb9b561:
                    it.advance(44)
                elif peek_u32(it) == 0xc8ce5dfb:
                    it.advance(44)
                elif peek_u32(it) == 0x8ca367f:
                    it.advance(40)
                elif peek_u32(it) == 0x1f633b1e:
                    it.advance(44)
                elif peek_u32(it) == 0x6e68aef:
                    it.advance(40)
                elif peek_u32(it) == 0x852ce4df:
                    it.advance(44)
                elif peek_u32(it) == 0x98eca9ea:
                    it.advance(48)
                else:
                    it.advance(32)
            _rarray(it)
            it.advance(16)
            count = read_int(it, 3)
            it.advance(1)
            for i in _range(count, it):
                count2 = read_int(it)
                for k in _range(count2, it):
                    it.advance(4)
                    read_string(it, 2)
                    it.advance(16)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(8)
        p.unitCosts = _rmap(it)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        _rarray(it)
        it.advance(3)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
            count2 = read_int(it)
            for i in _range(count2, it):
                it.advance(8)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(4)
        if peek_u32(it) == 0:
            it.advance(4)
        _rmap(it)
        it.advance(12)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(32)
        it.advance(44)
        _rmap(it)
        _rmap(it)
        _rarray(it, 4, 0)
        it.advance(4)
        it.advance(4)
        read_int(it)
        read_int(it)
        it.advance(52)
        for i in _range(2, it):
            it.advance(4)
            it.advance(64)
        for i in _range(13, it):
            _check(peek_u32(it) == 6, it)
            _rmap(it)
        it.advance(4)
        for i in _range(72, it):
            _check(peek_u32(it) == 6, it)
            _rmap(it)
        for k in _range(3, it):
            count = peek_u32(it)
            it.advance(4)
            for i in _range(count, it):
                it.advance(4)
                _check(peek_u32(it) == 6, it)
                _rmap(it)
        _rmap(it)
        for k in _range(4, it):
            count = peek_u32(it)
            it.advance(4)
            for i in _range(count, it):
                it.advance(4)
                _check(peek_u32(it) == 6, it)
                _rmap(it)
        it.advance(12)
        it.advance(8)
        readMapFloat(it)
        readMapFloat(it)
        readMapFloat(it)
        it.advance(10)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(10)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(41)
        # v0.32: the fixed region upstream skips ends with the game's
        # per-player influence block (see ``read_influence_tokens``); only its
        # 「剩余使者」counter is published, without changing the cursor position.
        p.envoyTokens = read_influence_tokens(it)
        count = read_int(it)
        for i in _range(count, it):
            emissaryCount = read_int(it)
            if emissaryCount != 0:
                if not len(p.emissaries):
                    resize(p.emissaries, playerCount)
                p.emissaries[i] = emissaryCount
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(1)
        _rmap(it)
        it.advance(16)
        _rmap(it)
        _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(20)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(12)
        _rmap(it)
        it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(8)
        it.advance(16)
        count = read_int(it)
        resize(p.governors, count)
        for i in _range(count, it):
            g = p.governors[i]
            g.id = read_int(it)
            it.advance(4)
            it.advance(4)
            g.type = read_int(it)
            read_string(it)
            g.cityOwner = read_int(it, 2)
            it.advance(2)
            g.city = read_int(it, 2)
            it.advance(2)
            g.established = read_governor_established(it.data, it.pos)
            it.advance(62)
            it.advance(4)
            it.advance(4)
            count2 = read_int(it)
            for i in _range(count2, it):
                it.advance(4)
                it.advance(4)
                g.turn = read_int(it)
            promotions = _rmap(it, 1)
            for _mit in promotions_items(promotions):
                if _mit[1] == 1:
                    g.promotions.append(_mit[0])
            it.advance(4)
            it.advance(1)
        it.advance(4)
        _rarray(it, 4, 0)
        it.advance(8)
        it.advance(4)
        it.advance(1)
        it.advance(8)
        it.advance(64)
        it.advance(4)
        it.advance(4)
        count = peek_u32(it)
        _check(count == 64, it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        count = peek_u32(it)
        _check(count == 64, it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(8)
        _rarray(it)
        _rarray(it)
        _rarray(it)
        it.advance(24)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(20)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(8)
        it.advance(2)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            type = peek_u32(it)
            it.advance(4)
            _check(peek_u32(it) == 3, it)
            it.advance(4)
            if type == 0:
                it.advance(61)
            elif type == 1:
                it.advance(48)
            elif type == 2:
                it.advance(44)
            elif type == 3:
                it.advance(44)
            elif type == 4:
                it.advance(44)
            else:
                _fail("assertT(0)", it)
        _check(peek_u32(it) == 2, it)
        it.advance(4)
        tileCount = peek_u32(it)
        it.advance(4)
        it.advance(tileCount*2)
        _check(peek_u32(it) == tileCount, it)
        it.advance(4)
        it.advance(tileCount*2)
        it.advance(24)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            _check(peek_u32(it) == p.cities[i].id, it)
            it.advance(4)
            _check(peek_u32(it) == 0x11, it)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            _check(peek_u32(it) == 0x6, it)
            p.cities[i].yields = readMapFloat(it)
            _check(peek_u32(it) == 0x6, it)
            readMapFloat(it)
            _rmap(it)
            it.advance(8)
            it.advance(9)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                it.advance(16)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                it.advance(4)
            it.advance(12)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                it.advance(12)
            it.advance(1)
            it.advance(16)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                it.advance(4)
            count2 = peek_u32(it)
            it.advance(4)
            it.advance(4)
            for j in _range(count2, it):
                it.advance(8)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                _check(peek_u32(it) == 0x04, it)
                it.advance(4)
                it.advance(4)
                _check(peek_u32(it) == 0x64, it)
                it.advance(4)
                it.advance(35)
                _check(peek_u32(it) == 0x40, it)
                count3 = peek_u32(it)
                it.advance(4)
                for k in _range(count3, it):
                    it.advance(4)
                it.advance(12)
            it.advance(20)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                it.advance(17)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                it.advance(8)
            it.advance(12)
            it.advance(16)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                _check(peek_u32(it) == 1, it)
                it.advance(4)
                it.advance(4)
                it.advance(61)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                _rmap(it)
                _rmap(it)
                _rmap(it)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            it.advance(8)
            _rmap(it)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(8)
        it.advance(4)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(12)
        it.advance(8)
        _check(peek_u32(it) == 3, it)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(8)
        it.advance(1)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            read_int(it)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            it.advance(8)
            read_int(it)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(34)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(32)
        _rmap(it)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
            it.advance(4)
            it.advance(4)
            read_int(it)
            read_int(it)
            read_int(it)
            read_int(it)
            it.advance(1)
        it.advance(8)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(8)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(1)
        it.advance(4)
        it.advance(1844)
        count = peek_u32(it)
        _check(count == 64, it)
        it.advance(4)
        for k in _range(count, it):
            it.advance(8)
            _check(peek_u32(it) == k, it)
            it.advance(4)
            read_string(it)
            it.advance(7)
            it.advance(4)
            count2 = peek_u32(it)
            it.advance(4)
            for i in _range(count2, it):
                it.advance(4)
            count2 = peek_u32(it)
            it.advance(4)
            for i in _range(count2, it):
                it.advance(4)
            count2 = peek_u32(it)
            it.advance(4)
            for i in _range(count2, it):
                it.advance(4)
            count2 = peek_u32(it)
            it.advance(4)
            for i in _range(count2, it):
                it.advance(20)
                read_string(it)
                it.advance(41)
                count3 = peek_u32(it)
                it.advance(4)
                for j in _range(count3, it):
                    it.advance(4)
                count3 = peek_u32(it)
                it.advance(4)
                for j in _range(count3, it):
                    it.advance(4)
                count3 = peek_u32(it)
                it.advance(4)
                for j in _range(count3, it):
                    it.advance(4)
            count2 = peek_u32(it)
            it.advance(4)
            for i in _range(count2, it):
                it.advance(4)
                read_string(it)
                it.advance(8)
        it.advance(5)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            _check(peek_u32(it) == 5, it)
            it.advance(4)
            value = peek_u32(it)
            if value == 0xffffffff:
                it.advance(21)
            else:
                it.advance(8)
                _rmap(it)
                _rmap(it)
                it.advance(13)
        it.advance(593)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            _rarray(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(24)
        it.advance(8)
        it.advance(1)
        it.advance(4)
        it.advance(4)
        it.advance(1)
        it.advance(19)
        p.maintenance = read_float(it)
        it.advance(4)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(8)
        it.advance(4)
        _rmap(it)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(12)
        it.advance(12)
        it.advance(8)
        it.advance(8)
        it.advance(1)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
            it.advance(8)
            it.advance(4)
            count2 = peek_u32(it)
            it.advance(4)
            it.advance(8 * count2)
            count2 = peek_u32(it)
            it.advance(4)
            it.advance(4 * count2)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            test = peek_u32(it)
            it.advance(4)
            it.advance(8)
            test2 = peek_u32(it)
            it.advance(4)
            _check(test == test2, it)
            count2 = peek_u32(it)
            it.advance(4)
            for j in _range(count2, it):
                it.advance(4)
            it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        it.advance(count)
        it.advance(8)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        count2 = peek_int(it, 3)
        it.advance(3)
        for k in _range(count2, it):
            it.advance(13)
            count = peek_u32(it)
            it.advance(4)
            for i in _range(count, it):
                it.advance(16)
            _check(peek_u32(it) == 0x05, it)
            it.advance(39)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            _rmap(it)
            _rmap(it)
        it.advance(12)
        for i in _range(4, it):
            _rarray(it)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        it.advance(8)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            _check(peek_u32(it) == 0x04, it)
            it.advance(4)
            type = read_int(it)
            ui = p.unitsInfo[type & 0xFFFFFFFF]
            ui.health = read_int(it)
            it.advance(7)
            read_int(it)
            read_int(it)
            ui.attack = read_int(it)
            read_int(it)
            it.advance(4)
            it.advance(280)
        it.advance(1)
        _rmap(it)
        it.advance(168)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        it.advance(21)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(4)
        it.advance(21)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(1)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(1)
        _rmap(it)
        _rmap(it)
        _rmap(it)
        it.advance(4)
        it.advance(4)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(16)
            read_string(it)
            it.advance(17)
            read_string(it)
            it.advance(4)
            count2 = peek_u32(it)
            it.advance(4)
            for k in _range(count2, it):
                _check(peek_u32(it) == 2, it)
                it.advance(25)
                count3 = peek_u32(it)
                it.advance(4)
                for k in _range(count3, it):
                    _check(peek_u32(it) == 2, it)
                    it.advance(29)
            it.advance(20)
            it.advance(11)
            read_string(it)
            it.advance(4)
            read_string(it)
            count2 = read_int(it)
            for k in _range(count2, it):
                it.advance(11)
                count3 = read_int(it)
                for l in _range(count3, it):
                    it.advance(4)
                count3 = read_int(it)
                for l in _range(count3, it):
                    it.advance(4)
                count3 = read_int(it)
                for l in _range(count3, it):
                    count4 = read_int(it)
                    it.advance(count4 * 4)
                count3 = read_int(it)
                for l in _range(count3, it):
                    it.advance(8)
                count3 = read_int(it)
                for l in _range(count3, it):
                    it.advance(4)
                it.advance(1)
                count3 = read_int(it)
                it.advance(count3 * 8)
                it.advance(8)
            for k in _range(3, it):
                it.advance(16)
            it.advance(8)
            for k in _range(3, it):
                it.advance(16)
            it.advance(8)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        it.advance(8)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        _rmap(it)
        _rmap(it)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(28)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(2)
        _rmap(it)
        _rmap(it, 1)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            read_int(it)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            it.advance(4)
            read_int(it)
            it.advance(8)
            it.advance(4)
        it.advance(1)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(12)
        it.advance(4)
        it.advance(4)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(8)
        it.advance(4)
        it.advance(4)
        it.advance(4)
        it.advance(8)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(12)
        count = peek_u32(it)
        if count == 0xffffffff:
            it.advance(4)
        it.advance(4)
        it.advance(4)
        _rmap(it, 1)
        it.advance(1)
        _check(peek_u32(it) == 0x07, it)
        it.advance(4)
        it.advance(4)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(51)
            count2 = peek_u32(it)
            it.advance(4)
            for k in _range(count2, it):
                it.advance(36)
            _rmap(it)
            _rarray(it)
            _rarray(it)
            _rmap(it)
            count2 = peek_u32(it)
            it.advance(4)
            for k in _range(count2, it):
                it.advance(4)
            _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(20)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(12)
        _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(17)
        globalCount = peek_int(it, 1)
        it.advance(4)
        for iOtherPlayer in _range(globalCount, it):
            it.advance(4)
            boolean = peek_int(it, 1)
            it.advance(1)
            if not boolean:
                continue
            count = peek_u32(it)
            it.advance(4)
            for k in _range(count, it):
                it.advance(4)
                unitCount = peek_u32(it)
                it.advance(4)
                for iUnit in _range(unitCount, it):
                    it.advance(36)
        it.advance(92)
        _rmap(it)
        _rmap(it)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(8)
        it.advance(4)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(20)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(20)
        it = _seek(data, END_IA_STUFF, it.pos)
        it.advance(-(4))
        _rmap(it)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(13)
        count = read_int(it)
        for i in _range(count, it):
            it.advance(16)
        count = peek_u32(it)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        count = peek_int(it, 3)
        it.advance(4)
        if count != 0:
            it = _seek(data, END_PLAYER_STUFF, it.pos)
            it.advance(-(4))
        _rmap(it)
        count = peek_int(it, 4)
        it.advance(4)
        for i in _range(count, it):
            it.advance(4)
        _rarray(it, 4,0)
        _rarray(it, 4, 0)
        _rarray(it, 4, 0)
    try:
        _parse_post_players(it, data, players, playerCount, warnings)
    except Exception as exc:
        # ``type`` is a local variable name in this ported walker, so the
        # builtin is reached through the instance instead.
        warnings.append(
            f"players tail: {exc.__class__.__name__}: {exc} "
            f"(offset 0x{it.pos:x})")
    return warnings


def _parse_post_players(it, data, players, playerCount, warnings) -> None:
    """Walk everything that follows the per-player records.

    Kept separate from :func:`parse_players` so a shift in this (rarely
    inspected) region cannot discard the per-player data; the tail blocks are
    parsed one segment at a time by :func:`_parse_tail`.
    """
    it.advance(28)
    read_int(it)
    for i in _range(playerCount, it):
        _check(peek_u32(it) == 0x04, it)
        it.advance(4)
        it.advance(4)
        _check(peek_u32(it) == 0x02, it)
        it.advance(4)
        count = read_int(it)
        for j in _range(count, it):
            _check(peek_u32(it) == 0x03, it)
            it.advance(64)
        it.advance(61)
    it.advance(4)
    count2 = read_int(it)
    for i in _range(count2, it):
        it.advance(14)
        count = read_int(it)
        for j in _range(count, it):
            it.advance(4)
            it.advance(8)
            it.advance(4)
            it.advance(9)
        count = read_int(it)
        for j in _range(count, it):
            it.advance(12)
        it.advance(13)
        count = read_int(it)
        for j in _range(count, it):
            it.advance(41)
            count3 = read_int(it)
            for k in _range(count3, it):
                it.advance(4)
        _rmap(it)
    it.advance(24)
    _check(peek_u32(it) == 0x06, it)
    _rmap(it)
    _rmap(it)
    it.advance(28)
    it.advance(1)
    _check(peek_u32(it) == 0x40, it)
    count = read_int(it)
    for j in _range(count, it):
        it.advance(4)
    count = read_int(it)
    for i in _range(count, it):
        it.advance(16)
        it.advance(65)
        count2 = read_int(it)
        for j in _range(count2, it):
            read_string(it)
        it.advance(12)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(8)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(8)
        it.advance(8)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(20)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(4)
        it.advance(8)
        _check(peek_u32(it) == 0x40, it)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(4)
        _check(peek_u32(it) == 0x40, it)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(24)
            count3 = read_int(it)
            for k in _range(count3, it):
                it.advance(4)
            it.advance(20)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(8)
    count = read_int(it)
    for i in _range(count, it):
        it.advance(8)
    it.advance(4)
    count2 = read_int(it)
    for i in _range(count2, it):
        it.advance(16)
    it.advance(4)
    it.advance(12)
    count2 = read_int(it)
    for i in _range(count2, it):
        it.advance(37)
        _rarray(it, 4, 1)
        _rarray(it, 4, 1)
    it.advance(4)
    it.advance(5)
    it.advance(21)
    count2 = read_int(it)
    for i in _range(count2, it):
        it.advance(16)
        count = read_int(it)
        for j in _range(count, it):
            it.advance(28)
            it.advance(20)
            it.advance(20)
            _check(peek_u32(it) == 0x06, it)
            _rmap(it)
            _rmap(it)
            it.advance(8)
            it.advance(1)
            count3 = read_int(it)
            for k in _range(count3, it):
                it.advance(4)
            it.advance(37)
    it.advance(8)
    it.advance(1)
    count2 = read_int(it)
    for i in _range(count2, it):
        _check(peek_u32(it) == 0x05, it)
        it.advance(4)
        read_int(it)
        read_int(it)
        read_int(it)
        read_int(it)
        read_int(it)
        it.advance(4)
    count2 = read_int(it)
    for i in _range(count2, it):
        read_int(it)
        _check(peek_u32(it) == 0x05, it)
        it.advance(4)
        read_int(it)
        it.advance(4)
        read_int(it)
        read_int(it)
        it.advance(8)
    count = read_int(it)
    for i in _range(count, it):
        _check(peek_u32(it) == 0x05, it)
        it.advance(12)
    count = read_int(it)
    for i in _range(count, it):
        _check(peek_u32(it) == 0x05, it)
        it.advance(16)
    it.advance(8)
    questParameterCount = 0
    count = read_int(it)
    for i in _range(count, it):
        it.advance(16)
        # v0.25: hashes are unsigned; ``read_int`` sign-extends 4-byte reads, so
        # 0x89E97D38 (the "no parameter record" quest type) never matched and the
        # walker consumed one 8-byte record too many, drifting for every save
        # that has this quest — which is what made age / commemoration data
        # unreachable from turn 7 onwards.
        quest = read_int(it) & 0xFFFFFFFF
        it.advance(12)
        if quest != 0x89e97d38  and  quest != 0x0c41aa65:
            questParameterCount += 1
    count2 = read_int(it)
    for i in _range(count2, it):
        it.advance(16)
        quest = read_int(it) & 0xFFFFFFFF
        it.advance(12)
        if quest != 0x89e97d38  and  quest != 0x0c41aa65:
            questParameterCount += 1
    for i in _range(questParameterCount, it):
        it.advance(8)
    it.advance(4)
    count = read_int(it)
    for i in _range(count, it):
        it.advance(8)
        it.advance(4)
        it.advance(8)
        it.advance(2)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(4)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(4)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(1)
        it.advance(4)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(1)
        count2 = read_int(it)
        for j in _range(count2, it):
            read_string(it)
        it.advance(1)
        _check(peek_u32(it) == 0x40, it)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(4)
    count = read_int(it)
    for i in _range(count, it):
        it.advance(24)
    it.advance(4)
    count = read_int(it)
    for i in _range(count, it):
        it.advance(28)
    it.advance(4)
    it.advance(16)
    count = read_int(it)
    for i in _range(count, it):
        it.advance(12)
    it.advance(4)
    it.advance(16)
    it.advance(12)
    it.advance(12)
    it.advance(6)
    _check(peek_u32(it) == 0x40, it)
    count = read_int(it)
    for i in _range(count, it):
        it.advance(4)
    _check(peek_u32(it) == 0x40, it)
    count = read_int(it)
    for i in _range(count, it):
        it.advance(4)
    it.advance(4)
    it.advance(4)
    count = read_int(it)
    for i in _range(count, it):
        _check(peek_u32(it) == 0x1C, it)
        it.advance(4)
        it.advance(4)
        it.advance(21)
        count2 = read_int(it)
        for i in _range(count2, it):
            it.advance(4)
        count2 = read_int(it)
        for i in _range(count2, it):
            it.advance(4)
        read_string(it)
    count = read_int(it)
    for i in _range(count, it):
        _check(peek_u32(it) == 0x1C, it)
        it.advance(4)
        it.advance(4)
        it.advance(21)
        count2 = read_int(it)
        for i in _range(count2, it):
            it.advance(4)
        read_string(it)
    count = read_int(it)
    for i in _range(count, it):
        _check(peek_u32(it) == 0x1C, it)
        it.advance(4)
        it.advance(4)
        it.advance(12)
        read_string(it)
        it.advance(8)
    it.advance(36)
    count = read_int(it)
    for i in _range(count, it):
        _check(peek_u32(it) == 0x04, it)
        it.advance(4)
        it.advance(4)
        it.advance(12)
        it.advance(8)
        it.advance(4)
        it.advance(24)
        read_string(it)
        it.advance(1)
    it.advance(1)
    it.advance(23)
    count = read_int(it)
    for i in _range(count, it):
        it.advance(12)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(4)
        count2 = read_int(it)
        for j in _range(count2, it):
            it.advance(1)
    it.advance(4)
    _rmap(it)
    _rmap(it)
    it.advance(24)
    it.advance(8)
    count = read_int(it)
    for i in _range(count, it):
        _check(peek_u32(it) == 0x08, it)
        it.advance(4)
        it.advance(4)
        it.advance(4)
        it.advance(8)
        it.advance(9)
        it.advance(4)
        count2 = read_int(it)
        for i in _range(count2, it):
            it.advance(4)
            it.advance(4)
        read_string(it)
        read_string(it)
        read_string(it)
        it.advance(4)
    it.advance(4)
    it.advance(4)
    it.advance(4)
    _parse_tail(it, players, warnings)


# --- v0.25: the shared "tail" blocks ----------------------------------------
#
# Golden / dark age flags, commemorations (golden-age dedications) and era
# points live in the blocks that follow the per-player records.  They are the
# part of the players layer that starts to drift first when a game patch or a
# MOD shifts a field: the walker above lands a few bytes off and then reads a
# loop count out of unrelated data, which used to abort the whole layer.
#
# Every block is now parsed on its own, with boundary checks on every count, so
# one bad block costs only its own data.  When a block fails, the cursor scans
# forward for the next ``0x40`` / ``0x1E`` anchor with a plausible count and
# resumes there.

TAIL_BLOCK_MARKER = 0x40
TAIL_RECORD_MARKER = 0x1E
# how far ``_resync_tail`` may look for the next anchor before giving up
TAIL_RESYNC_WINDOW = 1 << 16


def _tail_count(it, players, label: str) -> int:
    """Read a per-player block count and validate it against ``players``."""
    count = read_int(it)
    if not (0 <= count <= len(players)):
        _fail(f"{label}: implausible per-player count {count}", it)
    return count


def _tail_inner_count(it, label: str) -> int:
    """Read a nested list count (eras / choices / trailing values)."""
    count = read_int(it)
    if not (0 <= count <= 4096):
        _fail(f"{label}: implausible nested count {count}", it)
    return count


def _tail_ages(it, players) -> None:
    """``0x40`` + golden flags + dark flags (one byte per player)."""
    _check(peek_u32(it) == TAIL_BLOCK_MARKER, it)
    count = _tail_count(it, players, "age/golden")
    for i in range(count):
        if peek_byte(it) == 1:
            players[i].ageState = GOLDEN
        it.advance(1)
    count = _tail_count(it, players, "age/dark")
    for i in range(count):
        if peek_byte(it) == 1:
            players[i].ageState = DARK
        it.advance(1)


def _tail_commemorations(it, players) -> None:
    """``0x40`` + one ``0x1E``-prefixed record per player (dedication hashes)."""
    _check(peek_u32(it) == TAIL_BLOCK_MARKER, it)
    count = _tail_count(it, players, "commemorations")
    for i in range(count):
        p = players[i]
        _check(peek_u32(it) == TAIL_RECORD_MARKER, it)
        it.advance(4)
        count2 = _tail_inner_count(it, "commemoration eras")
        it.advance(4 * count2)
        it.advance(4)
        count2 = _tail_inner_count(it, "commemoration choices")
        for _ in range(count2):
            # hashes are unsigned: ``read_int`` sign-extends 4-byte reads
            p.commemorations.append(read_int(it) & 0xFFFFFFFF)
            if len(p.commemorations) == 3:
                p.ageState = HEROIC
        it.advance(4)


def _tail_era_points(it, players) -> None:
    """``0x40`` + three score tables and bases with a counted shift list."""
    _check(peek_u32(it) == TAIL_BLOCK_MARKER, it)
    count = _tail_count(it, players, "eraPoint")
    for i in range(count):
        _check(peek_u32(it) == TAIL_RECORD_MARKER, it)
        it.advance(4)
        it.advance(4)
        players[i].eraPoint = read_int(it)
        it.advance(43 * 4)
    count = _tail_count(it, players, "eraPointInitEra")
    for i in range(count):
        _check(peek_u32(it) == TAIL_RECORD_MARKER, it)
        it.advance(4)
        it.advance(4)
        read_int(it)
        it.advance(43 * 4)
    count = _tail_count(it, players, "eraPoint/skip")
    for i in range(count):
        _check(peek_u32(it) == TAIL_RECORD_MARKER, it)
        it.advance(4)
        it.advance(4)
        it.advance(44 * 4)
    count = _tail_count(it, players, "eraPointThresholds")
    for i in range(count):
        _check(peek_u32(it) == TAIL_RECORD_MARKER, it)
        it.advance(4)
        # The saved bases already include the era-start score and game-speed
        # scaling, but NOT the following threshold shifts. The game reconstructs
        # each target as max(0, base + sum(breakdown)) when loading this record.
        # Use the saved shifts, not today's city count or installed rules.
        golden_base = read_int(it)
        normal_base = read_int(it)
        it.advance(4)
        shift_count = _tail_inner_count(it, "era threshold shifts")
        shift = sum(read_int(it) for _ in range(shift_count))
        if 0 <= normal_base <= golden_base and golden_base > 0:
            players[i].eraNormalThreshold = max(0, normal_base + shift)
            players[i].eraGoldenThreshold = max(0, golden_base + shift)


def _tail_trailing(it, players) -> None:
    """Four ``0x40`` + ``count * 4`` tables and one ``0x1E`` record table."""
    for _ in range(4):
        _check(peek_u32(it) == TAIL_BLOCK_MARKER, it)
        count = _tail_count(it, players, "trailing")
        it.advance(4 * count)
    _check(peek_u32(it) == TAIL_BLOCK_MARKER, it)
    count = _tail_count(it, players, "trailing records")
    for _ in range(count):
        _check(peek_u32(it) == TAIL_RECORD_MARKER, it)
        it.advance(4)
        it.advance(60)


TAIL_SEGMENTS = (
    ("age", _tail_ages),
    ("commemorations", _tail_commemorations),
    ("eraPoints", _tail_era_points),
    ("trailing", _tail_trailing),
)


def _resync_tail(it, label: str) -> bool:
    """Scan forward for the next ``0x40`` + plausible count anchor.

    Returns ``False`` when no anchor turns up within
    :data:`TAIL_RESYNC_WINDOW` bytes, in which case the remaining segments are
    reported lost rather than guessed at.
    """
    start = it.pos
    end = min(len(it.data) - 8, start + TAIL_RESYNC_WINDOW)
    pos = start
    while pos < end:
        if u32(it.data, pos) == TAIL_BLOCK_MARKER:
            count = u32(it.data, pos + 4)
            if 0 <= count <= 64:
                it.pos = pos
                return True
        pos += 4
    it.pos = start
    return False


def _parse_tail(it, players, warnings) -> None:
    """Parse the shared tail blocks, one guarded segment at a time."""
    it.advance(10)
    for label, segment in TAIL_SEGMENTS:
        try:
            segment(it, players)
        except Exception as exc:
            warnings.append(
                f"players tail/{label}: {exc.__class__.__name__}: {exc} "
                f"(offset 0x{it.pos:x})")
            if not _resync_tail(it, label):
                warnings.append(
                    f"players tail/{label}: no anchor within "
                    f"{TAIL_RESYNC_WINDOW} bytes; later tail blocks are unavailable")
                return
