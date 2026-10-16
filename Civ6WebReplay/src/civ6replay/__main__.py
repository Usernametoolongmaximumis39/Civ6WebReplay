"""``python -m civ6replay`` entry point."""
from __future__ import annotations

import argparse
import os
import socket
import threading
import webbrowser


def _listen_socket(host: str, port: int) -> socket.socket:
    """Reserve a port until uvicorn takes over the listening socket."""
    address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
    sock = socket.socket(address[0], address[1], address[2])
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(address[4])
        sock.listen(2048)
        return sock
    except BaseException:
        sock.close()
        raise


def _choose_port(host: str, port: int, share_port: int) -> tuple[int, socket.socket]:
    if not 1 <= port <= 65535:
        raise ValueError("端口必须在 1-65535 之间。")
    for candidate in range(port, min(port + 30, 65536)):
        if candidate != port and candidate == share_port:
            continue
        try:
            return candidate, _listen_socket(host, candidate)
        except OSError as exc:
            if exc.errno not in (48, 98, 10013, 10048):
                raise
    # If the nearby range is full, ask the OS for any free port.
    for _ in range(10):
        try:
            listener = _listen_socket(host, 0)
        except OSError as exc:
            raise ValueError(f"无法为 {host} 找到可用端口：{exc}") from exc
        selected = listener.getsockname()[1]
        if selected != share_port:
            return selected, listener
        listener.close()
    raise ValueError("无法找到与共享端口不同的可用端口。")


def _run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="Civ6 WebReplay",
                                 description="Civ6 WebReplay - 文明 VI 浏览器复盘工具")
    ap.add_argument("--save-dir", default=os.environ.get("CIV6_SAVE_DIR"),
                    help="存档文件或目录，默认 Multi/auto")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--auto-port", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--share-port", type=int, default=8766,
                    help="共享端口：点顶栏「共享」时另起的对外监听（默认 8766）")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--load-workers", type=int, default=None,
                    help="存档解析并发数 1-16，默认为 CPU 逻辑线程数的一半（向下取整，至少 1）；1 为串行")
    args = ap.parse_args(argv)

    listener = None
    if args.auto_port:
        selected, listener = _choose_port(args.host, args.port, args.share_port)
        if selected != args.port:
            print(f"[提示] 端口 {args.port} 已被占用，改用 {selected}。")
        args.port = selected

    from .server import create_app
    try:
        app = create_app(args.save_dir, host=args.host, port=args.port,
                         share_port=args.share_port, workers=args.load_workers)
        url = f"http://{args.host}:{args.port}/"

        if not args.no_browser:
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()

        import uvicorn
        print(f"Civ6 WebReplay → {url}  (Ctrl+C 退出)", flush=True)
        if listener is None:
            uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        else:
            config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
            uvicorn.Server(config).run(sockets=[listener])
    finally:
        if listener is not None:
            listener.close()
    return 0


def main(argv=None) -> int:
    try:
        return _run(argv)
    except ValueError as exc:
        print(f"[错误] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
