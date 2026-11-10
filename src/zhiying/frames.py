"""关键帧提取与选段（PRD FR-104）。

三种提取模式：
- keyframe：PySceneDetect 场景切换检测，每个场景取代表帧（短/中视频默认；precise 档强制）
- uniform：ffmpeg 定点 seek 均匀抽帧（fast 档长视频用；无场景切换时 fallback）

精度两档（DR-22，用户交互指定）：
- fast（默认）：≥10min 视频走 ffmpeg seek 采样（秒级；17min 实测 10.8s）
- precise：无视时长强制逐帧场景检测（长视频 10min+；镜头切换快的视频切点更准）

产物：<data>/videos/<id>/frames/frames.json
  {"precision": "...", "frames": [{"frame_path", "ts", "scene_idx", "mode"}]}
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

# 长视频阈值（W7 实测：17min/204MB 逐帧解码 >10min，故 fast 档改 seek 采样）
LONG_VIDEO_SEC = 600

# 中长视频跳帧步长（precise 档与短/中视频用；减少检测计算量，切点精度到秒级）
SKIP_MID = 2        # 10-30min：每 3 帧取 1
SKIP_LONG = 5       # 30min-1h：每 6 帧取 1
SKIP_VERY_LONG = 11 # >1h：每 12 帧取 1


def _pick_frame_skip(duration: float) -> int:
    """按时长选跳帧步长（仅 precise 档与 <10min 视频的场景检测使用）。"""
    if duration <= 0:
        return 0
    if duration < LONG_VIDEO_SEC:
        return 0
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


def extract_keyframes(
    video_id: str,
    max_frames: int = 60,
    threshold: float = 27.0,
    precision: str = "fast",
) -> list[dict]:
    """关键帧提取（DR-22 精度两档）。

    precision：
      fast（默认）：≥10min 走 ffmpeg seek 均匀采样（秒级）
      precise：无视时长强制 PySceneDetect 场景检测（长视频 10min+，切点更准）
    """
    meta = load_meta(video_id)
    src = Path(meta.local_path) if meta and meta.local_path else None
    if not src or not src.exists():
        raise FileNotFoundError(f"视频 {video_id} 无源文件")

    # 缓存感知精度：切换精度后自动失效重提
    cached = _load_frames_index(video_id)
    if cached and cached.get("precision") == precision:
        return cached["frames"]

    out = frames_dir(video_id)
    out.mkdir(exist_ok=True)

    duration = meta.duration or 0
    max_frames = _cap_max_frames(duration, max_frames)

    # fast 档长视频：ffmpeg seek 均匀采样（绕开逐帧解码瓶颈，W7 实测 17min→11s）
    if precision == "fast" and duration >= LONG_VIDEO_SEC:
        return extract_uniform_frames(video_id, max_frames=max_frames, precision=precision)

    # precise 档（或短/中视频）：PySceneDetect 场景检测
    frame_skip = _pick_frame_skip(duration)
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(src))
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=threshold))
    # scenedetect 0.7：检测循环在 SceneManager 上
    sm.detect_scenes(video, show_progress=False, frame_skip=frame_skip)
    scenes = sm.get_scene_list()
    if not scenes:
        # 无场景切换（静态画面类视频）→ 均匀抽帧
        return extract_uniform_frames(video_id, max_frames=max_frames, precision=precision)

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
    _save_frames_index(video_id, frames, precision)
    return frames


def extract_uniform_frames(video_id: str, max_frames: int = 40, precision: str = "fast") -> list[dict]:
    """均匀抽帧（ffmpeg 定点 seek，O(1) 级）。"""
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
    cached = _load_frames_index(video_id)
    if cached and cached.get("precision") == precision:
        return cached["frames"]

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
    _save_frames_index(video_id, frames, precision)
    return frames


def _probe_duration(src: Path) -> float:
    """WAV 用 wave；视频用 OpenCV（scenedetect 已依赖 cv2，零新增依赖）。"""
    if src.suffix.lower() == ".wav":
        import wave

        try:
            with wave.open(str(src), "rb") as w:
                rate = w.getframerate()
                return w.getnframes() / rate if rate else 0.0
        except Exception:  # noqa: BLE001
            return 0.0
    # 视频：cv2 读帧数/帧率（本地上传视频无 info.json，duration 需探针）
    try:
        import cv2

        cap = cv2.VideoCapture(str(src))
        try:
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            if frames and fps and fps > 0:
                return float(frames) / float(fps)
        finally:
            cap.release()
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def _load_frames_index(video_id: str) -> dict | None:
    """读帧索引；返回 {"precision", "frames"} 或 None（兼容旧列表格式）。"""
    p = frames_dir(video_id) / "frames.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"precision": "fast", "frames": data}  # 旧格式兼容
    return None


def _save_frames_index(video_id: str, frames: list[dict], precision: str) -> None:
    p = frames_dir(video_id) / "frames.json"
    payload = {"precision": precision, "frames": frames}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
