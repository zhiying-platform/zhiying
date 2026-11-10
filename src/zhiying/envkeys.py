"""配置读取：进程环境 > 项目 .env 文件 > Windows 用户注册表。

- 进程环境：最高优先级，允许临时覆盖（CI/命令行注入）
- .env 文件：项目级配置（仓库根的 .env，已 gitignore），load 一次后缓存
- Windows 注册表：用户级兜底（setx 写入，网关等长驻进程不感知进程环境变量时生效）

不引入 python-dotenv 依赖，轻量解析支持：注释、export 前缀、单/双引号、行内空白。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ENV_CACHE: dict[str, str] | None = None


def _dotenv_path() -> Path:
    # envkeys.py 位于 <repo>/src/zhiying/envkeys.py，parents[2] = <repo>
    return Path(__file__).resolve().parents[2] / ".env"


def _load_dotenv() -> dict[str, str]:
    global _ENV_CACHE
    if _ENV_CACHE is not None:
        return _ENV_CACHE
    data: dict[str, str] = {}
    p = _dotenv_path()
    if not p.exists():
        _ENV_CACHE = data
        return data
    try:
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            # 去引号
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            # 去掉行内注释（仅当 # 前有空白，且值未被引号包裹时）
            elif " #" in v:
                v = v.split(" #", 1)[0].strip()
            if k:
                data[k] = v
    except OSError:
        pass
    _ENV_CACHE = data
    return data


def reload_dotenv() -> None:
    """修改 .env 后手动刷新缓存。"""
    global _ENV_CACHE
    _ENV_CACHE = None


def getenv(name: str) -> str | None:
    # 1) 进程环境
    v = os.environ.get(name)
    if v:
        return v
    # 2) .env 文件
    v = _load_dotenv().get(name)
    if v:
        return v
    # 3) Windows 用户注册表
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                v, _ = winreg.QueryValueEx(k, name)
                return v or None
        except OSError:
            return None
    return None
