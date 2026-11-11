"""下载器封装（PRD FR-101 / FR-102）。

职责：把 URL 或本地文件统一落到 <data>/videos/<video_id>/source/。
关键设计：
- 幂等：同 video_id 已有完整源文件则直接复用（FR-203 雏形）
- 断点续传：交由 yt-dlp 原生 --continue（默认行为），只重下未完成部分
- 多级缓存：本地文件直通；URL 先查已有产物再下载
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from zhiying.paths import meta_path, source_dir
from zhiying.tools.ffmpeg import resolve_ffmpeg

# B站 / YouTube 常见 ID 提取
_BILI_BV = re.compile(r"(BV[0-9A-Za-z]{10})")
_BILI_AV = re.compile(r"av(\d+)", re.I)
_YT_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})")

# 平台识别表（DR-38：扩充一级缺口——国内常见平台 + 通用外网站点）
# 匹配键 → (source_type, video_id 提取正则或 None=用 URL 哈希)
_PLATFORMS = [
    ("bilibili.com", "bilibili", _BILI_BV),
    ("b23.tv", "bilibili", _BILI_BV),
    ("youtube.com", "youtube", _YT_ID),
    ("youtu.be", "youtube", _YT_ID),
    ("douyin.com", "douyin", re.compile(r"/video/(\d+)")),
    ("v.douyin.com", "douyin", None),
    ("ixigua.com", "xigua", re.compile(r"(?:video/|)(\d+)")),
    ("weibo.com", "weibo", re.compile(r"show/([0-9]+:[0-9]+)")),
    ("xiaohongshu.com", "xiaohongshu", re.compile(r"/([0-9a-f]{24})")),
    ("xhslink.com", "xiaohongshu", None),
    ("twitter.com", "twitter", re.compile(r"status/(\d+)")),
    ("x.com", "twitter", re.compile(r"status/(\d+)")),
    ("vimeo.com", "vimeo", re.compile(r"/(\d+)")),
    ("twitch.tv", "twitch", re.compile(r"videos/(\d+)")),
]


@dataclass
class VideoMeta:
    video_id: str
    source_type: str  # bilibili | youtube | local | unknown
    source: str
    title: str = ""
    duration: float = 0.0
    uploader: str = ""
    width: int = 0
    height: int = 0
    filesize: int = 0
    local_path: str = ""
    downloaded_at: str = ""
    status: str = "pending"  # pending|downloading|done|failed
    error: str = ""
    extra: dict = field(default_factory=dict)
    content_hash: str = ""  # 文件级 SHA256（上传去重，DR-23）


def detect_source(src: str) -> tuple[str, str]:
    """返回 (source_type, video_id)。

    DR-38：识别表覆盖国内常见平台 + 通用外网站点；未命中平台时若 src 为
    http(s) URL，仍标记 unknown 并交给 yt-dlp 通用提取器处理（下载层兼容面
    远大于识别层），ID 用 URL 哈希保证去重。
    """
    p = Path(src)
    if p.exists():
        # 本地文件：ID 用文件名+大小哈希，稳定且可复现
        h = hashlib.sha1(f"{p.name}:{p.stat().st_size}".encode()).hexdigest()[:12]
        return "local", f"local-{h}"
    for key, stype, pat in _PLATFORMS:
        if key in src:
            vid = None
            if pat is not None:
                m = pat.search(src)
                if m:
                    vid = m.group(1)
            if not vid:
                vid = hashlib.sha1(src.encode()).hexdigest()[:12]
            # B站 av 号归一化标记
            if stype == "bilibili" and vid.lower().startswith("av"):
                vid = "BV" + vid
            return stype, vid
    if src.lower().startswith(("http://", "https://")):
        # 未识别平台的 URL：交给 yt-dlp 通用提取器尝试
        return "unknown", hashlib.sha1(src.encode()).hexdigest()[:12]
    return "unknown", hashlib.sha1(src.encode()).hexdigest()[:12]


def find_existing_source(video_id: str) -> Path | None:
    """已有完整源文件则返回路径（多级缓存第一级）。"""
    d = source_dir(video_id)
    for f in d.iterdir() if d.exists() else []:
        if f.is_file() and f.suffix.lower() in {".mp4", ".mkv", ".webm", ".flv", ".mov", ".m4a", ".mp3", ".wav"}:
            if f.stat().st_size > 0:
                return f
    return None


def _run_ytdlp(url: str, out_dir: Path, quality: str = "1080") -> tuple[int, str]:
    """调用 yt-dlp 下载；返回 (returncode, stderr 尾部)。"""
    exe = _ytdlp_exe()
    # 格式选择：优先约束清晰度，但必须有逐级回退（竖屏/低清源会匹配不到）
    # 链路：限定高度 → 最佳可用 → 最差可用，保证任何视频都能落下一个文件
    if quality == "best":
        fmt = "bv*+ba/b"
    else:
        fmt = f"bv*[height<={quality}]+ba/b[height<={quality}]/bv*+ba/b/worst"
    cmd = [
        exe,
        "--no-playlist",
        "--continue",          # 断点续传
        "--newline",           # 逐行进度，便于日志
        "--socket-timeout", "20",
        "--retries", "3",
        "--no-mtime",
        "--ffmpeg-location", resolve_ffmpeg() or "ffmpeg",  # 合并音视频必需
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", str(out_dir / "%(title).80s.%(ext)s"),
        "--print", "after_move:filepath",
        "--write-info-json",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=_ytdlp_env())
    tail = "\n".join((proc.stderr or "").strip().splitlines()[-6:])
    printed = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().endswith((".mp4", ".mkv", ".webm", ".flv"))]
    return proc.returncode, printed[-1] if printed else tail


def _ytdlp_env() -> dict:
    """注入代理环境变量（ZHIYING_PROXY 或系统 HTTPS_PROXY 均可）。

    网络受限环境下 YouTube 等站点需代理；未配置时不干预。
    """
    env = os.environ.copy()
    proxy = os.environ.get("ZHIYING_PROXY")
    if proxy:
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            env[k] = proxy
    elif os.environ.get("HTTPS_PROXY"):
        pass  # 已由系统环境提供
    else:
        # 本地常见代理端口探测（不改变无代理环境的行为）
        for cand in ("http://127.0.0.1:7890", "http://127.0.0.1:10809"):
            host = cand.split("//")[1].split(":")[0]
            port = int(cand.rsplit(":", 1)[1])
            try:
                with socket.create_connection((host, port), timeout=0.3):
                    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
                        env[k] = cand
                    break
            except OSError:
                continue
    return env


def _ytdlp_exe() -> str:
    base = Path(sys.executable).parent
    for name in ("yt-dlp.exe", "yt-dlp"):
        p = base / name
        if p.exists():
            return str(p)
    w = shutil.which("yt-dlp")
    if w:
        return w
    raise RuntimeError("未找到 yt-dlp，请在 venv 中安装：pip install yt-dlp")


def _read_info_json(out_dir: Path) -> dict:
    for f in out_dir.glob("*.info.json"):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return {}


def download(src: str, quality: str = "1080", force: bool = False) -> VideoMeta:
    """统一入口：本地文件拷入 / URL 下载。返回 VideoMeta 并落 meta.json。"""
    source_type, vid = detect_source(src)
    meta = VideoMeta(video_id=vid, source_type=source_type, source=src)
    mp = meta_path(vid)
    existing = find_existing_source(vid) if not force else None

    if existing:
        # 缓存命中：保留首次下载保存的元信息（标题/时长等），只刷新路径与状态
        prev = load_meta(vid)
        if prev is None:
            prev = VideoMeta(video_id=vid, source_type=source_type, source=src)
        prev.local_path = str(existing)
        prev.filesize = existing.stat().st_size
        prev.status = "done"
        prev.downloaded_at = prev.downloaded_at or _now()
        _save_meta(mp, prev)
        return prev

    if source_type == "local":
        p = Path(src)
        dst = source_dir(vid) / p.name
        shutil.copy2(p, dst)
        meta.local_path, meta.filesize, meta.status = str(dst), dst.stat().st_size, "done"
        meta.content_hash = file_sha256(dst)  # 上传去重（DR-23）
        meta.downloaded_at = _now()
        _save_meta(mp, meta)
        return meta

    # URL 下载
    meta.status = "downloading"
    _save_meta(mp, meta)
    out = source_dir(vid)
    rc, msg = _run_ytdlp(src, out, quality)
    if rc != 0:
        meta.status, meta.error = "failed", msg
        _save_meta(mp, meta)
        return meta

    info = _read_info_json(out)
    found = find_existing_source(vid)
    meta.local_path = str(found) if found else ""
    meta.filesize = found.stat().st_size if found else 0
    meta.title = info.get("title", "") or (found.stem if found else "")
    meta.duration = float(info.get("duration") or 0)
    meta.uploader = info.get("uploader", "") or info.get("channel", "")
    meta.status = "done" if found else "failed"
    if not found:
        meta.error = msg or "下载完成但未找到产物"
    meta.downloaded_at = _now()
    _save_meta(mp, meta)
    return meta


def _save_meta(path: Path, meta: VideoMeta) -> None:
    path.write_text(json.dumps(asdict(meta), ensure_ascii=False, indent=2), encoding="utf-8")


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """文件级 SHA256（流式分块，支持大文件；上传去重用，DR-23）。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def backfill_meta(video_id: str) -> VideoMeta | None:
    """用 info.json 回填缺失的元信息（标题/时长/UP 主），修复历史损坏数据。"""
    meta = load_meta(video_id)
    if not meta:
        return None
    info = _read_info_json(source_dir(video_id))
    if not info:
        return meta
    meta.title = meta.title or info.get("title", "")
    meta.duration = meta.duration or float(info.get("duration") or 0)
    meta.uploader = meta.uploader or info.get("uploader", "") or info.get("channel", "")
    _save_meta(meta_path(video_id), meta)
    return meta


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_meta(video_id: str) -> VideoMeta | None:
    p = meta_path(video_id)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return VideoMeta(**{k: v for k, v in data.items() if k in VideoMeta.__dataclass_fields__})
