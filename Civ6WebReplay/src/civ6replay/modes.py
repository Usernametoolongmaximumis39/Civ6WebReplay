"""The save's enabled *game modes* (玩法) - 秘密结社 / 垄断与公司 / …

Civ6 把官方模式做成「配置参数」而不是 MOD：每个模式在配置库里是一个
``ConfigurationId``（``GAMEMODE_SECRETSOCIETIES``、``GAMEMODE_MONOPOLIES``、
``GAMEMODE_BARBARIAN_CLANS``…，见游戏 ``DLC/*/Data/*_ConfigData.xml`` 的
``GameModeItems``），存档头部把每个参数按 ``hash(ConfigurationId)`` 存成一个
bool：0 = 未启用，1 = 启用。哈希就是 :func:`civ6replay.hash.crc32_type`
（``~crc32``），与地图 / 单位那些 TYPE 串同一套。

所以**原版存档也能识别**：存档里既没有模式名字符串（头部只留哈希），也没有
额外的 MOD 条目（验证过：本机 40+ 个存档里 ``GAMEMODE_*`` 全为 0，头部没有任何
"GAMEMODE" 明文）。这里递归扫头部包树，只认本工具不支持的那两个：
结社与垄断都会改写总督 / 奢侈资源的数据，复盘出来的东西不可信（v0.39）。
"""
from __future__ import annotations

from typing import Dict, List

from .hash import crc32_type

# 不支持的玩法：ConfigurationId -> 游戏里的中文名（"秘密结社模式" / "垄断与公司模式"）
UNSUPPORTED_MODES: Dict[str, str] = {
    "GAMEMODE_SECRETSOCIETIES": "秘密结社",
    "GAMEMODE_MONOPOLIES": "垄断与公司",
}

_BY_HASH = {crc32_type(key): key for key in UNSUPPORTED_MODES}

# 参数就压在「游戏参数」对象里（``packets[2]/31``、``packets[6]/31``），留点余量
MAX_DEPTH = 6


def _enabled(value) -> bool:
    """bool 参数为真？（非 0 数字才算，字符串 / ``None`` 一律当未启用）"""
    return isinstance(value, int) and not isinstance(value, bool) and value != 0


def parse_game_modes(packets) -> List[str]:
    """``["GAMEMODE_SECRETSOCIETIES", …]``：该存档启用的**不支持**玩法。

    ``packets`` 是 :func:`civ6replay.container.parse_all` 的结果；解析失败 / 老
    存档里没有这些参数时返回 ``[]``（照常复盘）。
    """
    out: List[str] = []

    def walk(packet, depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        mode = _BY_HASH.get(int(packet.marker) & 0xFFFFFFFF)
        if mode and mode not in out and _enabled(packet.value):
            out.append(mode)
        for sub in packet.packets.values():
            walk(sub, depth + 1)

    for top in (packets or ()):
        walk(top, 0)
    return out
