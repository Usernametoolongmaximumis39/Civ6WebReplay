"""FastAPI service exposing parsed replays on localhost."""
from __future__ import annotations

import gzip
import json
import logging
import multiprocessing
import os
import re
import ssl
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, wait, FIRST_COMPLETED
from concurrent.futures.process import BrokenProcessPool
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from . import share as share_mod
from .cache import ReplayCache, SCHEMA_VERSION
from .loading import load_workers, parse_turn, favor_snapshot
from .tileyields import rules_token, get_rules
from .adjacency import district_hit_points
from .gamedb import get_gamedb
from .governors import get_governors
from .hash import (CIV_TYPE_NAMES, TYPE_CIV_CITY_STATE, TYPE_CIV_FREE_CITIES,
                   TYPE_CIV_FULL, TYPE_CIV_TRIBE, YIELD_COLORS, YIELD_NAMES,
                   YIELD_ORDER, crc32_type)
from .identities import get_identities
from .rule_text import get_rule_text, rule_text_token
from .goldledger import build_report as build_gold_report
from .loc import get_loc
from .localization import (ui, localize_replays, localize_static,
                           localize_turn, localize_share, display_token)
from .mods import wall_defense_override
from .mod_identity import balance_profile
from .database_versions import version_info
from .production import rules_for as production_rules
from .replay import (SaveInfo, default_save_dir, discover, group_by_seed,
                     latest_save_for_seed)
from .state import (header_verdict, parse_save, turn_payload, encode_payload,
                    decode_payload)

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
ICONS_DIR = ROOT / "assets" / "icons"


def production_costs(profile: str) -> dict:
    return {h: row["cost"] for h, row in production_rules(profile).get("items", {}).items()
            if row.get("cost", 0) > 0 and row.get("model") in (
                "NO_COST_PROGRESSION", "NO_PROGRESSION_MODEL")}


MAPWRAP_JSON = ROOT / "data" / "vanilla" / "mapwrap.json"

# route index (``tiles.road``) -> ``LOC_ROUTE_*_NAME`` tag.  The index is the
# game's own *zero-based* position in the ``Routes`` table (ancient, medieval,
# industrial, modern, railroad); 255 (0xFF) means "no route".  A fresh city
# centre already carries route 0, so 0 must never be read as "no road".
# Verified against Single/quicksave.Civ6Save (turn 8) and AutoSave_0091
# (turn 90): values 0..4 all occur, roads upgrade in place 0 -> 1 -> 2 -> 3,
# and 4 (ROUTE_RAILROAD, Gathering Storm only) is never an upgrade product.
ROUTE_TAGS = {
    0: "LOC_ROUTE_ANCIENT_ROAD_NAME",
    1: "LOC_ROUTE_MEDIEVAL_ROAD_NAME",
    2: "LOC_ROUTE_INDUSTRIAL_ROAD_NAME",
    3: "LOC_ROUTE_MODERN_ROAD_NAME",
    4: "LOC_ROUTE_RAILROAD_NAME",
}
ROUTE_NAMES_FALLBACK = {0: "远古时代道路", 1: "古典时代道路", 2: "工业时代道路",
                        3: "现代道路", 4: "铁路"}

# steam profile XML is a third-party page; never block a request for long
STEAM_TIMEOUT = 5.0


def _steam_ssl_context() -> ssl.SSLContext:
    """TLS context for the Steam lookup, trusting the *platform* certificate store.

    httpx verifies against certifi's bundle by default.  Corporate proxies / AV
    products that terminate TLS install their root CA into the Windows store
    only, so certifi-only verification fails with ``CERTIFICATE_VERIFY_FAILED``
    and every lookup would answer 502 ("查询失败" in the UI).  ``create_default_context``
    keeps the normal hostname + chain verification, it just also loads the OS
    store; falls back to the httpx default when no store is available.
    """
    try:
        ctx = ssl.create_default_context()
        ctx.load_default_certs()          # Windows ROOT store / OpenSSL system paths
        return ctx
    except Exception:                      # pragma: no cover - exotic platforms
        return ssl.create_default_context()

# Background loader cadence (seconds) between full re-scans.
LOADER_INTERVAL = 30
logger = logging.getLogger(__name__)


def _load_mapwrap() -> Dict[str, bool]:
    """``map_key -> wrapX`` snapshot (``{}`` when the tool has not been run)."""
    if not MAPWRAP_JSON.exists():
        return {}
    try:
        doc = json.loads(MAPWRAP_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: Dict[str, bool] = {}
    for k, v in (doc.get("maps") or {}).items():
        out[str(k)] = bool(v)
    return out


def _save_map_english(save: SaveInfo) -> str:
    """Read only the header when an older metadata cache lacks English names."""
    if not save.map_name_en:
        from .container import parse_all
        from .header import game_info
        try:
            save.map_name_en = game_info(parse_all(Path(save.path).read_bytes()))["map_name_en"]
        except Exception:
            save.map_name_en = save.map_name
    return save.map_name_en

# playersInfo.typeCiv -> public player kind
_CIV_KIND = {
    TYPE_CIV_FULL: "major",
    TYPE_CIV_CITY_STATE: "city_state",
    TYPE_CIV_FREE_CITIES: "free_cities",
    TYPE_CIV_TRIBE: "barbarian",
}


def _name_of(h, profile: str = "", lang: str = "zh") -> str:
    """Profile policy text -> identities -> gamedb (empty when unknown)."""
    if not h:
        return ""
    hm = int(h) & 0xFFFFFFFF
    text = get_rule_text(profile).entry(hm, lang)
    if text and (text["kind"] == "policy" or lang == "en") and text["name"]:
        # Keep the user's chosen wording for Autocratic Legacy.
        if text["type"] == "POLICY_GOV_AUTOCRACY" and lang == "zh":
            return "独裁传承"
        return text["name"]
    name = get_identities().name(hm, profile, lang)
    if name:
        return name
    typ = get_gamedb().type_str(hm)
    if typ.startswith("GREAT_PERSON_INDIVIDUAL_"):
        from .greatpeople import individual_name
        name = individual_name(typ, profile, lang)
        if name:
            return name
    name = get_gamedb().name(hm, lang)
    return "" if name.startswith("0x") else name


def _resolve(h, profile: str = "", lang: str = "zh") -> dict:
    """Resolve profile-aware names, icons and separately captured descriptions."""
    hm = int(h) & 0xFFFFFFFF
    ident = get_identities()
    db = get_gamedb()
    text = get_rule_text(profile).entry(hm, lang)
    return {
        "name": _name_of(hm, profile, lang) or f"0x{hm:08X}",
        "type": ident.type_str(hm) or db.type_str(hm),
        "category": db.category(hm) or (ident.kind(hm) or None),
        "icon": ident.icon(hm, profile) or db.icon(hm),
        "description": text["description"] if text else "",
    }


def _religion_fallbacks(state, profile: str) -> dict:
    """Allocate replay-local display aliases from the final founded-religion catalog.

    The save retains founded religions even after their last city is converted.
    Use that catalog, rather than the viewed turn, to reserve late-game icons.
    Never replace gameplay hashes: beliefs and yield rules still use the originals.
    """
    used = {_u(r.iSymbol) for r in state.religions}
    used.update(_u(c.religion) for p in state.players for c in p.cities)
    used.discard(0xFFFFFFFF)
    resolved = {h: _resolve(h, profile) for h in used}
    unknown = sorted(h for h, row in resolved.items()
                     if row["type"].startswith("0x"))
    occupied = {row["icon"] for row in resolved.values() if row["icon"]}
    icons = []
    for row in sorted(get_identities().entries.values(), key=lambda row: row["type"]):
        icon = get_identities().icon(row["hash"], profile)
        if (row.get("kind") == "religion" and row["hash"] not in used
                and icon and icon not in occupied):
            icons.append(icon)
            occupied.add(icon)  # Different TYPEs can share the same icon.
    return {str(h): {"number": i + 1,
                     "icon": icons[i] if i < len(icons) else "yield/Faith.png"}
            for i, h in enumerate(unknown)}


def _steam_id(pseudo_with_id: str) -> Optional[str]:
    """``nickname@7656119…`` -> the numeric SteamID (``None`` for AI players)."""
    if not pseudo_with_id or "@" not in pseudo_with_id:
        return None
    tail = pseudo_with_id.rsplit("@", 1)[1].strip()
    return tail if tail.isdigit() else None


def _route_names() -> Dict[int, str]:
    """``{0..4: 道路名}`` from the localization snapshot (zh first).

    255 is deliberately absent: the frontend renders it as "无".
    """
    loc = get_loc()
    out: Dict[int, str] = {}
    for index, tag in ROUTE_TAGS.items():
        out[index] = loc.name(tag) or ROUTE_NAMES_FALLBACK[index]
    return out


def _luxury_resources(profile: str = "vanilla") -> List[int]:
    """Hashes of every ``RESOURCECLASS_LUXURY`` resource (continent badges)."""
    rules = get_rules(profile)
    if rules is not None:
        return sorted(_u(crc32_type(r["ResourceType"])) for r in rules.tables["Resources"]
                      if r["ResourceClassType"] == "RESOURCECLASS_LUXURY")
    return get_gamedb().luxury_resources()


def _strategic_resources(profile: str = "vanilla") -> List[int]:
    order = ["RESOURCE_" + name for name in
             ("HORSES", "IRON", "NITER", "COAL", "OIL", "ALUMINUM", "URANIUM")]
    rules = get_rules(profile)
    types = ([r["ResourceType"] for r in rules.tables["Resources"]
              if r["ResourceClassType"] == "RESOURCECLASS_STRATEGIC"]
             if rules is not None else order)
    types.sort(key=lambda typ: (order.index(typ) if typ in order else len(order), typ))
    return [_u(crc32_type(typ)) for typ in types]


def _governor_promotions(mods) -> dict:
    """总督晋升词条表（按该存档实际启用的规则集选表）。

    名称随平衡 MOD 变化（CCB 的「外汇资金」= BBG 的「国际贸易」），所以整张表
    随 static info 一起下发，前端只在城市面板里查它，不并进全局 ``names``
    （``names`` 在多次回放之间共享，混进 MOD 专属译名会串味）。
    """
    gp = get_governors()
    table = gp.table(mods)
    key = gp.key_for(mods)
    return {
        "key": key,
        "label": table.get("label", ""),
        "verified": table.get("verified"),
        "available": bool(table.get("names")),
        "names": {str(h): v for h, v in table.get("names", {}).items()},
        "order": {str(g): [str(h) for h in hs]
                  for g, hs in table.get("order", {}).items()},
    }


# ``<steamID><![CDATA[Alice]]></steamID>`` (the CDATA wrapper is optional)
_STEAM_ID_RE = re.compile(
    r"<steamID>\s*(?:<!\[CDATA\[(?P<cdata>.*?)\]\]>|(?P<plain>[^<]*))\s*</steamID>",
    re.DOTALL)


def fetch_steam_name(steamid: str, *, timeout: float = STEAM_TIMEOUT) -> str:
    """Resolve a SteamID64 to its community name via ``steamcommunity.com``.

    Raises on any failure (network, non-200, private profile without a
    ``<steamID>``) so the endpoint can answer 502 and the front end can fall
    back to "查询失败".  Kept module level so tests can monkeypatch it.
    """
    url = f"https://steamcommunity.com/profiles/{steamid}?xml=1"
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      verify=_steam_ssl_context(),
                     headers={"User-Agent": "civ6replay/0.44"}) as client:
        resp = client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    m = _STEAM_ID_RE.search(resp.text)
    if not m:
        raise RuntimeError("no <steamID> in profile XML")
    name = (m.group("cdata") or m.group("plain") or "").strip()
    if not name:
        raise RuntimeError("empty <steamID>")
    return name


def _drives() -> List[dict]:
    """Local drive roots (the browse tree always starts here)."""
    out: List[dict] = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        if root.exists():
            out.append({"name": f"{letter}:\\", "path": str(root),
                        "hasSaves": False})
    return out


def _has_saves(path: Path) -> bool:
    try:
        return next(path.glob("*.Civ6Save"), None) is not None
    except OSError:  # pragma: no cover - unreadable directory
        return False


def browse_dir(path: Optional[str]) -> dict:
    """One level of the directory tree (``/api/browse``).

    ``path`` empty lists the local drive roots; otherwise its sub-directories
    are listed, each flagged when it directly contains ``.Civ6Save`` files.
    """
    if not path:
        return {"path": "", "parent": None, "dirs": _drives()}
    base = Path(path)
    if not base.is_dir():
        raise HTTPException(400, f"目录不存在：{path}")
    dirs: List[dict] = []
    try:
        entries = sorted((p for p in base.iterdir() if p.is_dir()),
                         key=lambda p: p.name.lower())
    except OSError as exc:
        raise HTTPException(400, f"无法读取目录：{exc}")
    parent = None if base.parent == base else str(base.parent)
    for child in entries:
        if child.name.startswith("."):
            continue
        dirs.append({"name": child.name, "path": str(child),
                     "hasSaves": _has_saves(child)})
    return {"path": str(base), "parent": parent, "dirs": dirs}


# --- v0.27: native folder picker (Explorer-style) ---------------------------
# Windows has no browser-side directory dialog that also yields a *path*, so the
# server hosts a hidden PowerShell (STA) process.  v0.26 used the .NET Framework
# ``FolderBrowserDialog``: that is the *legacy* shell tree dialog (no address
# bar, no quick access) and - because the host process owns no window of its own
# - it came up *behind* the browser window, so 「浏览…」 looked broken.
#
# v0.27 drives the Vista+ ``IFileDialog`` (COM ``FileOpenDialog`` with
# ``FOS_PICKFOLDERS``) - the same dialog Explorer's 「另存为」 uses - owned by an
# invisible *top-most* window, which keeps it in front of the browser.  The
# legacy dialog stays as a fallback when the COM host cannot be built.
#
# The chosen path is written to a UTF-8 temp file (the console encoding would
# mangle 中文 paths); an empty file means the user cancelled.  The title and the
# initial folder travel as environment variables so the inline script itself
# stays pure ASCII.
PICK_FOLDER_CS = r"""
using System;
using System.IO;
using System.Runtime.InteropServices;

[ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
internal class FileOpenDialogRCW { }

[ComImport, Guid("42F85136-DB7E-439C-85F1-E4075D135FC8"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IFileDialog
{
    [PreserveSig] int Show(IntPtr parent);
    void SetFileTypes(uint cFileTypes, IntPtr rgFilterSpec);
    void SetFileTypeIndex(uint iFileType);
    void GetFileTypeIndex(out uint piFileType);
    void Advise(IntPtr pfde, out uint pdwCookie);
    void Unadvise(uint dwCookie);
    void SetOptions(uint fos);
    void GetOptions(out uint pfos);
    void SetDefaultFolder([MarshalAs(UnmanagedType.Interface)] IShellItem psi);
    void SetFolder([MarshalAs(UnmanagedType.Interface)] IShellItem psi);
    void GetFolder(out IntPtr ppsi);
    void GetCurrentSelection(out IntPtr ppsi);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
    void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string pszName);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string pszText);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string pszLabel);
    void GetResult(out IntPtr ppsi);
    void AddPlace(IntPtr psi, int fdap);
    void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string pszDefaultExtension);
    void Close(int hr);
    void SetClientGuid(ref Guid guid);
    void ClearClientData();
    void SetFilter(IntPtr pFilter);
}

[ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IShellItem
{
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetParent(out IShellItem ppsi);
    void GetDisplayName(uint sigdnName, out IntPtr ppszName);
    void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
    void Compare(IShellItem psi, uint hint, out int piOrder);
}

public static class Civ6FolderPicker
{
    private const uint FOS_PICKFOLDERS = 0x00000020;
    private const uint FOS_FORCEFILESYSTEM = 0x00000040;
    private const uint FOS_PATHMUSTEXIST = 0x00000800;
    private const uint SIGDN_FILESYSPATH = 0x80058000;

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern int SHCreateItemFromParsingName(
        [MarshalAs(UnmanagedType.LPWStr)] string pszPath, IntPtr pbc,
        ref Guid riid, [MarshalAs(UnmanagedType.Interface)] out IShellItem ppv);

    // A PowerShell process started by the web server is not necessarily allowed
    // to steal the foreground from the browser.  Merely setting Form.TopMost
    // therefore is not enough: Windows may still leave the picker behind the
    // browser.  Temporarily attaching the picker thread to the current
    // foreground thread makes this activation request legal.
    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr processId);
    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")]
    private static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool attach);
    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    private static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter,
                                             int x, int y, int cx, int cy, uint flags);

    private static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
    private const uint SWP_NOSIZE = 0x0001;
    private const uint SWP_NOMOVE = 0x0002;
    private const uint SWP_SHOWWINDOW = 0x0040;

    public static void ActivateOwner(IntPtr owner)
    {
        IntPtr foreground = GetForegroundWindow();
        uint foregroundThread = foreground == IntPtr.Zero ? 0 :
            GetWindowThreadProcessId(foreground, IntPtr.Zero);
        uint currentThread = GetCurrentThreadId();
        bool attached = foregroundThread != 0 && foregroundThread != currentThread &&
                        AttachThreadInput(currentThread, foregroundThread, true);
        try
        {
            SetWindowPos(owner, HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
            BringWindowToTop(owner);
            SetForegroundWindow(owner);
        }
        finally
        {
            if (attached) AttachThreadInput(currentThread, foregroundThread, false);
        }
    }

    public static string Folder(string title, string initial, IntPtr owner)
    {
        IFileDialog dlg = (IFileDialog)(new FileOpenDialogRCW());
        try
        {
            uint options;
            dlg.GetOptions(out options);
            dlg.SetOptions(options | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM
                                   | FOS_PATHMUSTEXIST);
            if (title != null && title.Length > 0) dlg.SetTitle(title);
            if (initial != null && initial.Length > 0 && Directory.Exists(initial))
            {
                Guid iid = new Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE");
                IShellItem where;
                if (SHCreateItemFromParsingName(initial, IntPtr.Zero, ref iid,
                                                out where) == 0 && where != null)
                {
                    dlg.SetFolder(where);
                    Marshal.ReleaseComObject(where);
                }
            }
            int hr = dlg.Show(owner);          // 0x800704C7 = user cancelled
            if (hr != 0) return null;
            IntPtr item;
            dlg.GetResult(out item);
            if (item == IntPtr.Zero) return null;
            IShellItem result = (IShellItem)Marshal.GetObjectForIUnknown(item);
            Marshal.Release(item);
            try
            {
                IntPtr name;
                result.GetDisplayName(SIGDN_FILESYSPATH, out name);
                string path = Marshal.PtrToStringUni(name);
                Marshal.FreeCoTaskMem(name);
                return path;
            }
            finally { Marshal.ReleaseComObject(result); }
        }
        finally { Marshal.ReleaseComObject(dlg); }
    }
}
"""

PICK_FOLDER_PS = (
    "$ErrorActionPreference = 'Stop';"
    "Add-Type -AssemblyName System.Windows.Forms | Out-Null;"
    "Add-Type -AssemblyName System.Drawing | Out-Null;"
    "Add-Type -TypeDefinition @'\n" + PICK_FOLDER_CS + "'@ | Out-Null;"
    # an invisible *top-most* owner: whatever the dialog does, it stays in front
    "$owner = New-Object System.Windows.Forms.Form;"
    "$owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None;"
    "$owner.ShowInTaskbar = $false;"
    "$owner.TopMost = $true;"
    "$owner.Opacity = 0.01;"
    # ``IFileDialog`` puts its top-left corner on the owner's centre, so the 1x1
    # owner is parked half a default dialog (1200x900) above-left of the middle
    # of the primary work area: the picker then comes up centred.
    "$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual;"
    "$wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea;"
    "$owner.Location = New-Object System.Drawing.Point "
    "([int]($wa.X + $wa.Width / 2 - 600), [int]($wa.Y + $wa.Height / 2 - 450));"
    "$owner.Size = New-Object System.Drawing.Size 1, 1;"
    "$owner.Show();"
    "[System.Windows.Forms.Application]::DoEvents();"
    # Activate the owner immediately before showing IFileDialog.  Without this
    # Windows may reject the foreground change because PowerShell was launched
    # by the background web server, leaving Explorer behind the browser.
    "[Civ6FolderPicker]::ActivateOwner($owner.Handle);"
    "$title = $env:CIV6REPLAY_PICK_TITLE;"
    "$initial = $env:CIV6REPLAY_PICK_INITIAL;"
    "$text = '';"
    "$handled = $false;"
    "try { $text = [Civ6FolderPicker]::Folder($title, $initial, $owner.Handle);"
    "      $handled = $true } catch { $handled = $false };"
    "if (-not $handled) {"
    "  try {"
    "    $d = New-Object System.Windows.Forms.FolderBrowserDialog;"
    "    if ($title) { $d.Description = $title };"
    "    $d.ShowNewFolderButton = $false;"
    "    if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK)"
    "    { $text = $d.SelectedPath }"
    "  } catch { $text = '' }"
    "};"
    "$owner.Close();"
    "if (-not $text) { $text = '' };"
    "[System.IO.File]::WriteAllText($env:CIV6REPLAY_PICK_OUT, $text, "
    "(New-Object System.Text.UTF8Encoding $false));"
)

# the dialog caption / the tree-dialog description (v0.27)
PICK_FOLDER_TITLE = "选择文明6存档目录"


def pick_folder(initial: Optional[str] = None, timeout: float = 300.0,
                title: str = PICK_FOLDER_TITLE) -> Optional[str]:
    """Ask the OS for a directory; ``None`` when the user cancels.

    Only implemented on Windows (``NotImplementedError`` elsewhere) so the API
    can answer 501 and the UI keeps its manual path box.  ``initial`` is the
    folder the dialog opens in (the scanned save directory).
    """
    if os.name != "nt":
        raise NotImplementedError("folder picker is Windows-only")
    fd, out_path = tempfile.mkstemp(prefix="civ6replay-pick-", suffix=".txt")
    os.close(fd)
    env = dict(os.environ, CIV6REPLAY_PICK_OUT=out_path,
               CIV6REPLAY_PICK_TITLE=title,
               CIV6REPLAY_PICK_INITIAL=str(initial or ""))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", PICK_FOLDER_PS],
            env=env, timeout=timeout, creationflags=creationflags,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False,
        )
        text = Path(out_path).read_text(encoding="utf-8", errors="replace").strip()
        if not text and done.returncode:
            err = (done.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"目录选择框启动失败（exit {done.returncode}）"
                               + (f"：{err.splitlines()[-1]}" if err else ""))
    finally:
        try:
            os.unlink(out_path)
        except OSError:  # pragma: no cover - best effort cleanup
            pass
    return text or None


class ReplayManager:
    def __init__(self, save_dir: Optional[str] = None,
                 cache: Optional[ReplayCache] = None, *, workers: int | None = None):
        self.workers = load_workers(workers)
        self.save_dir = save_dir
        self.cache = cache or ReplayCache()
        self.infos: List[SaveInfo] = []
        self.groups: dict = {}
        self._static: OrderedDict = OrderedDict()
        self._mapwrap = _load_mapwrap()
        self._loaders: Dict[int, threading.Thread] = {}
        self._loader_stops: Dict[int, threading.Event] = {}
        self._lock = threading.Lock()
        self._scan_lock = threading.RLock()
        self._parse_locks: dict = {}
        self._closed = threading.Event()
        self._pool_lock = threading.Lock()
        self._work_pool = None
        self._process_pool = None
        # v0.39: 「不支持」判定按存档文件缓存（``(path, mtime, size)`` -> verdict）
        self._verdicts: Dict[tuple, Optional[dict]] = {}
        self._verdict_lock = threading.Lock()
        # Browser uploads are session copies kept beside the selected cache.
        # Keep old copies alive while cancelled loader threads finish reading.
        self._imports: list[tempfile.TemporaryDirectory] = []
        self.refresh()

    @property
    def effective_save_dir(self) -> str:
        """The file or directory being read (session setting or the default)."""
        return str(self.save_dir or default_save_dir())

    def set_save_dir(self, path: str) -> None:
        """Switch the scanned directory for this session (v0.25).

        Only in-memory: a restart of the process goes back to the default
        ``Documents\\My Games\\Sid Meier's Civilization VI\\Saves\\Multi\\auto``.
        """
        target = Path(path)
        if not target.exists():
            raise ValueError(f"路径不存在：{path}")
        if not target.is_dir() and not (target.is_file() and target.suffix.lower() == ".civ6save"):
            raise ValueError("请选择 .Civ6Save 文件或存档文件夹。")
        with self._scan_lock:
            with self._lock:
                for stop in self._loader_stops.values():
                    stop.set()
                self.save_dir = str(target.resolve())
            self.refresh()

    def import_saves(self, uploads: list[UploadFile], kind: str) -> dict:
        """Copy browser-selected saves into an isolated session workspace."""
        saves = [upload for upload in uploads
                 if Path(upload.filename or "").suffix.lower() == ".civ6save"]
        if not saves:
            raise ValueError("未找到 .Civ6Save 存档。")
        if kind == "file" and len(saves) != 1:
            raise ValueError("请选择一个 .Civ6Save 文件。")
        workspace = tempfile.TemporaryDirectory(prefix="import-", dir=self.cache.path.parent)
        root = Path(workspace.name)
        try:
            for index, upload in enumerate(saves):
                # Never trust multipart filenames as paths; nested directories
                # and duplicate basenames receive distinct local filenames.
                target = root / f"{index:06d}.Civ6Save"
                with target.open("wb") as output:
                    while chunk := upload.file.read(1024 * 1024):
                        output.write(chunk)
            self.set_save_dir(str(target if kind == "file" else root))
        except BaseException:
            workspace.cleanup()
            raise
        self._imports.append(workspace)
        return self.source_result()

    def source_result(self) -> dict:
        single = Path(self.effective_save_dir).is_file()
        info = self.infos[0] if single and self.infos else None
        return {"ok": True, "current": self.effective_save_dir,
                "saves": len(self.infos), "kind": "file" if single else "directory",
                "selection": {"seed": info.seed, "turn": info.turn} if info else None}

    def refresh(self, stop: Optional[threading.Event] = None) -> None:
        # A scan started by an old loader must never publish the previous folder
        # after a directory switch, or restart its cancelled loader.
        with self._scan_lock:
            if self._closed.is_set() or (stop is not None and stop.is_set()):
                return
            infos = discover(self.save_dir, self.cache, workers=self.workers)
            groups = group_by_seed(infos)
            with self._lock:
                self.infos, self.groups = infos, groups
                for seed, event in self._loader_stops.items():
                    if seed not in groups:
                        event.set()
            for seed in groups:
                if seed:
                    self.ensure_loader(seed)

    # --- map wrap metadata -------------------------------------------------
    def wrap_x(self, map_key: str) -> bool:
        """WrapX for a save-header ``map_key`` (unknown keys default True)."""
        if map_key in self._mapwrap:
            return self._mapwrap[map_key]
        return True

    # --- background parallel loader ---------------------------------------
    def close(self) -> None:
        """Stop scheduling, drain active parses, then release imported files."""
        with self._scan_lock:
            with self._lock:
                self._closed.set()
                for stop in self._loader_stops.values():
                    stop.set()
                threads = list(self._loaders.values())
        for thread in threads:
            thread.join()
        with self._pool_lock:
            work_pool, self._work_pool = self._work_pool, None
        if work_pool is not None:
            work_pool.shutdown(wait=True, cancel_futures=True)
        with self._pool_lock:
            process_pool, self._process_pool = self._process_pool, None
        if process_pool is not None:
            process_pool.shutdown(wait=True, cancel_futures=True)
        for workspace in self._imports:
            workspace.cleanup()
        self._imports.clear()

    def _background_payload(self, save: SaveInfo) -> tuple[bytes, str]:
        with self._pool_lock:
            if self._process_pool is None:
                self._process_pool = ProcessPoolExecutor(
                    max_workers=self.workers, mp_context=multiprocessing.get_context("spawn"))
            pool = self._process_pool
        try:
            return pool.submit(parse_turn, save.path, self._mapwrap).result()
        except BrokenProcessPool:
            # Retire a failed pool; the next scan can retry missing turns.
            with self._pool_lock:
                if self._process_pool is pool:
                    self._process_pool = None
                    pool.shutdown(wait=False, cancel_futures=True)
            raise

    def unsupported(self, seed: int) -> Optional[dict]:
        """该 seed 最新存档的「不支持」判定（``None`` = 可以正常复盘）。

        v0.39：黑名单 MOD / 结社 / 垄断玩法命中时，整条 seed 不做任何解析 ——
        后台 loader 不再把回合写进缓存，前端拿到 ``unsupported`` 后直接画叉。
        判定只看头部（不解压游玩数据），并按存档文件缓存，30 秒一次的
        ``refresh`` 不会反复去扫。
        """
        save = self.latest(seed)
        if save is None:
            return None
        key = (save.path, save.mtime, save.size)
        with self._verdict_lock:
            if key in self._verdicts:
                return self._verdicts[key]
        verdict = None
        try:
            verdict = header_verdict(Path(save.path).read_bytes())
        except Exception:            # pragma: no cover - 坏文件交给正常解析流程
            verdict = None
        with self._verdict_lock:
            self._verdicts[key] = verdict
        return verdict

    def advance(self, seed: int, stop: Optional[threading.Event] = None) -> None:
        """Load missing turns concurrently; publish each completed turn at once.

        Cached payloads are only decoded when their favour snapshot is missing.
        """
        if self._closed.is_set() or (stop is not None and stop.is_set()) or self.unsupported(seed):
            return
        tm = self.turn_map(seed)
        status = self.cache.turn_status(seed)
        missing = iter((t, tm[t]) for t in sorted(tm)
                       if status.get((t, tm[t].mtime, tm[t].size)) is not True)
        if self.workers == 1:
            for t, save in missing:
                if self._closed.is_set() or (stop is not None and stop.is_set()):
                    return
                try:
                    self._payload_for_save(seed, t, save, stop)
                except Exception:
                    logger.exception("Failed to load save %s", save.path)
            return
        # One shared budget across games and directory switches. Only one small
        # window per coordinator is queued, rather than every turn in the game.
        with self._pool_lock:
            if self._closed.is_set():
                return
            if self._work_pool is None:
                self._work_pool = ThreadPoolExecutor(
                    max_workers=self.workers, thread_name_prefix="civ6-load")
            pool = self._work_pool
        pending = {}
        try:
            while True:
                if self._closed.is_set() or (stop is not None and stop.is_set()):
                    return
                while len(pending) < self.workers:
                    item = next(missing, None)
                    if item is None:
                        break
                    t, save = item
                    future = pool.submit(self._payload_for_save, seed, t, save, stop, background=True)
                    pending[future] = save
                if not pending:
                    return
                done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    save = pending.pop(future)
                    try:
                        future.result()
                    except Exception:
                        logger.exception("Failed to load save %s", save.path)
        finally:
            for future in pending:
                future.cancel()

    def _payload_for_save(self, seed: int, turn: int, save: SaveInfo,
                          stop: Optional[threading.Event] = None, *, background=False) -> Optional[dict]:
        # Foreground requests and the loader can miss the same row together.
        # Recheck under a per-save lock before doing the expensive save parse;
        # a cold turn must not block requests for other, already-cached turns.
        with self._lock:
            key = (seed, turn, save.mtime, save.size)
            lock = self._parse_locks.setdefault(key, threading.Lock())
        with lock:
            if self._closed.is_set() or (stop is not None and stop.is_set()):
                return None
            cached = self.cache.get_turn(seed, turn, save.mtime, save.size)
            encoded = None
            if cached is not None:
                payload = decode_payload(cached)
                favor = favor_snapshot(payload)
            elif background:
                encoded, favor = self._background_payload(save)
                payload = None
            else:
                state = self.load_state(save)
                if stop is not None and stop.is_set():
                    return None
                payload = turn_payload(state, wrap_x=self.wrap_x(state.map_key))
                if stop is not None and stop.is_set():
                    return None
                encoded, favor = encode_payload(payload), favor_snapshot(payload)
            # Serialize cancellation with publication, so a switched directory
            # cannot publish late results, including its favour snapshot.
            with self._lock:
                if self._closed.is_set() or (stop is not None and stop.is_set()):
                    return None
                if encoded is not None:
                    self.cache.put_turn(seed, turn, save.mtime, save.size, encoded)
                if self.cache.get_turn_stats(seed, turn, save.mtime, save.size) is None:
                    self.cache.put_turn_stats(seed, turn, favor, save.mtime, save.size)
            return payload

    def ensure_loader(self, seed: int) -> None:
        """Start the per-seed daemon loader thread if it is not running."""
        if not seed:
            return
        with self._lock:
            if self._closed.is_set() or seed not in self.groups:
                return
            th = self._loaders.get(seed)
            stop = self._loader_stops.get(seed)
            if th is not None and th.is_alive() and stop is not None and not stop.is_set():
                return
            stop = threading.Event()
            th = threading.Thread(target=self._loader_loop, args=(seed, stop),
                                  name=f"civ6-loader-{seed}", daemon=True)
            self._loaders[seed] = th
            self._loader_stops[seed] = stop
            th.start()

    def _loader_loop(self, seed: int, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                try:
                    self.advance(seed, stop)
                except Exception:  # pragma: no cover - defensive background loop
                    pass
                if stop.wait(LOADER_INTERVAL):
                    return
                try:
                    self.refresh(stop)
                except Exception:  # pragma: no cover
                    pass
        finally:
            with self._lock:
                if self._loader_stops.get(seed) is stop:
                    self._loaders.pop(seed, None)
                    self._loader_stops.pop(seed, None)

    def loadstate(self, seed: int) -> dict:
        """``{total, loaded:[bool…], loading}`` aligned with the turns list."""
        tm = self.turn_map(seed)
        turns = sorted(tm)
        # v0.39: 不支持的 seed 一个回合都不会解析；全部报「就绪」，
        # 免得前端一直显示「正在解析」。
        if self.unsupported(seed):
            return {"total": len(turns), "loaded": [True] * len(turns),
                    "loading": False}
        loaded: List[bool] = []
        status = self.cache.turn_status(seed)
        for t in turns:
            save = tm[t]
            loaded.append((t, save.mtime, save.size) in status)
        loading = any(not x for x in loaded)
        return {"total": len(turns), "loaded": loaded, "loading": loading}

    def turnstats(self, seed: int, turn: int) -> dict:
        """Per-player diplomatic favour delta (turn vs the previous turn)."""
        tm = self.turn_map(seed)
        save, previous = tm.get(turn), tm.get(turn - 1)
        cur = self.cache.get_turn_stats(seed, turn, save.mtime, save.size) if save else None
        prev = (self.cache.get_turn_stats(seed, turn - 1, previous.mtime, previous.size)
                if previous else None)
        out: Dict[str, Optional[int]] = {}
        if cur is None:
            return out
        try:
            cur_map = json.loads(cur)
        except ValueError:
            return out
        prev_map = {}
        if prev is not None:
            try:
                prev_map = json.loads(prev)
            except ValueError:
                prev_map = {}
        for key, val in cur_map.items():
            if prev_map and key in prev_map:
                out[key] = int(val) - int(prev_map[key])
            else:
                out[key] = None
        return out

    def turn_map(self, seed: int) -> dict:
        return {i.turn: i for i in self.groups.get(seed, [])}

    def latest(self, seed: int) -> Optional[SaveInfo]:
        return latest_save_for_seed(self.infos, seed)

    def load_state(self, save: SaveInfo):
        raw = Path(save.path).read_bytes()
        return parse_save(raw)

    def load_payload(self, seed: int, turn: int) -> dict:
        tm = self.turn_map(seed)
        save = tm.get(turn)
        if save is None:
            raise KeyError(turn)
        if self.unsupported(seed):
            raise KeyError(turn)     # 不支持的存档没有回合数据可给
        return self._payload_for_save(seed, turn, save)

    def static_info(self, seed: int) -> dict:
        save = self.latest(seed)
        if save is None:
            raise KeyError(seed)
        self.ensure_loader(seed)
        key = (seed, save.path, save.mtime, save.size, SCHEMA_VERSION, rules_token(), rule_text_token())
        with self._lock:
            info = self._static.get(key)
            if info is not None:
                self._static.move_to_end(key)
                return {**info, "turns": sorted(self.turn_map(seed))}
        state = self.load_state(save)
        db = get_gamedb()
        profile = balance_profile(state.modPackages or state.mods, default=(state.balanceMod or "vanilla").lower())
        identities = [get_identities().entry(h, profile) for h in get_identities().entries]
        def identity_map(field):
            return {str(e["hash"]): e[field] for e in identities if field in e}
        players = []
        for info in state.playersInfo:
            if info.typePlayer not in (1, 3):
                continue
            players.append({
                "iPlayer": info.iPlayer,
                "civ": _u(info.civ),
                "leader": _u(info.leader),
                "civName": (_name_of(info.civ, profile) or info.locCivName or info.civStr),
                "leaderName": (_name_of(info.leader, profile) or info.leaderStr),
                "abilities": get_rule_text(profile).abilities(info.civ, info.leader),
                "civStr": info.civStr,
                "leaderStr": info.leaderStr,
                # v0.25: human players carry a nickname + SteamID
                "pseudo": info.pseudo,
                "steamId": _steam_id(info.pseudoWithSteamId),
                "typeCiv": _u(info.typeCiv),
                "typeCivName": CIV_TYPE_NAMES.get(_u(info.typeCiv), ""),
                "kind": _CIV_KIND.get(_u(info.typeCiv), "other"),
                "flavour": get_identities().flavour(_u(info.civ)),
                "team": info.team,
                "primary": list(info.primaryColor),
                "secondary": list(info.secondaryColor),
            })
        religions = [
            {"iPlayer": r.iPlayer, "symbol": _u(r.iSymbol),
             "name": r.name or "",
             "beliefs": [_u(x) for x in r.beliefs]}
            for r in state.religions
        ]
        info = {
            "seed": seed,
            # v0.28.1: the turn payload's shape version - the web client puts it in
            # the turn URL (``?v=``) so a schema bump can never reuse a cached body.
            "schema": SCHEMA_VERSION,
            "mapName": state.map_name,
            "mapNameEn": state.map_name_en,
            "mapKey": state.map_key,
            "mapSize": state.map_size,
            "gameSpeed": state.game_speed,
            "multiplayer": state.multiplayer,
            "width": state.width,
            "height": state.height,
            "turns": sorted(self.turn_map(seed).keys()),
            "players": players,
            # v0.25: founded religions (custom names), road display names and
            # the luxury-resource set used by the continent highlight
            "religions": religions,
            "religionFallbacks": _religion_fallbacks(state, profile),
            "routeNames": _route_names(),
            "luxuryResources": _luxury_resources(profile),
            "strategicResources": _strategic_resources(profile),
            # v0.26: wall caps + the 钢铁 urban-defence value, so every wall
            # readout (city panel / tile panel / both tooltips) shares one source.
            # v0.26.1: a balance MOD (BBG / CCB) in this save's mod list switches
            # the numbers to its ruleset (75 / 300) - one snapshot cannot hold both.
            "wallDefense": wall_defense_override(db.wall_defense(), state.mods),
            "districtHitPoints": district_hit_points("official" if profile == "vanilla" else profile),
            "mods": list(state.mods),
            "modPackages": list(state.modPackages),
            "balanceMod": profile.upper() if profile in ("bbg", "ccb") else "",
            "identityProfile": profile,
            "balanceVersions": version_info(profile,
                state.modPackages or [{"key": m, "name": m} for m in state.mods]),
            # v0.39: 启用的不支持玩法（``modes.parse_game_modes``）与「整局不支持」
            # 的判定 —— 命中时前端不画地图，只在画布中间画叉 + 提示。
            "gameModes": list(state.gameModes),
            "unsupported": state.unsupported,
            # v0.34: 总督晋升词条名（按该存档的规则集选表：原版 / BBG / CCB）。
            "governorPromotions": _governor_promotions(state.mods),
            "techTree": db.tree("technology"),
            "civicTree": db.tree("civic"),
            "layerErrors": [e.to_dict() for e in state.layerErrors],
            # debug only: the players-tail walker notes (never shown in the UI)
            "tailWarnings": list(state.tailWarnings),
            "wrapX": self.wrap_x(state.map_key),
            "buildingDistrict": {**{str(k): v for k, v in db.building_district_map().items()},
                                 **identity_map("buildingDistrict")},
            # v0.35: 建筑造价（``Buildings.Cost``）——前端在一格的几栋建筑里挑
            # 「最后那栋」（升级链末端）用，见 hexmap.js ``_pickBuilding``。
            "buildingCost": {**{str(k): v for k, v in db.building_cost_map().items()},
                             **identity_map("buildingCost")},
            "productionCost": production_costs(profile),
            "districtReplaces": {**{str(k): v for k, v in db.replaces_map().items()},
                                 **identity_map("replaces")},
            "yieldOrder": YIELD_ORDER,
            "yieldMeta": {str(h): {"name": YIELD_NAMES.get(h, "?"), "color": YIELD_COLORS.get(h, "#888")} for h in YIELD_ORDER},
        }
        with self._lock:
            self._static[key] = info
            self._static.move_to_end(key)
            if len(self._static) > 16:
                self._static.popitem(last=False)
        return info

    def replays(self) -> list:
        out = []
        for seed, group in self.groups.items():
            if seed == 0:
                continue
            latest = max(group, key=lambda s: (s.turn, s.mtime))
            # v0.39: 列表里就标出「不支持」，省得点进去才发现
            verdict = self.unsupported(seed)
            out.append({
                "seed": seed,
                "mapName": latest.map_name,
                "mapNameEn": _save_map_english(latest),
                "mapKey": latest.map_key,
                "mapSize": latest.map_size,
                "gameSpeed": latest.game_speed,
                "multiplayer": latest.multiplayer,
                "turnMin": group[0].turn,
                "turnMax": group[-1].turn,
                "saveCount": len(group),
                "status": "unsupported" if verdict else "ready",
                "unsupported": bool(verdict),
            })
        out.sort(key=lambda r: -r["turnMax"])
        return out


def _u(v) -> int:
    return int(v) & 0xFFFFFFFF


def create_app(save_dir: Optional[str] = None, *, host: str = "127.0.0.1",
               port: int = 8765, share_port: Optional[int] = None,
               share_bind: Optional[str] = None,
               share_reuse: Optional[bool] = None, workers: int | None = None) -> FastAPI:
    """``host``/``port`` 是主服务的绑定（共享时用来判断能不能直接复用主端口）。

    ``share_bind`` / ``share_port`` 供测试替换共享监听器的绑定与默认端口。
    """
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            app.state.share.stop()
            await run_in_threadpool(app.state.manager.close)

    app = FastAPI(title="Civ6 WebReplay", version="0.44", lifespan=lifespan)
    @app.exception_handler(HTTPException)
    async def localized_error(request: Request, exc: HTTPException):
        detail = exc.detail
        if request.query_params.get("lang") == "en" and isinstance(detail, str):
            # Preserve user-entered paths/hosts following a developer prefix.
            from .localization import catalogs
            strings = catalogs()[0]
            if detail in strings:
                detail = strings[detail]
            else:
                prefix = next((p for p in strings if p.endswith("：") and detail.startswith(p)), None)
                if prefix:
                    detail = strings[prefix] + detail[len(prefix):]
                else:
                    detail = ui(detail, "en")
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)
    manager = ReplayManager(save_dir, workers=workers)
    app.state.manager = manager
    # v0.38: 共享 —— 主进程本来就绑 0.0.0.0 时不再另起监听器，直接复用主端口。
    wildcard = str(host).strip() in ("0.0.0.0", "::", "*")
    if share_reuse is None:
        share_reuse = wildcard
    share = share_mod.ShareSession(
        app, bind_host=share_bind or "0.0.0.0",
        base_port=int(share_port or share_mod.SHARE_PORT_DEFAULT),
        reuse_port=int(port) if share_reuse else None)
    app.state.share = share

    @app.middleware("http")
    async def _no_cache_frontend(request: Request, call_next):
        """前端静态文件必须回源校验。

        v0.38：重启进程不会让浏览器丢掉 ``app.js`` / ``style.css`` 的磁盘缓存
        （``StaticFiles`` 只给了 ETag 与 Last-Modified，浏览器按启发式规则直接复用），
        于是页面可能停在「新 HTML + 旧 JS」——按钮画出来了，但没人给它绑事件，
        点「共享」毫无反应。这里给 html / js / css 明确 ``Cache-Control: no-cache``：
        每次回源校验，文件没变才会 304，代价是本地几毫秒。
        """
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith(".html") \
                or path.startswith(("/js/", "/css/")):
            response.headers["Cache-Control"] = "no-cache"
        return response
    db = get_gamedb()

    def _is_local(request: Request) -> bool:
        """请求是否来自本机（共享相关操作只允许本机发起）。"""
        client = getattr(request, "client", None)
        return bool(client) and str(client.host) in ("127.0.0.1", "::1", "localhost")

    def _require_local(request: Request) -> None:
        if not _is_local(request):
            raise HTTPException(403, "共享只能在本机（127.0.0.1）操作。")

    def _share_locked() -> None:
        """共享期间锁住「刷新存档 / 更换目录」，本机与访客一视同仁。"""
        if share.enabled:
            raise HTTPException(409, "共享中已锁定：请先停止共享。")

    def _share_idle(request: Request) -> dict:
        return localize_share({"enabled": False, "isLocal": _is_local(request), "host": None,
                "port": None, "base": None, "kind": "none", "source": "nic",
                "hint": "", "note": "", "candidates": [],
                "reach": share_mod.idle_reach("none")}, request.query_params.get("lang", "zh"))

    def _share_view(request: Request, *, host: Optional[str] = None,
                    port: Optional[int] = None, remote: bool = False,
                    refresh: bool = False, with_reach: bool = True) -> dict:
        """共享对话框要的全部信息（地址选择 + 文案 + 自测结果）。"""
        candidates = share_mod.gather_candidates(remote=remote, refresh=refresh)
        entry = None
        if host:
            entry = next((c for c in candidates if c.get("ip") == host), None)
        else:
            entry = share_mod.pick_host(candidates,
                                        default_ip=share_mod.default_route_ip())
            host = str(entry["ip"]) if entry else None
        # 手填的（不在候选里的）地址按 manual 处理，只写进链接文本
        kind = str(entry["kind"]) if entry else ("manual" if host else "none")
        source = str(entry["source"]) if entry else ("manual" if host else "nic")
        resolved = int(port) if port else (share.port or share.base_port)
        if with_reach and share.enabled and host and kind in ("public", "manual"):
            reach = share_mod.check_reachable(host, resolved)
        else:
            reach = share_mod.idle_reach(kind)
        return localize_share({
            "enabled": share.enabled,
            "isLocal": _is_local(request),
            "host": host,
            "port": resolved,
            "base": "http://%s:%d" % (host, resolved) if host else None,
            "kind": kind,
            "source": source,
            "hint": share_mod.hint_for(kind),
            "note": share_mod.note_for(kind, source),
            "candidates": candidates,
            "reach": reach,
        }, request.query_params.get("lang", "zh"))

    @app.get("/api/replays")
    def api_replays(lang: Literal["zh", "en"] = Query("zh")):
        return localize_replays(manager.replays(), lang)

    @app.post("/api/refresh")
    def api_refresh():
        _share_locked()
        manager.refresh()
        manager._static.clear()
        return {"ok": True, "saves": len(manager.infos)}

    @app.get("/api/replay/{seed}")
    def api_replay(seed: int, lang: Literal["zh", "en"] = Query("zh")):
        try:
            return localize_static(manager.static_info(seed), lang)
        except KeyError:
            raise HTTPException(404, f"seed {seed} not found")

    @app.get("/api/replay/{seed}/turns")
    def api_turns(seed: int):
        tm = manager.turn_map(seed)
        if not tm:
            raise HTTPException(404, f"seed {seed} not found")
        return [
            {"turn": i.turn, "timestamp": i.timestamp, "mtime": i.mtime}
            for i in sorted(tm.values(), key=lambda s: s.turn)
        ]

    @app.get("/api/replay/{seed}/loadstate")
    def api_loadstate(seed: int):
        tm = manager.turn_map(seed)
        if not tm:
            raise HTTPException(404, f"seed {seed} not found")
        return manager.loadstate(seed)

    @app.get("/api/replay/{seed}/turnstats")
    def api_turnstats(seed: int, turn: int = Query(0)):
        tm = manager.turn_map(seed)
        if not tm:
            raise HTTPException(404, f"seed {seed} not found")
        return manager.turnstats(seed, turn)

    # --- v0.25: Steam community name -------------------------------------
    @app.get("/api/steam/name/{steamid}")
    def api_steam_name(steamid: str):
        """Local proxy for the profile XML (the browser often cannot fetch it).

        Answers 502 when the lookup fails so the front end can show
        "查询失败" after its own 5 s direct attempt times out.
        """
        if not steamid.isdigit():
            raise HTTPException(400, "bad steamid")
        try:
            name = fetch_steam_name(steamid)
        except Exception as exc:
            raise HTTPException(502, f"steam lookup failed: {exc}")
        return {"steamId": steamid, "name": name}

    # --- v0.28: 金币流水账（右栏文明卡「金币」明细里的三指标） --------------
    @app.get("/api/gold")
    def api_gold(seed: int = Query(0), range_key: str = Query("all", alias="range"),
                 weighted: int = Query(0), end: int = Query(0), legacy: int = Query(0),
                 lang: Literal["zh", "en"] = Query("zh")):
        """打钱 / 吸钱 / 净金币交易。

        只读**默认日志目录**（存档目录同级的 ``Logs``，或 ``%LOCALAPPDATA%\\Firaxis
        Games\\…\\Logs``），不接受指定目录。日志还必须"刚写过"并且能和 ``seed``
        对应存档的主文明槽位 / 文明对上，否则返回 ``ok=false`` + ``reason`` —— 前端会把
        整块金币流水隐藏掉，只留一行提示（隔夜账不再显示）。

        ``range`` = ``all | 5 | 10 | 30``，``weighted=1`` 按 1.036^(末回合-该期)
        折算，``end`` 指定窗口末回合（默认取日志里的最新回合）。
        """
        save_players = None
        if seed:
            try:
                static = manager.static_info(seed)
            except KeyError:
                static = None                       # 未知 seed：当"读不到本局信息"处理
            if static:
                # 开局日志可能保留 MOD 替换前的城邦名；用主文明确认本局。
                save_players = {int(p["iPlayer"]): str(p.get("civStr") or "")
                                for p in static.get("players", [])
                                if p.get("kind", "major") == "major"}
        report = build_gold_report(save_dir=manager.effective_save_dir, seed=seed or None,
                                 save_players=save_players, range_key=range_key,
                                 weighted=bool(weighted),
                                 end_turn=end or None, legacy=bool(legacy))
        if "reason" in report:
            report["reason"] = ui(report["reason"], lang)
        return report

    # --- v0.25: save directory selection (session scope) ------------------
    @app.get("/api/savedir")
    def api_savedir():
        current = Path(manager.effective_save_dir)
        return {"current": manager.effective_save_dir,
                "default": str(default_save_dir()),
                "browse": str(current.parent if current.is_file() else current)}

    @app.post("/api/savedir")
    def api_set_savedir(payload: dict):
        _share_locked()
        path = str((payload or {}).get("path") or "").strip()
        if not path:
            raise HTTPException(400, "path required")
        try:
            manager.set_save_dir(path)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return manager.source_result()

    @app.post("/api/saves/import")
    async def api_import_saves(request: Request, kind: Literal["file", "directory"] = "file"):
        _share_locked()
        async with request.form(max_files=10000) as form:
            uploads = [value for _, value in form.multi_items() if isinstance(value, UploadFile)]
            # Check again after the upload in case sharing started meanwhile.
            _share_locked()
            try:
                return await run_in_threadpool(manager.import_saves, uploads, kind)
            except ValueError as exc:
                raise HTTPException(400, str(exc))

    @app.get("/api/browse")
    def api_browse(path: str = Query("")):
        _share_locked()
        return browse_dir(path or None)

    # --- v0.26: native folder picker --------------------------------------
    @app.post("/api/savedir/pick")
    def api_savedir_pick():
        """Open the OS directory dialog; ``{"path": null}`` when cancelled.

        Answers 501 off Windows (and 502 when the dialog host itself fails) so
        the UI can fall back to typing / pasting a path.
        """
        _share_locked()
        try:
            # v0.27: start in the folder currently being scanned
            current = Path(manager.effective_save_dir)
            picked = pick_folder(initial=str(current.parent if current.is_file() else current))
        except NotImplementedError as exc:
            raise HTTPException(501, str(exc))
        except Exception as exc:            # pragma: no cover - dialog host
            raise HTTPException(502, f"无法打开目录选择框：{exc}")
        return {"path": picked}

    # --- v0.38: 复盘共享 ---------------------------------------------------
    # 共享期间另起一个绑 0.0.0.0 的 uvicorn（见 share.ShareSession），链接里的地址
    # 按「本机网卡公网 → UU 虚拟网 → 云元数据 / 外部回显 → 手填」挑；只有本机能
    # 启停共享，访客连共享开关都点不动。
    @app.get("/api/share")
    def api_share(request: Request):
        if not share.enabled:
            return _share_idle(request)
        return _share_view(request, host=share.link_host, port=share.port)

    @app.get("/api/share/probe")
    def api_share_probe(request: Request, host: str = Query(""),
                        port: int = Query(0), remote: int = Query(0)):
        """候选地址 / 文案 / 回连自测（``remote=1`` 才允许发起对外探测）。"""
        _require_local(request)
        return _share_view(request, host=(host.strip() or None) or share.link_host,
                           port=port or None, remote=bool(remote))

    @app.post("/api/share/start")
    def api_share_start(request: Request, payload: Optional[dict] = None):
        """开始共享（或换地址 / 换端口）。``host`` 只决定链接文案。"""
        _require_local(request)
        body = payload or {}
        host = str(body.get("host") or "").strip() or None
        port: Optional[int] = None
        raw_port = body.get("port")
        if raw_port not in (None, ""):
            try:
                port = int(raw_port)
            except (TypeError, ValueError):
                raise HTTPException(400, "端口必须是数字。")
            if not 1 <= port <= 65535:
                raise HTTPException(400, "端口超出范围（1-65535）。")
        view = _share_view(request, host=host, port=port, refresh=True,
                           with_reach=False)
        try:
            share.start(host=view["host"], port=port, kind=view["kind"],
                        source=view["source"])
        except share_mod.ShareError as exc:
            raise HTTPException(400, str(exc))
        # 端口可能是自动顺延出来的，绑定后再算一次链接与自测结果
        return _share_view(request, host=share.link_host, port=share.port)

    @app.post("/api/share/stop")
    def api_share_stop(request: Request):
        _require_local(request)
        share.stop()
        return _share_idle(request)

    @app.get("/api/replay/{seed}/turn/{n}")
    def api_turn(request: Request, seed: int, n: int, gz: int = Query(1),
                 lang: Literal["zh", "en"] = Query("zh")):
        save = manager.turn_map(seed).get(n)
        if save is None:
            raise HTTPException(404, f"turn {n} not found for seed {seed}")
        # v0.28.1: the *shape* of a turn payload is tied to SCHEMA_VERSION, and the
        # old ``public, max-age=3600`` made the browser keep its copy for an hour —
        # after a schema bump it kept replaying the stale body, so the civ card fell
        # back to the all-turns ``staticInfo`` religions (the "turn 1 already shows
        # a 4-belief religion" report).  Answer with an ETag and let the browser
        # revalidate every time: unchanged payload = one cheap 304, changed payload
        # = new body, never a stale mix.
        etag = (f'W/"{seed}-{n}-{save.mtime!r}-{save.size}-'
                f'{SCHEMA_VERSION}-{rules_token()}-{display_token()}-{lang}-gz{int(bool(gz))}"')
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        try:
            payload = manager.load_payload(seed, n)
        except KeyError:
            raise HTTPException(404, f"turn {n} not found for seed {seed}")
        profile = manager.static_info(seed).get("identityProfile", "vanilla") if lang == "en" else "vanilla"
        payload = localize_turn(payload, profile, lang)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if gz:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
        return Response(content=body, media_type="application/json", headers=headers)

    @app.get("/api/gamedb/names")
    def api_names(hashes: str = Query(""), profile: Literal["", "vanilla", "bbg", "ccb"] = Query(""),
                  lang: Literal["zh", "en"] = Query("zh")):
        out = {}
        for token in hashes.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                h = int(token, 0) & 0xFFFFFFFF
            except ValueError:
                continue
            out[str(h)] = _resolve(h, profile, lang)
        return out

    @app.get("/api/gamedb/type/{hash_value}")
    def api_type(hash_value: str, profile: Literal["", "vanilla", "bbg", "ccb"] = Query(""),
                 lang: Literal["zh", "en"] = Query("zh")):
        try:
            h = int(hash_value, 0) & 0xFFFFFFFF
        except ValueError:
            raise HTTPException(400, "bad hash")
        resolved = _resolve(h, profile, lang)
        resolved["hash"] = h
        return resolved

    @app.get("/api/gamedb/tileyield")
    def api_tileyield(terrain: str = "-1", feature: str = "-1",
                      resource: str = "-1", improvement: str = "-1"):
        def _h(v):
            try:
                return int(v, 0) & 0xFFFFFFFF
            except ValueError:
                return 0xFFFFFFFF
        yields = db.tile_yields(_h(terrain), _h(feature), _h(resource), _h(improvement))
        return {str(k): v for k, v in yields.items()}

    @app.get("/api/health")
    def api_health():
        return {
            "ok": True,
            "gamedb": db.available,
            "saves": len(manager.infos),
            "seeds": [s for s in manager.groups if s],
        }

    if ICONS_DIR.exists():
        app.mount("/assets/icons", StaticFiles(directory=str(ICONS_DIR)), name="icons")
    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app
