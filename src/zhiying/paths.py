"""数据目录与路径约定（多级缓存结构）。

目录布局（仓库外，避免大文件入 git）：

    <data_root>/
      videos/<video_id>/
        meta.json          # 视频元信息
        source/            # 下载的原视频（断点续传目标）
        audio/             # 抽取的音频（S3 用）
        frames/            # 关键帧（S4 用）
        transcript/        # 转写产物（S3/S6 用）
      cache/               # 通用缓存（字幕、API 响应）

data_root 优先级：ZHIYING_DATA 环境变量 → <repo>/data → ~/.zhiying/data
"""

from __future__ import annotations

import os
from pathlib import Path


def data_root() -> Path:
    """数据根目录（DR-27 用户可配置）。

    优先级：进程环境 ZHIYING_DATA → .env 文件同名项 → <repo>/data 默认值。
    切换路径后历史数据不会自动迁移（.env.example 有说明）。
    """
    from zhiying.envkeys import getenv

    env = os.environ.get("ZHIYING_DATA") or getenv("ZHIYING_DATA")
    if env:
        p = Path(env).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p
    # 默认放在仓库同级的 data/（已被 .gitignore 忽略）
    repo = Path(__file__).resolve().parents[2]
    p = repo / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def video_dir(video_id: str) -> Path:
    p = data_root() / "videos" / video_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def source_dir(video_id: str) -> Path:
    p = video_dir(video_id) / "source"
    p.mkdir(parents=True, exist_ok=True)
    return p


def audio_dir(video_id: str) -> Path:
    p = video_dir(video_id) / "audio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def frames_dir(video_id: str) -> Path:
    p = video_dir(video_id) / "frames"
    p.mkdir(parents=True, exist_ok=True)
    return p


def transcript_dir(video_id: str) -> Path:
    p = video_dir(video_id) / "transcript"
    p.mkdir(parents=True, exist_ok=True)
    return p


def meta_path(video_id: str) -> Path:
    return video_dir(video_id) / "meta.json"
