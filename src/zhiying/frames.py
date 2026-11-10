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

# 长视频性能参数（W7 实测：17分钟/204MB 视频逐帧解码 >10 分钟）
LONG_VIDEO_SEC = 600        # 阈值：10 分钟以上算长视频
SKIP_SHORT = 0              # <10min：逐帧检测
SKIP_MID = 2                # 10-30min：每 3 帧取 1
SKIP_LONG = 5               # 30min-1h：每 6 帧取 1
SKIP_VERY_LONG = 11         # >1h：每 12 帧取 1


def _pick_frame_skip(duration: float) -> int:
    """按时长选跳帧步长（跳帧不影响场景切点精度到秒级）。"""
    if duration <= 0:
        return 0
    if duration < LONG_VIDEO_SEC:
        return SKIP_SHORT
    if duration < 1800:
        return SKIP_MID
    if duration < 3600:
        return SKIP_LONG
    return SKIP_VERY_LONG


def _cap_max_frames(duration: float, requested: int) -> int:
    """按时长限制帧数：帧只用于画面理解，不必过密（控制 VLM 调用成本）。"""
    if duration <= 0:
        return requested
    # 约 1 帧/分钟，夹在 [6, requested] 之间
    by_dur = max(6, int(duration / 60))
    return min(requested, by_dur)


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

    duration = meta.duration or 0
    frame_skip = _pick_frame_skip(duration)
    max_frames = _cap_max_frames(duration, max_frames)

    # W7 实测结论：长视频的瓶颈是 OpenCV 逐帧解码（17min/204MB 即使跳帧仍 >12min），
    # 而非场景检测算法本身。超过阈值的视频直接放弃场景检测，改 ffmpeg 定点 seek 采样
    # （seek 不依赖解码前置帧，O(1) 级，全流程秒级完成）。
    if duration >= LONG_VIDEO_SEC:
        return extract_uniform_frames(video_id, max_frames=max_frames)

    video = open_video(str(src))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold))
    # scenedetect 0.7：检测循环在 SceneManager 上（0.6 才是 video.detect_scenes）
    # frame_skip：长视频跳帧检测（W7 性能优化，实测显著降低解码耗时）
    sm.detect_scenes(video, show_progress=False, frame_skip=frame_skip)
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
    max_frames = _cap_max_frames(duration, max_frames)

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
