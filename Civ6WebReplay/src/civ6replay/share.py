"""v0.38: 复盘共享 —— 本机地址探测、链接选址与对外监听器。

共享要解决的事情只有一件：让同一个局域网 / UU 虚拟网 / 公网入口上的其他人也能用
浏览器打开本机正在看的这一局复盘。为此要在本机再开一个绑 ``0.0.0.0`` 的 uvicorn
（主进程仍然只绑 ``127.0.0.1``），并按

    本机网卡公网 IP → UU 虚拟网 → 云元数据 / 外部回显拿到的公网 IP → 用户手填

的顺序挑出链接里该写哪个地址。只有网卡层找不到公网 IP 时才去问云厂商的元数据服务
或公网回显（那两次都是对外请求，离线环境会静默降级）。

注意：拿到公网 IP ≠ 该端口可达。云安全组、iptables、路由器端口映射没放行的话链接
一样打不开，而且这从本机无法可靠判断，所以只做一个「尽力而为」的回连自测，结果只
当提示用（见 :func:`check_reachable`）。
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

SHARE_PORT_DEFAULT = 8766
"""共享监听器的默认端口（主进程默认占着 8765，所以错开一位）。"""

PORT_SCAN_RANGE = 10
"""自动模式下从 :data:`SHARE_PORT_DEFAULT` 起顺延的最多端口数。"""

NIC_CACHE_TTL = 15.0
"""网卡枚举结果的缓存秒数（PowerShell 一次约 0.3 秒，不该反复付这个钱）。"""

UU_ADAPTER_KEY = "uulanplay"
"""UU 加速器的虚拟网卡名（本机实测为 ``UU Lanplay``），归一化后按子串匹配。"""

FETCH_TIMEOUT_METADATA = 0.4
FETCH_TIMEOUT_ECHO = 2.0
REACH_TIMEOUT = 3.0
SHARE_UA = "civ6replay-share/0.42"


# --- 地址分类 ---------------------------------------------------------------

def _norm_name(name: Optional[str]) -> str:
    """网卡名归一化：去掉空白 / 连字符 / 下划线再小写（``UU Lanplay`` → ``uulanplay``）。"""
    return re.sub(r"[\s_\-]+", "", str(name or "")).lower()


def is_public_ipv4(ip: str) -> bool:
    """全局可路由的 IPv4 才算「公网」（``100.64/10`` 之类的 CGNAT 不算）。"""
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return False
    if addr.version != 4:
        return False
    return bool(addr.is_global) and not addr.is_multicast and not addr.is_reserved


def _usable_ipv4(ip: str) -> bool:
    """能出现在候选列表里的地址（排除回环、169.254 自动地址、0.0.0.0）。"""
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return False
    if addr.version != 4:
        return False
    return not (addr.is_loopback or addr.is_link_local or addr.is_unspecified
                or addr.is_multicast)


def classify_ip(ip: str, name: str = "") -> str:
    """``public`` / ``uu`` / ``lan``（公网判定优先于网卡名）。"""
    if is_public_ipv4(ip):
        return "public"
    if UU_ADAPTER_KEY in _norm_name(name):
        return "uu"
    return "lan"


def label_of(ip: str, name: str = "", kind: str = "", source: str = "nic") -> str:
    """候选列表里那一行显示什么。"""
    tail = f"（{name}）" if name else ""
    if kind == "uu":
        return f"{ip} · UU 虚拟网{tail}"
    if kind == "public":
        return f"{ip} · {'公网' if source == 'nic' else '公网（探测所得）'}{tail}"
    return f"{ip} · 本机地址{tail}"


def default_route_ip(timeout: float = 0.2) -> Optional[str]:
    """默认路由出口的源地址（UDP connect 不发包，失败时返回 ``None``）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


# --- 网卡枚举 ---------------------------------------------------------------

_NIC_PS = (
    "$ErrorActionPreference = 'SilentlyContinue';"
    "try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {};"
    "$up = @(Get-NetAdapter -IncludeHidden | Where-Object { $_.Status -eq 'Up' } |"
    " ForEach-Object { [int]$_.ifIndex });"
    "$rows = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {"
    " $_.AddressState -eq 'Preferred' -and"
    " ($up.Count -eq 0 -or $up -contains [int]$_.InterfaceIndex)"
    "} | ForEach-Object {"
    " [pscustomobject]@{ name = [string]$_.InterfaceAlias; ip = [string]$_.IPAddress }"
    "});"
    "ConvertTo-Json -InputObject @($rows) -Compress -Depth 3"
)

_PS_TIMEOUT = 6.0

_nic_lock = threading.Lock()
_nic_cache: Dict[str, object] = {"at": 0.0, "rows": None}


def _decode_ps(data: bytes) -> str:
    """PowerShell 重定向输出的编码：脚本里已改成 UTF-8，老版本退回 ANSI 代码页。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("mbcs", "replace")


def _powershell_addresses() -> Optional[List[dict]]:
    """``[{name, ip}]``；PowerShell 不可用 / 超时 / 输出无法解析时返回 ``None``。"""
    if os.name != "nt":
        return None
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-Command", _NIC_PS],
                              capture_output=True, timeout=_PS_TIMEOUT,
                              creationflags=creationflags, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    text = _decode_ps(done.stdout or b"").strip()
    if not text:
        return None
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    if isinstance(doc, dict):
        doc = [doc]
    if not isinstance(doc, list):
        return None
    rows: List[dict] = []
    for row in doc:
        if not isinstance(row, dict):
            continue
        ip = str(row.get("ip") or "").strip()
        if not ip:
            continue
        rows.append({"name": str(row.get("name") or "").strip(), "ip": ip})
    return rows


def _socket_addresses() -> List[dict]:
    """无 PowerShell 时的退路：只有地址、没有网卡名（因此永远匹配不到 UU）。"""
    rows: List[dict] = []
    seen = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip in seen:
                continue
            seen.add(ip)
            rows.append({"name": "", "ip": ip})
    except OSError:                                        # pragma: no cover
        pass
    route = default_route_ip()
    if route and route not in seen:
        rows.append({"name": "", "ip": route})
    return rows


def local_addresses(refresh: bool = False) -> List[dict]:
    """本机可用 IPv4 候选：``[{name, ip, kind, source, label}]``（缓存 15 秒）。

    只保留 ``AddressState = Preferred`` 且网卡在 Up 状态的地址，并滤掉回环 /
    169.254 自动地址；``kind`` 见 :func:`classify_ip`。
    """
    with _nic_lock:
        cached = _nic_cache["rows"]
        fresh = (cached is not None
                 and (time.monotonic() - float(_nic_cache["at"])) < NIC_CACHE_TTL)
        if fresh and not refresh:
            return [dict(r) for r in cached]               # type: ignore[union-attr]

    rows = _powershell_addresses()
    if rows is None:
        rows = _socket_addresses()

    out: List[dict] = []
    seen = set()
    for row in rows:
        ip = row.get("ip") or ""
        if ip in seen or not _usable_ipv4(ip):
            continue
        seen.add(ip)
        name = row.get("name") or ""
        kind = classify_ip(ip, name)
        out.append({"name": name, "ip": ip, "kind": kind, "source": "nic",
                    "label": label_of(ip, name, kind, "nic")})

    with _nic_lock:
        _nic_cache["at"] = time.monotonic()
        _nic_cache["rows"] = out
    return [dict(r) for r in out]


def pick_host(candidates: Sequence[dict],
              default_ip: Optional[str] = None) -> Optional[dict]:
    """按优先级挑默认地址：网卡公网 → UU → 探测到的公网 → ``None``。

    有多个网卡公网地址时优先默认路由出口那一个；UU 与回显结果永远进不了这一档，
    因为「回显到的家宽 WAN 地址」在没做端口映射时根本连不进来。
    """
    pubs = [c for c in candidates
            if c.get("kind") == "public" and c.get("source") == "nic"]
    if pubs:
        if default_ip:
            for cand in pubs:
                if cand.get("ip") == default_ip:
                    return cand
        return pubs[0]
    for cand in candidates:
        if cand.get("kind") == "uu":
            return cand
    for cand in candidates:
        if cand.get("kind") == "public":
            return cand
    return None


# --- 外部探测（云元数据 / 公网回显） ----------------------------------------

Fetch = Callable[..., Tuple[int, str]]

# 云厂商的元数据服务：只有对应厂商的机器上才连得通，普通电脑是静默超时。
# 华为云的地址与 AWS 相同，所以只留一条。
METADATA_URLS: Tuple[Tuple[str, str, dict], ...] = (
    ("aliyun", "http://100.100.100.200/latest/meta-data/eipv4", {}),
    ("qcloud", "http://metadata.tencentyun.com/latest/meta-data/public-ipv4", {}),
    ("aws", "http://169.254.169.254/latest/meta-data/public-ipv4", {}),
    ("azure", "http://169.254.169.254/metadata/instance/network/interface/0/ipv4"
              "/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text",
     {"Metadata": "true"}),
)

# 公网回显：返回「你在外面看起来是什么 IP」。ipify / checkip 是经典选择，
# ip.3322.net 与 ipip.net 在国内可达性更好。
ECHO_URLS: Tuple[str, ...] = (
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
    "https://ip.3322.net",
    "https://myip.ipip.net",
)

_IPV4_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")


def _ssl_context():
    """优先信任 Windows 证书库（企业代理 / 杀软换过根证书时 certifi 会验签失败）。"""
    try:
        ctx = ssl.create_default_context()
        ctx.load_default_certs()
        return ctx
    except Exception:                                      # pragma: no cover
        return True


def default_fetch(url: str, *, method: str = "GET", headers: Optional[dict] = None,
                  timeout: float = 1.0) -> Tuple[int, str]:
    """``(status, text)``；任何异常都往上抛，由调用方吞掉。"""
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=True, verify=_ssl_context(),
                      headers={"User-Agent": SHARE_UA}) as client:
        resp = client.request(method, url, headers=headers or {})
    return resp.status_code, resp.text


def parse_ipv4(text: str) -> Optional[str]:
    """从响应体里挑出第一个全局 IPv4（``myip.ipip.net`` 会带中文前缀）。"""
    for match in _IPV4_RE.finditer(str(text or "")):
        cand = match.group(1)
        if is_public_ipv4(cand):
            return cand
    return None


def _imdsv2_token(fetch: Fetch, timeout: float) -> Optional[str]:
    """AWS 新镜像要求 IMDSv2：先 PUT 换 token 再带 token 取元数据。"""
    try:
        status, text = fetch("http://169.254.169.254/latest/api/token", method="PUT",
                             headers={"X-aws-ec2-metadata-token-ttl-seconds": "120"},
                             timeout=timeout)
    except Exception:
        return None
    if status != 200:
        return None
    token = str(text or "").strip()
    return token or None


def probe_metadata(fetch: Fetch = default_fetch,
                   timeout: float = FETCH_TIMEOUT_METADATA) -> Optional[str]:
    """并行问一遍云厂商元数据服务（各自独立主机，互不阻塞），返回公网 IP。"""
    results: List[Optional[str]] = [None] * len(METADATA_URLS)
    threads: List[threading.Thread] = []

    def worker(index: int, url: str, headers: dict) -> None:
        try:
            status, text = fetch(url, headers=headers, timeout=timeout)
        except Exception:
            return
        if status == 401 and "169.254.169.254" in url:
            token = _imdsv2_token(fetch, timeout)
            if not token:
                return
            try:
                status, text = fetch(url,
                                     headers={**headers,
                                              "X-aws-ec2-metadata-token": token},
                                     timeout=timeout)
            except Exception:
                return
        if status != 200:
            return
        body = str(text or "").strip()
        results[index] = parse_ipv4(body) or (body if is_public_ipv4(body) else None)

    for i, (_vendor, url, headers) in enumerate(METADATA_URLS):
        thread = threading.Thread(target=worker, args=(i, url, headers), daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join(timeout + 0.5)
    for ip in results:
        if ip:
            return ip
    return None


def probe_echo(fetch: Fetch = default_fetch,
               timeout: float = FETCH_TIMEOUT_ECHO) -> Optional[str]:
    """并行问一遍公网回显服务，返回最先拿到的公网 IP。"""
    first: Dict[str, Optional[str]] = {"ip": None}
    lock = threading.Lock()

    def worker(url: str) -> None:
        try:
            status, text = fetch(url, timeout=timeout)
        except Exception:
            return
        if status != 200:
            return
        ip = parse_ipv4(text)
        if not ip:
            return
        with lock:
            if first["ip"] is None:
                first["ip"] = ip

    threads = [threading.Thread(target=worker, args=(url,), daemon=True)
               for url in ECHO_URLS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout + 0.5)
    return first["ip"]


def probe_remote(fetch: Fetch = default_fetch, nic_ips: Sequence[str] = (),
                 *, meta_budget: float = 0.8,
                 echo_budget: float = FETCH_TIMEOUT_ECHO + 0.6) -> Optional[dict]:
    """网卡层没找到公网 IP 时的兜底：``{ip, source, nat}`` 或 ``None``。

    元数据与回显两组同时开跑，但优先采纳元数据的结果（云服务器上它 0.1 秒内就回来，
    普通电脑上整组在 0.4 秒内全部超时，于是自然落到回显）。
    """
    slots: Dict[str, Optional[str]] = {"metadata": None, "echo": None}
    events = {"metadata": threading.Event(), "echo": threading.Event()}

    def group(key: str, fn: Callable[[], Optional[str]]) -> None:
        try:
            slots[key] = fn()
        except Exception:
            slots[key] = None
        finally:
            events[key].set()

    threads = [
        threading.Thread(target=group, args=("metadata",
                                             lambda: probe_metadata(fetch)),
                         daemon=True),
        threading.Thread(target=group, args=("echo", lambda: probe_echo(fetch)),
                         daemon=True),
    ]
    for thread in threads:
        thread.start()

    events["metadata"].wait(meta_budget)
    if not slots["metadata"]:
        events["echo"].wait(echo_budget)

    ip = slots["metadata"] or slots["echo"]
    if not ip:
        return None
    return {"ip": ip,
            "source": "metadata" if slots["metadata"] else "echo",
            "nat": ip not in set(nic_ips)}


def gather_candidates(*, remote: bool = False, refresh: bool = False,
                      fetch: Optional[Fetch] = None) -> List[dict]:
    """候选地址列表（``remote=True`` 时才允许发起元数据 / 回显探测）。"""
    cands = local_addresses(refresh=refresh)
    if remote:
        known = {c["ip"] for c in cands}
        found = probe_remote(fetch or default_fetch, nic_ips=sorted(known))
        if found and found["ip"] not in known:
            cands.append({"name": "", "ip": found["ip"], "kind": "public",
                          "source": found["source"],
                          "label": label_of(found["ip"], "", "public",
                                            found["source"])})
    return cands


# --- 文案 -------------------------------------------------------------------

def hint_for(kind: str) -> str:
    """UU 场景要追加到分享信息里的那句提醒（其它场景为空）。"""
    if kind == "uu":
        return "本链接走 UU 虚拟局域网，观看期间请不要退出 UU 加速器。"
    return ""


def note_for(kind: str, source: str = "nic") -> str:
    """对话框里的可访问性说明（不进复制文案）。"""
    if kind == "uu":
        return "UU 虚拟网地址：对方需要与本机在同一 UU 房间，观看期间不要退出 UU 加速器。"
    if kind == "lan":
        return "本机局域网地址：仅同一局域网内的设备可以访问。"
    if kind == "manual":
        return "手填地址：本工具只把它写进链接，能否访问取决于你的端口映射 / 域名解析。"
    if kind == "public":
        if source == "nic":
            return ("本机网卡公网地址：自测通过也只说明本机能连上，外网能否访问还取决于"
                    "运营商 / 校园网策略。")
        return ("该地址由云元数据 / 外部回显探测得到，属于 NAT 映射：请确认云安全组或"
                "路由器端口映射已放行该端口。")
    return "未检测到可用地址：请从候选列表选择，或手填 ip:端口。"


def idle_reach(kind: str) -> dict:
    """没有真的做过回连自测时的 ``reach`` 结构。"""
    if kind == "uu":
        detail = ("本机 UU 虚拟网地址：对方需与本机在同一 UU 房间，且观看期间不要退出"
                  "UU 加速器。")
    elif kind == "lan":
        detail = "本机局域网地址：仅同一局域网内的设备可以访问。"
    elif kind in ("public", "manual"):
        detail = "尚未开始共享，未做回连自测。"
    else:
        detail = "未选定地址。"
    return {"checked": False, "ok": None, "detail": detail}


def check_reachable(host: str, port: int, *, timeout: float = REACH_TIMEOUT,
                    connect: Optional[Callable[..., object]] = None) -> dict:
    """本机回连 ``host:port`` 的尽力而为自测。

    连得上说明映射 / 放行大概率没问题；连不上不一定是真不通（有的云 EIP 回连会被
    安全组拦，很多 NAT 不支持回流），所以调用方只把它当提示。
    """
    connector = connect or socket.create_connection
    try:
        conn = connector((host, int(port)), timeout=timeout)
    except OSError as exc:
        return {"checked": True, "ok": False,
                "detail": "未能自测通过（%s）：请检查云安全组 / 路由器端口映射 / 防火墙。"
                          % (type(exc).__name__,)}
    try:
        if hasattr(conn, "close"):
            conn.close()                                   # type: ignore[union-attr]
    except OSError:                                        # pragma: no cover
        pass
    return {"checked": True, "ok": True, "detail": "自测可达。"}


# --- 对外监听器 -------------------------------------------------------------

class ShareError(RuntimeError):
    """共享无法启动（端口被占用等），消息直接给到界面。"""


def port_is_free(port: int, host: str = "0.0.0.0") -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


class ShareSession:
    """共享状态：对外监听器 + 当前对外公布的链接地址。

    ``bind_host`` 默认 ``0.0.0.0``（链接里写哪个地址与监听无关，反正是全网卡），
    ``reuse_port`` 用于主进程本来就绑在 ``0.0.0.0`` 的情况 —— 那时不再另起监听器，
    共享端口就是主端口。
    """

    def __init__(self, app, *, bind_host: str = "0.0.0.0",
                 base_port: int = SHARE_PORT_DEFAULT,
                 reuse_port: Optional[int] = None):
        self._app = app
        self.bind_host = bind_host
        self.base_port = int(base_port)
        self.reuse_port = int(reuse_port) if reuse_port else None
        self.link_host: Optional[str] = None
        self.kind = "none"
        self.source = "nic"
        self.port: Optional[int] = None
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # -- 状态 --------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        with self._lock:
            return self.port is not None

    def status(self) -> dict:
        with self._lock:
            return {"enabled": self.port is not None, "host": self.link_host,
                    "port": self.port, "kind": self.kind, "source": self.source,
                    "reused": self.reuse_port is not None}

    # -- 启停 --------------------------------------------------------------
    def _resolve_port(self, port: Optional[int]) -> int:
        if port is not None:
            return int(port)
        if self.port is not None:
            return self.port          # 已经绑过：不带端口就沿用当前端口
        if self.reuse_port:
            return self.reuse_port
        for offset in range(PORT_SCAN_RANGE):
            cand = self.base_port + offset
            if port_is_free(cand, self.bind_host):
                return cand
        raise ShareError("%d-%d 之间的端口都被占用了，请手填一个端口。"
                         % (self.base_port, self.base_port + PORT_SCAN_RANGE - 1))

    def _launch_listener(self, port: int) -> None:
        """在 daemon 线程里跑第二个 uvicorn（测试中可以替换掉）。"""
        import uvicorn

        config = uvicorn.Config(self._app, host=self.bind_host, port=port,
                                log_level="warning", access_log=False)
        server = uvicorn.Server(config)

        def run() -> None:
            try:
                server.run()
            except BaseException:                          # SystemExit: 端口被占
                pass

        thread = threading.Thread(target=run, name="civ6replay-share", daemon=True)
        thread.start()
        for _ in range(400):                               # 最多等 8 秒
            if getattr(server, "started", False):
                break
            if not thread.is_alive():
                break
            time.sleep(0.02)
        if not getattr(server, "started", False):
            server.should_exit = True
            raise ShareError("无法在 %s:%d 上启动共享监听（端口被占用？）。"
                             % (self.bind_host, port))
        self._server = server
        self._thread = thread

    def start(self, host: Optional[str], port: Optional[int],
              kind: str = "none", source: str = "nic") -> None:
        """启动 / 重绑监听器并记下对外公布的地址（端口没变就不重绑）。"""
        with self._lock:
            target = self._resolve_port(port)
            need_listener = (self.reuse_port is None
                             and (self.port != target or self._server is None))
            if need_listener:
                self._stop_listener()
                self._wait_port_free(target)
                if not port_is_free(target, self.bind_host):
                    raise ShareError("端口 %d 已被占用，请换一个端口。" % target)
                self._launch_listener(target)
            self.port = target
            self.link_host = str(host).strip() if host else None
            self.kind = kind
            self.source = source

    def _wait_port_free(self, port: int, timeout: float = 3.0) -> None:
        """刚停掉的监听器要过一会儿才放开端口，等一小会儿再判占用。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if port_is_free(port, self.bind_host):
                return
            time.sleep(0.05)

    def _stop_listener(self) -> None:
        """置 ``should_exit``，并在后台线程里等它退出。

        不能在请求线程里 join：停止共享的那个请求很可能正由被停的监听器自己处理，
        两边互相等就成了死锁（早期版本就是这样卡 5 秒的）。
        """
        server, thread = self._server, self._thread
        self._server, self._thread = None, None
        if server is None:
            return
        try:
            server.should_exit = True
        except Exception:                                  # pragma: no cover
            pass
        if thread is None:
            return

        def wait() -> None:
            thread.join(timeout=5.0)

        threading.Thread(target=wait, name="civ6replay-share-stop",
                         daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            self._stop_listener()
            self.port = None
            self.link_host = None
            self.kind = "none"
            self.source = "nic"
