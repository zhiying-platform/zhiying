"""环境变量读取：进程环境优先，Windows 用户注册表兜底。

网关等长驻进程不会感知新设置的用户级环境变量；本项目 CLI 由各种父进程
拉起，统一走此模块读取，保证用户级配置（setx / 系统设置面板写入）即时生效。
"""

from __future__ import annotations

import os
import sys


def getenv(name: str) -> str | None:
    """返回环境变量值；进程环境缺失时查 Windows 用户注册表。"""
    v = os.environ.get(name)
    if v:
        return v
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                v, _ = winreg.QueryValueEx(k, name)
                return v or None
        except OSError:
            return None
    return None
