"""知映系统托盘（Windows 安装版）—— 单进程完成全部引导，零控制台窗口。

设计（解决两个实测缺陷）：
1) 原先由 start.cmd 引导 → 双击时必然弹一个 cmd 窗口，且「校验知识库表结构」
   那步耗时不短，用户看到窗口赖着不关。
2) 管道内部子进程未抑制窗口 → 处理视频时「黑窗一闪」。

现在：快捷方式直接指向 pythonw.exe（无控制台），本模块自解析安装路径，
自行完成「起 PG → 建库 → 建表 → 起服务 → 开浏览器 → 托盘驻留」。
所有子进程经 zhiying.proc 调用，带 CREATE_NO_WINDOW，全程无窗口。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------- 路径自解析
# 安装版：sys.executable = {app}\runtime\python\pythonw.exe → parents[2] = {app}
# 开发版：回退到 ZHIYING_HOME 或仓库根
def _app_home() -> Path:
    env = os.environ.get("ZHIYING_HOME")
    if env and Path(env).is_dir():
        return Path(env)
    try:
        cand = Path(sys.executable).resolve().parents[2]
        if (cand / "runtime" / "pg").is_dir() or (cand / "web").is_dir():
            return cand
    except Exception:  # noqa: BLE001
        pass
    return Path(__file__).resolve().parents[2]


APP_HOME = _app_home()
DATA_DIR = Path(os.environ.get("ZHIYING_DATA") or (Path.home() / "AppData" / "Roaming" / "zhiying"))
PORT = int(os.environ.get("ZHIYING_API_PORT", "8600"))
PG_BIN = APP_HOME / "runtime" / "pg" / "bin"
PG_DATA = DATA_DIR / "pg"
PG_PORT_FILE = DATA_DIR / "pg.port"
PG_CANDIDATES = list(range(15499, 15511))

os.environ.setdefault("ZHIYING_HOME", str(APP_HOME))
os.environ.setdefault("ZHIYING_DATA", str(DATA_DIR))
if (APP_HOME / "web").is_dir():
    os.environ.setdefault("ZHIYING_WEB_DIST", str(APP_HOME / "web"))


def _log(msg: str) -> None:
    """写到 %APPDATA%\\zhiying\\app.log，便于无窗口时排查。"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "app.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _server_ready(timeout: float = 3.0) -> bool:
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return False


# ---------------------------------------------------------------- PG 引导
def _port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _pg_ready(port: int) -> bool:
    from zhiying import proc

    pg_isready = PG_BIN / "pg_isready.exe"
    if not pg_isready.is_file():
        return False
    try:
        r = proc.run(
            [str(pg_isready), "-h", "127.0.0.1", "-p", str(port), "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _ensure_pg() -> int | None:
    """确保嵌入式 PG 运行，返回端口；未安装 PG 组件则返回 None。"""
    from zhiying import proc

    pg_ctl = PG_BIN / "pg_ctl.exe"
    if not pg_ctl.is_file():
        _log("未安装 PG 组件，跳过知识库")
        return None

    # 1) 复用已记录且健康的端口
    port = None
    if PG_PORT_FILE.is_file():
        try:
            saved = int(PG_PORT_FILE.read_text(encoding="utf-8").strip() or 0)
            if saved and _pg_ready(saved):
                port = saved
        except Exception:  # noqa: BLE001
            pass

    # 2) 首次初始化
    if not (PG_DATA / "PG_VERSION").is_file():
        _log("首次初始化数据库")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            proc.run(
                [str(PG_BIN / "initdb.exe"), "-D", str(PG_DATA), "-U", "postgres",
                 "-E", "UTF8", "--locale=C"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180,
            )
        except Exception as e:  # noqa: BLE001
            _log(f"initdb 失败: {type(e).__name__}: {e}")

    # 3) 未运行则挑空闲端口启动
    if port is None:
        port = next((p for p in PG_CANDIDATES if _port_free(p)), None)
        if port is None:
            _log("找不到空闲数据库端口")
            return None
        try:
            PG_PORT_FILE.write_text(str(port), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        # 关键：pg_ctl start 会 spawn postgres 守护进程并继承 stdout 管道；
        # 用 capture_output 会等不到 EOF 而 timeout（曾导致托盘进程静默崩溃）。
        # 必须用 DEVNULL 重定向，日志由 pg_ctl -l 写文件。
        try:
            proc.run(
                [str(pg_ctl), "-D", str(PG_DATA), "-o", f"-p {port}",
                 "-l", str(DATA_DIR / "pg.log"), "start"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90,
            )
        except Exception as e:  # noqa: BLE001
            _log(f"pg_ctl start 异常（可能仅超时，服务可能已起）: {type(e).__name__}")
        for _ in range(40):
            if _pg_ready(port):
                break
            time.sleep(0.5)

    if not _pg_ready(port):
        _log(f"数据库未就绪（端口 {port}）")
        return None

    # 4) 建库 + 建表（幂等）
    os.environ["ZHIYING_DB_HOST"] = "127.0.0.1"
    os.environ["ZHIYING_DB_PORT"] = str(port)
    os.environ["ZHIYING_DB_USER"] = "postgres"
    os.environ["ZHIYING_DB_NAME"] = "zhiying"
    try:
        from zhiying.storage.init_db import main as init_db_main

        init_db_main([])
        _log(f"数据库就绪（端口 {port}）")
    except Exception as e:  # noqa: BLE001
        _log(f"建表失败: {type(e).__name__}: {e}")
    return port


def _stop_pg() -> None:
    from zhiying import proc

    pg_ctl = PG_BIN / "pg_ctl.exe"
    if not (pg_ctl.is_file() and (PG_DATA / "PG_VERSION").is_file()):
        return
    try:
        proc.run([str(pg_ctl), "-D", str(PG_DATA), "stop", "-m", "fast"],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 托盘
def _open_browser() -> None:
    threading.Thread(target=lambda: webbrowser.open(f"http://127.0.0.1:{PORT}"), daemon=True).start()


def main() -> int:
    # pythonw 下 stdout/stderr 为 None：重定向到 app.log（追加），
    # 这样管道内所有 print（转写降级原因、帧描述告警等）都可查，不再丢失
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(DATA_DIR / "app.log", "a", encoding="utf-8", buffering=1))

    # 单实例：服务已在跑则只开浏览器
    if _server_ready(timeout=2.0):
        _open_browser()
        return 0

    _log("=== 启动 ===")
    try:
        _ensure_pg()
    except Exception as e:  # noqa: BLE001
        # 数据库故障不能阻塞整个应用（纯 md 模式仍可用）
        _log(f"数据库引导异常，将以无知识库模式启动: {type(e).__name__}: {e}")

    import uvicorn

    from zhiying.api import app

    threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": PORT, "log_level": "warning"},
        daemon=True,
    ).start()

    try:
        import pystray
        from PIL import Image
    except ImportError:
        _log("缺少 pystray/Pillow，退化为后台服务（无托盘）")
        if _server_ready(timeout=30):
            _open_browser()
        threading.Event().wait()
        return 0

    ico = Path(__file__).parent / "assets" / "zhiying.ico"
    image = Image.open(ico) if ico.is_file() else Image.new("RGBA", (64, 64), (99, 102, 241, 255))

    def _quit(icon) -> None:  # noqa: ANN001
        _log("用户退出")
        _stop_pg()
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("打开知映", lambda *_: _open_browser(), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", _quit),
    )
    icon = pystray.Icon("zhiying", image, "知映 zhiying", menu)

    # 服务就绪后再开浏览器（避免首启"拒绝连接"）
    def _late_open() -> None:
        if _server_ready(timeout=60):
            _open_browser()
            _log("服务就绪，已打开浏览器")
        else:
            _log("服务启动超时")

    threading.Thread(target=_late_open, daemon=True).start()
    icon.run()
    return 0


if __name__ == "__main__":
    # pythonw 下无控制台，未捕获异常会静默消失：写日志并弹窗提示
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        import traceback
        _log("致命错误: " + traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "启动失败，详情见 %APPDATA%\\\\zhiying\\\\app.log\\n\\n" + str(exc)[:300],
                "知映 zhiying",
                0x10,
            )
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
