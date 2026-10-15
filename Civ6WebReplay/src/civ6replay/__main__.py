"""``python -m civ6replay`` entry point."""
from __future__ import annotations

import argparse
import os
import threading
import webbrowser


def _run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="Civ6 WebReplay",
                                 description="Civ6 WebReplay - 文明 VI 浏览器复盘工具")
    ap.add_argument("--save-dir", default=os.environ.get("CIV6_SAVE_DIR"),
                    help="存档文件或目录，默认 Multi/auto")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--share-port", type=int, default=8766,
                    help="共享端口：点顶栏「共享」时另起的对外监听（默认 8766）")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--load-workers", type=int, default=None,
                    help="存档解析并发数 1-16，默认为 CPU 逻辑线程数的一半（向下取整，至少 1）；1 为串行")
    args = ap.parse_args(argv)

    from .server import create_app
    app = create_app(args.save_dir, host=args.host, port=args.port,
                     share_port=args.share_port, workers=args.load_workers)
    url = f"http://{args.host}:{args.port}/"

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    import uvicorn
    print(f"Civ6 WebReplay → {url}  (Ctrl+C 退出)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv=None) -> int:
    try:
        return _run(argv)
    except ValueError as exc:
        print(f"[错误] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
