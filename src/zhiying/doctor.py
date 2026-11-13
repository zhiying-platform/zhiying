"""zhiying doctor — 环境自检（B1 交付，PRD FR-306 / DR-19 雏形）。

逐项检查依赖、版本、目录，输出 ✅/❌ 与修复提示。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from zhiying import proc
from zhiying.console import setup_console
from zhiying.envkeys import getenv
from zhiying.tools.ffmpeg import resolve_ffmpeg

CHECKS = []


def check(name: str):
    """注册检查项的装饰器。"""

    def deco(fn):
        CHECKS.append((name, fn))
        return fn

    return deco


@check("python")
def check_python() -> tuple[bool, str]:
    v = sys.version_info
    ok = v >= (3, 10)
    detail = f"Python {v.major}.{v.minor}.{v.micro}"
    hint = "" if ok else "需要 Python 3.10+，请安装后重试"
    return ok, detail, hint  # type: ignore[return-value]


@check("ffmpeg")
def check_ffmpeg() -> tuple[bool, str]:
    exe = resolve_ffmpeg()
    if not exe:
        return False, "未找到 ffmpeg", "pip install imageio-ffmpeg 或安装系统 ffmpeg 后重试"
    try:
        out = proc.run(
            [exe, "-version"], capture_output=True, text=True, timeout=10, check=True
        ).stdout
        ver = out.splitlines()[0].strip()
        return True, ver, ""
    except Exception as e:  # noqa: BLE001
        return False, f"ffmpeg 调用失败: {e}", "检查 ffmpeg 可执行权限"


@check("yt-dlp")
def check_ytdlp() -> tuple[bool, str]:
    # 与 download._ytdlp_cmd 同口径：exe / PATH / python -m yt_dlp 三级回退
    # （安装版 --target 装包不生成 exe，模块方式是唯一可用路径）
    try:
        import yt_dlp  # noqa: F401

        mod_ok = True
    except ImportError:
        mod_ok = False
    exe = shutil.which("yt-dlp") or _venv_script("yt-dlp.exe") or _venv_script("yt-dlp")
    if not exe and not mod_ok:
        return False, "未找到 yt-dlp", "在 venv 中执行 pip install yt-dlp"
    if exe:
        try:
            out = proc.run(
                [exe, "--version"], capture_output=True, text=True, timeout=10, check=True
            ).stdout.strip()
            return True, f"yt-dlp {out}", ""
        except Exception as e:  # noqa: BLE001
            if not mod_ok:
                return False, f"yt-dlp 调用失败: {e}", "重装 yt-dlp"
    if mod_ok:
        try:
            out = proc.run(
                [sys.executable, "-m", "yt_dlp", "--version"],
                capture_output=True, text=True, timeout=15, check=True,
            ).stdout.strip()
            return True, f"yt-dlp {out}（模块方式）", ""
        except Exception as e:  # noqa: BLE001
            return False, f"yt-dlp 模块方式调用失败: {e}", "重装 yt-dlp"
    return False, "未找到 yt-dlp", "在 venv 中执行 pip install yt-dlp"


@check("pyyaml")
def check_pyyaml() -> tuple[bool, str]:
    try:
        import yaml  # noqa: F401

        return True, f"PyYAML {yaml.__version__}", ""
    except ImportError:
        return False, "未安装 PyYAML", "pip install pyyaml"


@check("longcat_key")
def check_longcat_key() -> tuple[bool, str]:
    key = getenv("LONGCAT_API_KEY")
    if key:
        return True, "LONGCAT_API_KEY 已配置", ""
    return (
        False,
        "未配置 LONGCAT_API_KEY",
        "画面识别（VLM）需要；V0.1 转写阶段可不配置，后续按提示设置",
    )


def _venv_script(name: str) -> str | None:
    """在当前 venv 的 Scripts/bin 目录找可执行文件。"""
    base = Path(sys.executable).parent
    p = base / name
    return str(p) if p.exists() else None


from pathlib import Path  # noqa: E402  (置于函数定义后以保持检查项紧凑)


def run_doctor() -> int:
    setup_console()
    print("知映 zhiying 环境自检")
    print("=" * 46)
    failed = 0
    for name, fn in CHECKS:
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001
            result = (False, f"检查异常: {e}", "")
        ok, detail, hint = (result + ("",))[:3] if len(result) == 2 else result
        mark = "✅" if ok else "❌"
        print(f"{mark} {name:<12} {detail}")
        if not ok:
            failed += 1
            if hint:
                print(f"   └─ 修复提示: {hint}")
    print("=" * 46)
    if failed:
        print(f"{failed} 项未通过；按修复提示处理后重跑。")
        return 1
    print("全部通过，环境就绪。")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_doctor())
