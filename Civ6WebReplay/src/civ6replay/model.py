"""Dataclasses for the state consumed by the replay tool.

Player / City / Unit / Religion keep the C++ member names so the ported
parser code (``players.py``) reads the same as the source.  Free-form
sub-records (districts, unitsInfo) use ``Record`` which accepts arbitrary
attributes.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

NONE_U32 = 0xFFFFFFFF

# AgeState
DARK, NORMAL, GOLDEN, HEROIC = 0, 1, 2, 3
# TechDogmeType
TECH, DOGME = 0, 1


class Record:
    """A permissive record: missing attributes read back as 0."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        value: Any = 0
        object.__setattr__(self, name, value)
        return value


@dataclass
class TechDogmeInfo:
    found: Dict[int, bool] = field(default_factory=dict)
    boost: Dict[int, bool] = field(default_factory=dict)
    current: List[int] = field(default_factory=list)


@dataclass
class Tile:
    terrain: int = NONE_U32
    feature: int = NONE_U32
    resource: int = NONE_U32
    improvment: int = NONE_U32
    road: int = 0
    roadLvl: int = 0
    appeal: int = 0
    continent: int = 0
    river: int = 0
    riverCount: int = 0
    cliffbitmap: int = 0
    bOverlay: int = 0
    wonder: int = NONE_U32
    pillage: int = 0
    isLake: Optional[bool] = None

    iPlayer: int = 0xFFFF
    iCity: int = 0xFFFF
    iDistrict: int = 0xFFFF


@dataclass
class Unit:
    x: int = 0
    y: int = 0
    id: int = 0
    type: int = NONE_U32
    xp: int = 0
    damage: int = 0
    army: int = 0
    level: int = 0
    fortified: int = 0
    iPlayer: int = -1

    @property
    def exist(self) -> bool:
        return self.x != -9999 or self.y != -9999


@dataclass
class City:
    id: int = 0
    x: int = 0
    y: int = 0
    population: int = 0
    religion: int = NONE_U32
    name: str = ""
    nameKey: str = ""            # raw name token from the save (LOC_... or rename)
    yields: Dict[int, int] = field(default_factory=dict)
    currentProds: List[int] = field(default_factory=list)
    currentProdType: int = 0
    built: Dict[int, int] = field(default_factory=dict)
    # {building hash: 1} for the buildings this city has *pillaged* (the game
    # tracks it per building; the host district's own flag is ``District.pillage``)
    pillagedBuildings: Dict[int, int] = field(default_factory=dict)
    iPlayer: int = -1


@dataclass
class Governor:
    id: int = 0
    type: int = NONE_U32
    city: int = 0
    turn: int = 0
    promotions: List[int] = field(default_factory=list)
    # Read from the serialized activity flag; unknown formats retain None.
    established: Optional[bool] = None


@dataclass
class Religion:
    iSymbol: int = 0
    iPlayer: int = 0
    name: str = ""
    beliefs: List[int] = field(default_factory=list)


@dataclass
class Player:
    iPlayer: int = -1
    units: List[Unit] = field(default_factory=list)
    unitsInfo: Dict[int, Any] = field(default_factory=lambda: defaultdict(Record))
    cities: List[City] = field(default_factory=list)
    districts: List[Any] = field(default_factory=list)
    governors: List[Any] = field(default_factory=list)

    yields: Dict[int, int] = field(default_factory=dict)
    totalYields: Dict[int, int] = field(default_factory=dict)

    techDogmeInfo: List[TechDogmeInfo] = field(
        default_factory=lambda: [TechDogmeInfo(), TechDogmeInfo()])

    totalTourismByPlayer: List[int] = field(default_factory=lambda: [0] * 64)
    externalTourist: int = 0
    internalTourist: int = 0

    gold: int = 0
    maintenance: float = 0.0
    faith: int = 0
    diploFavor: int = 0
    diploPoint: int = 0

    pantheon: int = NONE_U32
    totalPop: int = 0
    militaryStrength: int = 0

    government: int = NONE_U32
    policies: List[List[int]] = field(default_factory=lambda: [[], [], [], []])
    # Save resource inventory includes strategic stocks and luxury copies.
    resources: Dict[int, int] = field(default_factory=dict)

    visible: List[int] = field(default_factory=list)

    emissaries: List[int] = field(default_factory=list)
    # v0.32: 剩余使者 = the unspent envoy tokens the top bar shows next to
    # ``[ICON_Envoy]`` (only meaningful for major civs - the same word inside a
    # city-state's record is a different counter, see players.parse_players).
    envoyTokens: int = 0

    # v0.31: WMD stockpile (``nukes.parse_wmd``): {WMD type hash: count}
    wmd: Dict[int, int] = field(default_factory=dict)

    ageState: int = NORMAL
    eraPoint: int = 0
    eraNormalThreshold: Optional[int] = None
    eraGoldenThreshold: Optional[int] = None
    commemorations: List[int] = field(default_factory=list)
    # Optional runtime conditions used by plot yields. Never infer from techs/city order.
    eraType: Optional[str] = None
    atPeace: Optional[bool] = None
    capitalContinent: Optional[int] = None
    suzerainBonusEnabled: Optional[bool] = None

    unitCount: int = 0


@dataclass
class PlayerInfo:
    iPlayer: int = -1
    team: int = NONE_U32
    iColor: int = 0
    leader: int = NONE_U32
    civ: int = NONE_U32
    civStr: str = ""
    leaderStr: str = ""
    pseudo: str = ""
    pseudoWithSteamId: str = ""
    locCivName: str = ""
    typePlayer: int = 0
    typeCiv: int = NONE_U32
    primaryColor: tuple = (1.0, 0.0, 0.0, 0.7)
    secondaryColor: tuple = (0.0, 0.0, 0.0, 0.7)


@dataclass
class GameState:
    bcy: Dict[str, Optional[int]] = field(default_factory=dict)
    seed: int = 0
    turn: int = 0
    eraType: Optional[str] = None
    width: int = 44
    height: int = 0
    timestamp: int = 0
    map_name: str = ""
    map_key: str = ""
    map_size: str = ""
    game_speed: str = ""
    multiplayer: bool = False
    tiles: List[Tile] = field(default_factory=list)
    # v0.31: contamination turns per tile (``nukes.parse_fallout``), same order
    # as ``tiles``; 0 = clean.
    fallout: List[int] = field(default_factory=list)
    players: List[Player] = field(default_factory=list)
    playersInfo: List[PlayerInfo] = field(default_factory=list)
    religions: List[Religion] = field(default_factory=list)
    layerErrors: List[Any] = field(default_factory=list)
    # v0.25: non-fatal "the tail of the players block could not be walked"
    # notes; they never render in the UI, only in ``/api/replay/{seed}``.
    tailWarnings: List[str] = field(default_factory=list)
    # v0.26.1: every MOD / DLC title recorded in the save header (the title dicts
    # are plain JSON, so they can be read without walking the binary layout) and
    # the balance MOD that decides the city-wall numbers, if any.
    mods: List[str] = field(default_factory=list)
    modPackages: List[dict] = field(default_factory=list)
    balanceMod: str = ""
    # v0.39: 存档启用的不支持玩法（``modes.parse_game_modes`` 的 ``GAMEMODE_*``）
    # 与「整局判为不支持」的结果（``unsupported.verdict``，``None`` = 正常复盘）。
    # 命中时 ``state`` 只剩头部信息 —— 地图 / 玩家 / 回合数据都不解析。
    gameModes: List[str] = field(default_factory=list)
    unsupported: Optional[dict] = None
