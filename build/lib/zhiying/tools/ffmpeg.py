"""ffmpeg 可执行文件定位。

查找顺序：环境变量 ZHIYING_FFMPEG → 系统 PATH → venv 内 imageio-ffmpeg。
二进制不入仓（V0.1-PLAN 决策记录）。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def resolve_ffmpeg() -> str | None:
    """返回可用的 ffmpeg 可执行路径；找不到返回 None。"""
    # 1) 显式环境变量
    env = os.environ.get("ZHIYING_FFMPEG")
    if env and Path(env).exists():
        return env
    # 2) 系统 PATH
    which = shutil.which("ffmpeg")
    if which:
        return which
    # 3) venv 内 imageio-ffmpeg（二进制名带版本号，非标准 ffmpeg.exe）
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except ImportError:
        pass
    return None


if __name__ == "__main__":
    r = resolve_ffmpeg()
    print(r or "NOT FOUND")
    sys.exit(0 if r else 1)
