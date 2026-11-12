"""知映系统托盘（Windows 安装版）。

pythonw 下无控制台运行：uvicorn 跑在后台线程，pystray 托盘驻留；
浏览器关闭后服务仍常驻，右键「退出」才停止数据库与服务。

环境变量（由安装版 start.cmd 提供）：ZHIYING_DATA / ZHIYING_WEB_DIST / ZHIYING_API_PORT 等。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

_PORT = int(os.environ.get("ZHIYING_API_PORT", "8600"))
_DATA = Path(os.environ.get("ZHIYING_DATA", str(Path.home() / "AppData" / "Roaming" / "zhiying")))


def _server_ready(timeout: float = 30.0) -> bool:
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/api/health", timeout=2):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return False


def _stop_pg() -> None:
    """退出时停止嵌入式 PG（复用 start.cmd 记录的端口）。"""
    pg_ctl = Path(os.environ.get("ZHIYING_HOME", "")) / "runtime" / "pg" / "bin" / "pg_ctl.exe"
    pgdata = _DATA / "pg"
    if not (pg_ctl.is_file() and (pgdata / "PG_VERSION").is_file()):
        return
    try:
        subprocess.run(
            [str(pg_ctl), "-D", str(pgdata), "stop", "-m", "fast"],
            capture_output=True, timeout=15,
        )
    except Exception:  # noqa: BLE001
        pass


def _open_browser() -> None:
    threading.Thread(target=lambda: webbrowser.open(f"http://127.0.0.1:{_PORT}"), daemon=True).start()


def _quit(icon) -> None:  # noqa: ANN001
    _stop_pg()
    icon.stop()
    os._exit(0)


def main() -> int:
    # pythonw 下 stdout/stderr 为 None：uvicorn/logging 写流会异常，重定向到空设备
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name) is None:
            setattr(sys, stream_name, open(os.devnull, "w", encoding="utf-8"))

    # 单实例保护：服务已在跑则只开浏览器
    if _server_ready(timeout=2.0):
        _open_browser()
        return 0

    import uvicorn

    from zhiying.api import app

    threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": _PORT, "log_level": "warning"},
        daemon=True,
    ).start()

    try:
        import pystray
        from PIL import Image
    except ImportError:
        # 无托盘依赖时退化为纯后台服务（保持可运行）
        _server_ready()
        _open_browser()
        threading.Event().wait()
        return 0

    ico = Path(__file__).parent / "assets" / "zhiying.ico"
    image = Image.open(ico) if ico.is_file() else Image.new("RGBA", (64, 64), (99, 102, 241, 255))

    menu = pystray.Menu(
        pystray.MenuItem("打开知映", lambda *_: _open_browser(), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", _quit),
    )
    icon = pystray.Icon("zhiying", image, "知映 zhiying", menu)

    # 服务就绪后再开浏览器（避免首启"拒绝连接"闪屏）
    def _late_open() -> None:
        if _server_ready():
            _open_browser()

    threading.Thread(target=_late_open, daemon=True).start()
    icon.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
