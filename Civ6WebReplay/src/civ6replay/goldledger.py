"""金币流水账：从文明6日志统计「打钱 / 吸钱 / 净金币交易」。

口径沿用 ``elaphantguys_gold_script.exe``（复利 1.036/回合、``Turn N,`` 回合编号、
``from player`` / ``to player`` / ``amount`` / ``duration`` 的取法），是仓库里
``goldledger/gold.js`` 的 Python 移植版，两者数字应当一致。

数据来源（只读，不修改任何文件）：

* ``DiplomacyDeals.log`` —— 成交明细，一行一个 item
* ``GameCore.log`` —— ``SlotStatus - Human`` 用来认哪些槽位是玩家
* ``Player_Stats.csv`` —— 只用它的首列拿"日志当前回合"（首列比实际回合大 1）

日志目录由游戏自己维护，与存档目录不同：存档在
``Documents\\My Games\\Sid Meier's Civilization VI\\Saves\\...``，日志在
``%LOCALAPPDATA%\\Firaxis Games\\Sid Meier's Civilization VI\\Logs``。
``resolve_log_dir`` 会先找存档目录同级的 ``Logs``，再退回 AppData。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

INTEREST_AMOUNT = 1.036
CUSTOM_CIV_CREATOR_ALIASES = ("SUK", "LIME")

#: 范围键 -> 窗口回合数（``None`` = 从第 1t 起）
RANGE_TURNS = {"all": None, "5": 5, "10": 10, "30": 30}
DEFAULT_RANGE = "all"

DEALS_LOG = "DiplomacyDeals.log"
GAMECORE_LOG = "GameCore.log"
STATS_CSV = "Player_Stats.csv"

RE_TURN = re.compile(r"^Turn\s+(\d+)\s*,")
RE_TYPE_GOLD = re.compile(r"type\s+Gold\b", re.I)
RE_TYPE_ANY = re.compile(r"type\s+[A-Za-z_]")
RE_LEADING_INT = re.compile(r"^[+-]?\d+")

# 核对"日志是不是本局"用的宽松模式：一行里同时出现 Player N: 与 CIVILIZATION_*
RE_PLAYER_LINE = re.compile(r"Player\s+(\d+)\s*:")
RE_CIV_TOKEN = re.compile(r"CIVILIZATION_[A-Z0-9_]+")
# 日志里若写了地图 / 游戏种子，就是最硬的同一局证据（没写就退回槽位核对）
RE_SEED = re.compile(r"(?i)\b(?:game|map)\s*seed\b[^0-9]{0,6}(\d{1,10})")

#: 日志新鲜度上限（小时）。游戏每回合都会重写这几个日志，写时间离现在越近越可信；
#: 超过这个时长就当"隔夜账"不再显示金币流水（可用 CIV6_GOLD_FRESH_HOURS 覆盖）。
LOG_FRESH_HOURS = 6.0


def fresh_hours() -> float:
    raw = os.environ.get("CIV6_GOLD_FRESH_HOURS")
    try:
        value = float(raw)
        return value if value > 0 else LOG_FRESH_HOURS
    except (TypeError, ValueError):
        return LOG_FRESH_HOURS


# --------------------------------------------------------------- 日志目录定位
def log_dir_candidates(save_dir: Optional[str] = None,
                       override: Optional[str] = None) -> List[Path]:
    """按优先级列出可能的日志目录（去重，保持顺序）。"""
    out: List[Path] = []
    if override:
        out.append(Path(override))
    env = os.environ.get("CIV6_LOG_DIR")
    if env:
        out.append(Path(env))
    if save_dir:
        p = Path(save_dir)
        if p.name.lower() == "logs":
            out.append(p)
        out.append(p / "Logs")
        for _ in range(5):                       # 存档目录往上找同级的 Logs
            p = p.parent
            if not p.name:
                break
            out.append(p / "Logs")
    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    local = os.environ.get("LOCALAPPDATA") or str(Path(home) / "AppData" / "Local")
    civ6 = "Sid Meier's Civilization VI"
    out.append(Path(local) / "Firaxis Games" / civ6 / "Logs")
    out.append(Path(home) / "AppData" / "Local" / "Firaxis Games" / civ6 / "Logs")
    out.append(Path(home) / "Documents" / "My Games" / civ6 / "Logs")
    if save_dir:
        out.append(Path(save_dir))
    seen, uniq = set(), []
    for d in out:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq


def resolve_log_dir(save_dir: Optional[str] = None,
                    override: Optional[str] = None):
    """返回 ``(日志目录 或 None, 试过的候选目录)``。"""
    tried = log_dir_candidates(save_dir, override)
    for d in tried:
        if d.is_dir() and any((d / f).exists() for f in (DEALS_LOG, GAMECORE_LOG, STATS_CSV)):
            return d, tried
    for d in tried:                              # 目录在、但一个文件都没有
        if d.is_dir():
            return d, tried
    return None, tried


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None                              # 游戏每回合会删掉并重建这些日志


# --------------------------------------------------------------- 单行解析
def _sections(line: str) -> List[str]:
    return line.split(",")


def get_deal_from_line(line: str) -> Dict[str, int]:
    """一个 item 行的 ``from / to / amount / duration``（与原程序同顺序同取法）。"""
    deal = {"from": -1, "to": -1, "amount": -1, "duration": -1}
    for section in _sections(line):
        if "from player" in section:
            deal["from"] = _to_int(section.split(" ")[-1])
        elif "to player" in section:
            deal["to"] = _to_int(section.split(" ")[-1])
        elif "amount" in section:
            deal["amount"] = _to_int(section.split(" ")[-1])
        elif "duration" in section:
            deal["duration"] = _to_int(section.split(" ")[-1])
    return deal


def _to_int(token: str, default: int = -1) -> int:
    """像 JS 的 ``parseInt`` 一样取前导整数（``"0:"`` -> 0，``"x"`` -> default）。"""
    if token is None:
        return default
    m = RE_LEADING_INT.match(str(token).strip())
    return int(m.group(0)) if m else default


def is_gold_item(line: str, legacy: bool = False) -> bool:
    """这一行是不是一笔金币付款。

    原程序只要求整行含 ``YIELD_GOLD``；实测那会把"价值字段里写了 YIELD_GOLD 的
    资源行"也算成一笔金币转账（幻影金币），所以默认再要求 item 的 ``type`` 就是
    ``Gold``，``legacy=True`` 可切回原口径做对照。
    """
    if "YIELD_GOLD" not in line:
        return False
    if legacy:
        return True
    if RE_TYPE_ANY.search(line):
        return bool(RE_TYPE_GOLD.search(line))
    return True


def parse_deals(text: Optional[str], legacy: bool = False) -> List[Dict[str, int]]:
    """``DiplomacyDeals.log`` -> 金币交易条目。"""
    deals: List[Dict[str, int]] = []
    if not text:
        return deals
    turn = 1
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = RE_TURN.match(line)
        if m:
            turn = int(m.group(1))
        if is_gold_item(line, legacy):
            deal = get_deal_from_line(line)
            deal["turn"] = turn
            deals.append(deal)
    return deals


def civ_display_name(raw_civ: str) -> str:
    parts = raw_civ.split("_")
    if any(a in raw_civ for a in CUSTOM_CIV_CREATOR_ALIASES):
        return parts[2] if len(parts) > 2 else raw_civ
    return parts[1] if len(parts) > 1 else raw_civ


def parse_game_core(text: Optional[str]) -> Dict[int, Dict]:
    """``GameCore.log`` -> ``{槽位: {"civ": ..., "name": ..., "human": bool}}``。

    **所有**槽位都收（不只 Human）：``human`` 标记用于统计口径，整表用于核对
    "这些日志是不是正在复盘的这一局"。
    """
    out: Dict[int, Dict] = {}
    if not text:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        m = RE_PLAYER_LINE.search(line)
        if not m:
            continue
        civ_match = RE_CIV_TOKEN.search(line)
        raw_civ = civ_match.group(0) if civ_match else ""
        slot = _to_int(m.group(1), default=-1)
        if slot < 0:
            continue
        out[slot] = {"civ": raw_civ or f"P{slot}",
                     "name": civ_display_name(raw_civ) if raw_civ else str(slot),
                     "human": "SlotStatus - Human" in line}
    return out


def log_seed(text: Optional[str]) -> Optional[int]:
    """日志里写的地图 / 游戏种子（没有就返回 None）。"""
    m = RE_SEED.search(text or "")
    return int(m.group(1)) if m else None


def file_ages_hours(directory: Path, names: Sequence[str], now: float) -> List[float]:
    """这些日志文件"最后一次写入"距 ``now`` 的小时数（缺失的跳过）。"""
    ages: List[float] = []
    for name in names:
        try:
            ages.append(max(0.0, (now - (directory / name).stat().st_mtime) / 3600.0))
        except OSError:
            pass
    return ages


def verify_log(save_players: Optional[Dict[int, str]],
               log_players: Dict[int, str], ages: Sequence[float],
               seed: Optional[int] = None, log_seed_value: Optional[int] = None,
               fresh_limit: Optional[float] = None):
    """判断这批日志"能不能看"：新鲜 + 属于本赛季 + 能对上槽位/文明。

    返回 ``(ok, reason, detail)``；``reason`` 是一句给用户看的短话。
    宁可少显示也不显示错——对不上 / 太旧 / 信息不足一律判 False。
    """
    limit = LOG_FRESH_HOURS if fresh_limit is None else float(fresh_limit)
    age = max(ages) if ages else None
    detail: Dict = {
        "freshHours": round(age, 2) if age is not None else None,
        "freshLimitHours": limit,
        "matched": 0,
        "compared": 0,
        "conflicts": [],
        "seed": log_seed_value,
    }
    if age is None:
        return False, "没有日志", detail
    if age > limit:
        return False, f"日志已过期（最后一次写入 {age:.1f} 小时前）", detail
    if log_seed_value is not None and seed:
        if int(log_seed_value) != int(seed):
            detail["seedMismatch"] = True
            return False, f"日志里的地图种子 {log_seed_value} 不是本赛季的 {seed}", detail
    if not save_players:
        return False, "读不到本局的玩家信息", detail
    if not log_players:
        return False, "日志里没有可核对的玩家信息", detail
    overlap = sorted(set(save_players) & set(log_players))
    detail["compared"] = len(overlap)
    if not overlap:
        return False, "日志与本局的槽位对不上", detail
    conflicts = [s for s in overlap
                 if str(save_players[s]).upper() != str(log_players[s]).upper()]
    detail["matched"] = len(overlap) - len(conflicts)
    detail["conflicts"] = [{"slot": s, "save": save_players[s], "log": log_players[s]}
                           for s in conflicts]
    if conflicts:
        c = detail["conflicts"][0]
        return False, f"日志与本局对不上（槽位 {c['slot']}：本局 {c['save']}，日志 {c['log']}）", detail
    if len(overlap) < 2:
        return False, "日志里可核对的玩家太少，无法确认是本赛季", detail
    return True, "", detail


def latest_stats_turn(text: Optional[str]) -> int:
    """``Player_Stats.csv`` 的最后一行的回合（首列比实际回合大 1），没有则 -1。"""
    if not text:
        return -1
    last = -1
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        first = line.split(",")[0]
        if first.startswith("Game"):
            continue
        n = _to_int(first, default=-1)
        if n > 0:
            last = max(last, n)
    return last - 1 if last > 0 else -1


# --------------------------------------------------------------- 指标
def expand_payments(deals: Sequence[Dict[str, int]]) -> List[Dict[str, int]]:
    """把交易展开成"每一期付款"。

    ``duration = 0`` 是一次性付款；``duration = D`` 是第 ``T … T+D-1`` 回合每回合
    一笔（与原程序的时钟推进一致）。
    """
    out: List[Dict[str, int]] = []
    for d in deals:
        amount, src, dst = d.get("amount", 0), d.get("from", -1), d.get("to", -1)
        if not amount or amount < 0 or src < 0 or dst < 0:
            continue
        duration = d.get("duration", 0)
        turn = d.get("turn", 1)
        if duration and duration > 0:
            for t in range(turn, turn + duration):
                out.append({"turn": t, "from": src, "to": dst, "amount": amount})
        else:
            out.append({"turn": turn, "from": src, "to": dst, "amount": amount})
    return out


def compute_metrics(payments: Sequence[Dict[str, int]], start: int, end: int,
                    weighted: bool = False,
                    players: Optional[Sequence[int]] = None):
    """返回 ``(每个玩家的三个指标, 逐对手流向)``。

    * 打钱总数 = 该玩家作付款方在窗口内的金额合计
    * 吸钱总数 = 该玩家作收款方在窗口内的金额合计
    * 净金币交易 = 打钱 - 吸钱

    ``weighted`` 打开时每一期按 ``INTEREST_AMOUNT ** (end - 该期回合)`` 折算到
    窗口末回合 ``end``。
    """
    per: Dict[int, Dict[str, float]] = {}
    pairs: Dict[tuple, Dict[str, float]] = {}

    def ensure(slot: int) -> Dict[str, float]:
        if slot not in per:
            per[slot] = {"slot": slot, "sent": 0.0, "received": 0.0}
        return per[slot]

    allowed = set(players) if players else None
    if allowed:
        for slot in allowed:
            ensure(slot)
    for p in payments:
        if p["turn"] < start or p["turn"] > end:
            continue
        if allowed is not None and (p["from"] not in allowed or p["to"] not in allowed):
            continue
        value = float(p["amount"])
        if weighted:
            value *= INTEREST_AMOUNT ** (end - p["turn"])
        ensure(p["from"])["sent"] += value
        ensure(p["to"])["received"] += value
        key = (p["from"], p["to"])
        row = pairs.setdefault(key, {"from": p["from"], "to": p["to"],
                                     "amount": 0.0, "periods": 0})
        row["amount"] += value
        row["periods"] += 1
    return per, pairs


def build_report(save_dir: Optional[str] = None, log_dir: Optional[str] = None,
                 range_key: str = DEFAULT_RANGE, weighted: bool = False,
                 end_turn: Optional[int] = None, legacy: bool = False,
                 save_players: Optional[Dict[int, str]] = None,
                 seed: Optional[int] = None, now: Optional[float] = None) -> Dict:
    """给前端的完整报告（``/api/gold`` 直接返回它）。

    ``save_players`` = ``{槽位: 文明串}``（取自正在复盘的那份存档）、``seed`` = 本局种子，
    两者用来核对"这批日志是不是本局、是不是刚写的"；``now`` 只给测试注入时间用。

    **只有核对通过才 ``ok=True``**；否则 ``ok=False`` + 一句 ``reason``，前端会把整块
    金币流水隐藏掉，只留一行提示 —— 宁可少显示，也不显示过期 / 张冠李戴的账。
    """
    now = time.time() if now is None else float(now)
    range_key = str(range_key) if str(range_key) in RANGE_TURNS else DEFAULT_RANGE
    turns = RANGE_TURNS[range_key]

    directory, tried = resolve_log_dir(save_dir, log_dir)
    report: Dict = {
        "ok": False,
        "verified": False,
        "logDir": str(directory) if directory else None,
        "tried": [str(d) for d in tried],
        "range": range_key,
        "weighted": bool(weighted),
        "legacy": bool(legacy),
        "files": {"deals": False, "gamecore": False, "stats": False},
        "verify": {},
        "reason": "",
    }
    if directory is None:
        report["reason"] = "没有默认日志目录"
        return report

    deals_text = read_text(directory / DEALS_LOG)
    core_text = read_text(directory / GAMECORE_LOG)
    stats_text = read_text(directory / STATS_CSV)
    report["files"] = {"deals": deals_text is not None,
                       "gamecore": core_text is not None,
                       "stats": stats_text is not None}
    ages = file_ages_hours(directory, (DEALS_LOG, GAMECORE_LOG, STATS_CSV), now)
    if deals_text is None:
        report["reason"] = "没有日志"
        return report

    core_players = parse_game_core(core_text)
    ok, reason, detail = verify_log(
        save_players, {s: v["civ"] for s, v in core_players.items()}, ages,
        seed=seed, log_seed_value=log_seed(core_text), fresh_limit=fresh_hours())
    report["verify"] = detail
    if not ok:
        report["reason"] = reason
        return report

    humans = {s: v for s, v in core_players.items() if v["human"]}
    deals = parse_deals(deals_text, legacy)
    payments = expand_payments(deals)

    latest_deal_turn = max((d.get("turn", 1) for d in deals), default=0)
    log_turn = max(latest_deal_turn, latest_stats_turn(stats_text), 1)
    end = log_turn if not end_turn or end_turn < 1 else int(end_turn)
    clamped = end > log_turn
    if clamped:
        end = log_turn
    start = 1 if turns is None else max(1, end - turns + 1)

    players: Optional[List[int]] = sorted(humans) if humans else None
    per, pairs = compute_metrics(payments, start, end, weighted, players)
    rows = []
    for slot, m in per.items():
        rows.append({"slot": slot,
                     "sent": round(m["sent"], 2),
                     "received": round(m["received"], 2),
                     "net": round(m["sent"] - m["received"], 2)})
    rows.sort(key=lambda r: (r["net"], r["slot"]))

    report.update({
        "ok": True,
        "verified": True,
        "reason": "",
        "logTurn": log_turn,
        "endTurn": end,
        "startTurn": start,
        "endClamped": clamped,
        "deals": len(deals),
        "payments": len(payments),
        "humans": [{"slot": s, "civ": h["civ"], "name": h["name"]}
                   for s, h in sorted(humans.items())],
        "players": rows,
        "pairs": [dict(v) for v in pairs.values()],
    })
    return report
