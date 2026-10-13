"""存档「不支持」判定（v0.39）。

两条互不相干的来源：

* **黑名单 MOD**（:func:`civ6replay.mods.blacklisted_mods`）——标题命中结社 /
  CCB 受命于天 / CCB 纪元回响 / Team PVP 的 MOD；
* **不支持的玩法**（:func:`civ6replay.modes.parse_game_modes`）——存档启用了
  秘密结社或垄断与公司，**原版存档也算**，因为这两个玩法改写总督与奢侈资源，
  本工具解析出来的数据会失真。

命中就整局判为不支持：:func:`civ6replay.state.parse_save` 直接收工，前端拿到
``unsupported`` 后在画布中间画个叉并提示（见 ``web/js/hexmap.js``）。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .modes import UNSUPPORTED_MODES
from .mods import blacklisted_mods


def verdict(mods=None, modes=None) -> Optional[Dict[str, object]]:
    """``None`` = 可以复盘；否则返回给前端用的判定结果。

    返回：``{title, message, lines, mods, modes, modeKeys}`` —— ``title`` 是画布
    上那行大字，``message`` 是顶栏提示，``lines`` 是画布上的补充行（一行一条）。

    **不点名**：``mods`` 里那份「是哪几个 MOD 命中」只随接口下发，供排查用，
    界面上一个都不写（需求：画叉提示「带有不支持的 MOD」就够了）。玩法不是 MOD，
    名字留在 ``lines`` 里（「玩法：秘密结社」），否则用户不知道为什么不支持。
    """
    bad_mods = blacklisted_mods(mods)
    bad_modes: List[str] = []
    for key in (modes or []):
        label = UNSUPPORTED_MODES.get(str(key), str(key))
        if label not in bad_modes:
            bad_modes.append(label)
    if not bad_mods and not bad_modes:
        return None
    if bad_mods and bad_modes:
        title = "存档带有不支持的 MOD 与玩法"
    elif bad_mods:
        title = "存档带有不支持的 MOD"
    else:
        title = "存档启用了不支持的玩法"
    lines: List[str] = []
    if bad_modes:
        lines.append("玩法：" + "、".join(bad_modes))
    message = title if not bad_modes else title + "：" + "、".join(bad_modes)
    return {
        "title": title,
        "message": message,
        "lines": lines,
        "mods": bad_mods,
        "modes": bad_modes,
        "modeKeys": [str(k) for k in (modes or [])],
    }
