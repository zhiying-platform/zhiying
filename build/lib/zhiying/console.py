"""Windows 控制台编码修复。

Windows 控制台默认 GBK（cp936），直接打印 ✅ 会 UnicodeEncodeError；
而仅把 stdout 改成 UTF-8 又会让 PowerShell 按 GBK 解码成乱码。
正解：同时把控制台代码页切到 65001，再让 stdout 用 UTF-8。
"""

from __future__ import annotations

import sys


def setup_console() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001
            pass
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
