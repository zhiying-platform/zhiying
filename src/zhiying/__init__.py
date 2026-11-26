"""知映 zhiying — 视频知识库 CLI。

将收藏的视频转为可检索、可问答、可溯源到时间点的知识库。
版本号单一来源：仓库根 VERSION 文件（安装器、CI、Info.plist 均读取它）。
"""

from pathlib import Path


def _read_version() -> str:
    """优先读仓库根 VERSION（开发/打包环境），否则回退到内置值（已安装环境）。"""
    try:
        vf = Path(__file__).resolve().parents[2] / "VERSION"
        if vf.is_file():
            return vf.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        pass
    return "1.4.0"


__version__ = _read_version()
