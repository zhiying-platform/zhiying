"""子进程调用辅助：Windows 下统一抑制控制台窗口弹出。

背景（实测 bug）：安装版用 pythonw 运行（无控制台），管道再 `subprocess` 拉起
python.exe / yt-dlp.exe / ffmpeg.exe 等控制台程序时，系统会给每个子进程新建控制台窗口，
表现为处理视频时「黑窗一闪」；若子进程存活时间长（如整条管道），窗口会一直存在。

解决：Windows 下所有子进程统一带 CREATE_NO_WINDOW 标志。
"""

from __future__ import annotations

import subprocess
import sys

# CREATE_NO_WINDOW：子进程不创建控制台窗口
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# CREATE_NO_WINDOW：子进程不创建控制台窗口
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
# DETACHED_PROCESS：子进程完全脱离父控制台（无控制台可继承时使用）
_DETACHED_PROCESS = 0x00000008 if sys.platform == "win32" else 0


def no_window_flags(extra: int = 0) -> int:
    """返回抑制窗口的 creationflags（非 Windows 返回 extra）。

    注意：CREATE_NO_WINDOW 与 DETACHED_PROCESS 在 Windows 上互斥，
    同时置位属未定义行为。若调用方显式要求 DETACHED_PROCESS，则不再叠加
    CREATE_NO_WINDOW——DETACHED 的子进程本身就没有控制台，不会弹窗。
    """
    if extra & _DETACHED_PROCESS:
        return extra
    return extra | _CREATE_NO_WINDOW


def run(cmd, **kwargs):  # noqa: ANN001, ANN201
    """subprocess.run 的包装：Windows 下自动抑制窗口。

    调用方可显式传入 creationflags，会被合并。
    """
    flags = kwargs.pop("creationflags", 0) | no_window_flags()
    return subprocess.run(cmd, creationflags=flags, **kwargs)


def popen(cmd, **kwargs):  # noqa: ANN001, ANN201
    """subprocess.Popen 的包装：Windows 下自动抑制窗口。"""
    flags = kwargs.pop("creationflags", 0) | no_window_flags()
    return subprocess.Popen(cmd, creationflags=flags, **kwargs)
