"""关键帧提取与选段（PRD FR-104）。

两种提取模式：
- keyframe：PySceneDetect 场景切换检测，每个场景取代表帧（默认）
- uniform：均匀抽帧（fallback，场景检测无结果时用）

选段模式（agent）：LLM 分析完整文案后划重点时段（B4 只落帧与时段数据，
LLM 选段逻辑在 B5 与摘要一起实现，避免双倍 LLM 调用）。

产物：<data>/videos/<id>/frames/frames.json
  [{"frame_path", "ts", "scene_idx", "mode"}]
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from zhiying.download import load_meta
from zhiying.paths import frames_dir
from zhiying.tools.ffmpeg import resolve_ffmpeg

FRAME_FORMAT = "jpg"
FRAME_QUALITY = 2  # ffmpeg -q:v 2 高质量 jpeg


def extract_keyframes(video_id: str, max_frames: int = 60, threshold: float = 27.0) -> list[dict]:
    """PySceneDetect 场景切换检测，每场景取 1 帧。"""
    meta = load_meta(video_id)
    src = Path(meta.local_path) if meta and meta.local_path else None
    if not src or not src.exists():
        raise FileNotFoundError(f"视频 {video_id} 无源文件")

    out = frames_dir(video_id)
    out.mkdir(exist_ok=True)
    existing = _load_frames_index(video_id)
    if existing:
        return existing

    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(src))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold))
    # scenedetect 0.7：检测循环在 SceneManager 上（0.6 才是 video.detect_scenes）
    sm.detect_scenes(video, show_progress=False)
    scenes = sm.get_scene_list()
    if not scenes:
        # 无场景切换（静态画面类视频）→ 均匀抽帧
        return extract_uniform_frames(video_id, max_frames=max_frames)

    frames: list[dict] = []
    ff = resolve_ffmpeg()
    step = max(1, len(scenes) // max_frames) if len(scenes) > max_frames else 1
    idx = 0
    for i, (start, _end) in enumerate(scenes[::step]):
        ts = start.get_seconds()
        fp = out / f"scene_{idx:03d}.{FRAME_FORMAT}"
        cmd = [ff, "-y", "-ss", f"{ts:.2f}", "-i", str(src), "-frames:v", "1",
               "-q:v", str(FRAME_QUALITY), str(fp)]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode == 0 and fp.exists():
            frames.append({"frame_path": str(fp), "ts": round(ts, 2),
                           "scene_idx": i, "mode": "keyframe"})
        idx += 1
    _save_frames_index(video_id, frames)
    return frames


def extract_uniform_frames(video_id: str, max_frames: int = 40) -> list[dict]:
    """均匀抽帧 fallback。"""
    meta = load_meta(video_id)
    src = Path(meta.local_path) if meta and meta.local_path else None
    if not src or not src.exists():
        raise FileNotFoundError(f"视频 {video_id} 无源文件")
    duration = meta.duration or _probe_duration(src)
    if duration <= 0:
        raise RuntimeError(f"无法确定视频时长: {src}")

    out = frames_dir(video_id)
    out.mkdir(exist_ok=True)
    existing = _load_frames_index(video_id)
    if existing:
        return existing

    frames: list[dict] = []
    ff = resolve_ffmpeg()
    n = min(max_frames, max(3, int(duration // 15)))  # 至少 15s 一帧
    for i in range(n):
        ts = duration * (i + 0.5) / n
        fp = out / f"uniform_{i:03d}.{FRAME_FORMAT}"
        cmd = [ff, "-y", "-ss", f"{ts:.2f}", "-i", str(src), "-frames:v", "1",
               "-q:v", str(FRAME_QUALITY), str(fp)]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode == 0 and fp.exists():
            frames.append({"frame_path": str(fp), "ts": round(ts, 2),
                           "scene_idx": i, "mode": "uniform"})
    _save_frames_index(video_id, frames)
    return frames


def _probe_duration(src: Path) -> float:
    """WAV 用 wave；视频用 ffmpeg 解码估算（降级路径）。"""
    if src.suffix.lower() == ".wav":
        import wave

        try:
            with wave.open(str(src), "rb") as w:
                rate = w.getframerate()
                return w.getnframes() / rate if rate else 0.0
        except Exception:  # noqa: BLE001
            return 0.0
    return 0.0


def _load_frames_index(video_id: str) -> list[dict] | None:
    p = frames_dir(video_id) / "frames.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if data else None
        except Exception:  # noqa: BLE001
            return None
    return None


def _save_frames_index(video_id: str, frames: list[dict]) -> None:
    p = frames_dir(video_id) / "frames.json"
    p.write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8")
