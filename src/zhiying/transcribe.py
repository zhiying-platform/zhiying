"""转写管道（PRD FR-103 三级降级）。

第一级：平台字幕（B站 cc/AI 字幕，经 yt-dlp 获取；danmaku 弹幕不算语音转写）
第二级：SenseVoiceSmall（硅基流动 API，SILICONFLOW_API_KEY）
第三级：本地 Whisper（faster-whisper，C+A 方案拍板后改为真实实现）

产物：<data>/videos/<id>/transcript/transcript.jsonl
每行: {"start_ts": float, "end_ts": float, "text": str, "origin": "platform_subtitle"|"sensevoice"|"whisper"}
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from zhiying import proc
from zhiying.console import setup_console  # noqa: F401  (CLI 侧调用前统一设置)
from zhiying.download import load_meta
from zhiying.envkeys import getenv
from zhiying.paths import audio_dir, transcript_dir
from zhiying.tools.ffmpeg import resolve_ffmpeg

PLATFORM_SUB_LANGS = ("ai-zh", "zh-Hans", "zh-CN", "zh")

# HuggingFace 模型下载端点：国内默认走镜像（HF 直连常被阻断）
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


# ---------------------------------------------------------------- 音频抽取


def extract_audio(video_id: str, src: Path | None = None) -> Path:
    """从源视频抽取 16k 单声道 wav（语音识别标准输入）。"""
    meta = load_meta(video_id)
    src = src or (Path(meta.local_path) if meta and meta.local_path else None)
    if not src or not src.exists():
        raise FileNotFoundError(f"视频 {video_id} 无源文件，先执行 ingest")
    out = audio_dir(video_id) / "audio.wav"
    if out.exists() and out.stat().st_size > 44:  # 幂等：已有有效音频
        return out
    ff = resolve_ffmpeg()
    cmd = [ff, "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(out)]
    res = proc.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0 or not out.exists():
        raise RuntimeError(f"音频抽取失败: {(res.stderr or '')[-300:]}")
    return out


# ------------------------------------------------------------ 第一级：平台字幕


def fetch_platform_subtitle(video_id: str, src_url: str | None = None) -> Path | None:
    """尝试抓平台字幕（非弹幕）。成功返回转写 jsonl 路径，失败返回 None。"""
    meta = load_meta(video_id)
    url = src_url or (meta.source if meta and meta.source_type != "local" else None)
    if not url:
        return None
    out_dir = transcript_dir(video_id)
    exe = str(Path(__import__("sys").executable).parent / "yt-dlp.exe")
    cmd = [
        exe, "--no-playlist", "--skip-download",
        "--write-subs", "--sub-langs", ",".join(PLATFORM_SUB_LANGS),
        "--sub-format", "json3/srt/vtt/best",
        "-o", str(out_dir / "sub"),
        url,
    ]
    res = proc.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    # 找下载到的字幕文件（排除 danmaku）
    for f in sorted(out_dir.glob("sub*")):
        if f.suffix.lower() in {".json3", ".json", ".srt", ".vtt"} and "danmaku" not in f.name.lower():
            return _convert_subtitle_to_jsonl(f, video_id)
    return None


def _convert_subtitle_to_jsonl(sub_file: Path, video_id: str) -> Path:
    """把 json3/srt/vtt 统一转成 transcript.jsonl。"""
    out = transcript_dir(video_id) / "transcript.jsonl"
    entries: list[dict] = []
    if sub_file.suffix in {".json3", ".json"}:
        data = json.loads(sub_file.read_text(encoding="utf-8"))
        for ev in data.get("events", []):
            segs = "".join(s.get("utf8", "") for s in ev.get("segs", [])).strip()
            if not segs:
                continue
            start = ev.get("startTs", ev.get("start", 0))
            dur = ev.get("duration", ev.get("dDurationMs", 0)) / (1000 if ev.get("startTs") is not None else 1)
            entries.append({"start_ts": float(start), "end_ts": float(start) + float(dur), "text": segs,
                            "origin": "platform_subtitle"})
    elif sub_file.suffix == ".srt":
        entries = _parse_srt(sub_file)
    elif sub_file.suffix == ".vtt":
        entries = _parse_vtt(sub_file)
    if not entries:
        return None  # type: ignore[return-value]
    with out.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return out


def _ts_to_seconds(ts: str) -> float:
    h, m, rest = ts.split(":")
    s = rest.replace(",", ".").replace(".", ".")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _parse_srt(p: Path) -> list[dict]:
    entries, block = [], []
    for line in p.read_text(encoding="utf-8").splitlines() + [""]:
        if line.strip():
            block.append(line)
        elif block:
            if len(block) >= 3 and "-->" in block[1]:
                a, b = block[1].split("-->")
                text = " ".join(x.strip() for x in block[2:] if x.strip())
                if text:
                    entries.append({"start_ts": _ts_to_seconds(a.strip()), "end_ts": _ts_to_seconds(b.strip()),
                                    "text": text, "origin": "platform_subtitle"})
            block = []
    return entries


def _parse_vtt(p: Path) -> list[dict]:
    entries, block = [], []
    for line in p.read_text(encoding="utf-8").splitlines() + [""]:
        if line.strip():
            block.append(line)
        elif block:
            tl = next((x for x in block if "-->" in x), None)
            if tl:
                a, b = tl.split("-->")
                text = " ".join(x.strip() for x in block[block.index(tl) + 1:] if x.strip() and not x.startswith(("WEBVTT", "Kind:", "Language:")))
                if text:
                    entries.append({"start_ts": _ts_to_seconds(a.strip().split(" ")[0]), "end_ts": _ts_to_seconds(b.strip().split(" ")[0]),
                                    "text": text, "origin": "platform_subtitle"})
            block = []
    return entries


# ------------------------------------------------------ 第二级：SenseVoice（硅基流动）


def _audio_duration_seconds(audio: Path) -> float:
    """读取 WAV 时长（标准库 wave，零外部依赖）。"""
    import wave

    try:
        with wave.open(str(audio), "rb") as w:
            frames, rate = w.getnframes(), w.getframerate()
            return frames / rate if rate else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _key_sanity_warning(key: str) -> str | None:
    """预检 Key 是否疑似打码/截断，返回警告文案或 None。"""
    if any(ord(c) > 126 for c in key):
        return "含非 ASCII 字符（疑似复制的控制台打码显示，如带省略号 …）"
    if not key.startswith("sk-"):
        return "硅基流动 Key 通常以 sk- 开头，当前值疑似不完整"
    if len(key) < 20:
        return f"长度仅 {len(key)} 字符，疑似被截断"
    return None


def sensevoice_transcribe(video_id: str) -> Path | None:
    """调硅基流动 SenseVoiceSmall 转写音频。需要 SILICONFLOW_API_KEY。

    大音频按 60s 切片并发送（免费档单文件大小受限），逐片落 jsonl。
    """
    import os

    import requests

    key = getenv("SILICONFLOW_API_KEY")
    if not key:
        print("⚠ 未配置 SILICONFLOW_API_KEY，无法执行第二级转写")
        print("  └─ 配置: https://cloud.siliconflow.cn 创建 API Key 后")
        print("          set SILICONFLOW_API_KEY=sk-... (或写入系统环境变量)")
        return None
    key = key.strip()
    warn = _key_sanity_warning(key)
    if warn:
        print(f"⚠ SILICONFLOW_API_KEY 疑似无效：{warn}")
        print("  └─ 请提供完整 Key（控制台打码显示不可用），将自动降级到本地 Whisper")
        return None

    audio = audio_dir(video_id) / "audio.wav"
    if not audio.exists():
        extract_audio(video_id)

    duration = _audio_duration_seconds(audio)
    if duration <= 0:
        print("⚠ 无法读取音频时长，放弃第二级转写")
        return None

    seg_dir = audio_dir(video_id) / "segs"
    seg_dir.mkdir(exist_ok=True)
    ff = resolve_ffmpeg()
    # 60s 切片
    slice_len = 60
    out = transcript_dir(video_id) / "transcript.jsonl"
    entries: list[dict] = []
    idx = 0
    max_idx = int(duration / slice_len) + 1
    while idx < max_idx:
        seg = seg_dir / f"seg_{idx:03d}.wav"
        cmd = [ff, "-y", "-i", str(audio), "-ss", str(idx * slice_len), "-t", str(slice_len),
               "-ac", "1", "-ar", "16000", str(seg)]
        p = proc.run(cmd, capture_output=True, text=True)
        if p.returncode != 0 or not seg.exists() or seg.stat().st_size <= 1024:
            break
        try:
            with seg.open("rb") as f:
                r = requests.post(
                    "https://api.siliconflow.cn/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (seg.name, f, "audio/wav")},
                    data={"model": "FunAudioLLM/SenseVoiceSmall"},
                    timeout=120,
                )
        except Exception as e:  # noqa: BLE001  网络/编码异常一律降级，不中断管道
            print(f"⚠ 片段 {idx} 请求异常: {e}")
            seg.unlink(missing_ok=True)
            break  # 出现请求异常直接结束第二级，交给 Whisper 保底
        if r.status_code != 200:
            print(f"⚠ 片段 {idx} 转写失败 HTTP {r.status_code}: {r.text[:200]}")
        else:
            text = (r.json().get("text") or "").strip()
            if text:
                entries.append({"start_ts": float(idx * slice_len),
                                "end_ts": float((idx + 1) * slice_len),
                                "text": text, "origin": "sensevoice"})
        seg.unlink(missing_ok=True)
        idx += 1
    if not entries:
        return None
    with out.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return out


# ------------------------------------------ 第三级：本地 Whisper（C 方案保底）


def whisper_transcribe(video_id: str) -> Path | None:
    """本地 faster-whisper 保底转写（可选组件）。

    首次使用自动下载 small 模型（约 500MB）；未安装时返回 None 并给安装提示，
    降级编排自动结束（前两级：平台字幕/SenseVoice 不受影响）。
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("⚠ 本地 Whisper 未安装（可选组件）")
        print("  └─ 需要离线转写保底时安装: pip install faster-whisper")
        return None

    audio = audio_dir(video_id) / "audio.wav"
    if not audio.exists():
        extract_audio(video_id)
    out = transcript_dir(video_id) / "transcript.jsonl"
    model_name = os.environ.get("ZHIYING_WHISPER_MODEL", "small")
    # 实测调优（2026-11-09）：VAD 对背景音乐重的视频会过滤掉全部语音（0 段），
    # 保底路径默认关闭；beam_size=1 相比 5 提速约 5 倍，保底场景质量可接受。
    vad = os.environ.get("ZHIYING_WHISPER_VAD", "0") == "1"
    beam = int(os.environ.get("ZHIYING_WHISPER_BEAM", "1"))
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(audio), language="zh", beam_size=beam, vad_filter=vad)
    entries = []
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            entries.append({"start_ts": float(seg.start), "end_ts": float(seg.end),
                            "text": text, "origin": f"whisper_{model_name}"})
    if not entries:
        return None
    with out.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return out


# ------------------------------------------------------------- 管道入口（降级编排）


def transcribe(video_id: str) -> dict:
    """三级降级编排，返回 {"level": ..., "path": ...}。"""
    # 幂等：已有转写产物直接复用（retry/重跑不重复调转写 API）
    existing = transcript_dir(video_id) / "transcript.jsonl"
    if existing.exists() and existing.stat().st_size > 0:
        return {"level": "cached", "path": str(existing)}

    meta = load_meta(video_id)
    reasons: list[str] = []
    # 第一级：平台字幕
    sub = fetch_platform_subtitle(video_id)
    if sub:
        return {"level": "platform_subtitle", "path": str(sub)}
    if meta and meta.source_type != "local" and meta.source:
        reasons.append("平台字幕：源视频未找到可用字幕")
    else:
        reasons.append("平台字幕：本地视频无源 URL，不可用")
    # 第二级：SenseVoice
    if not getenv("SILICONFLOW_API_KEY"):
        reasons.append("SenseVoice：未配置 SILICONFLOW_API_KEY（网页「设置」页可配置）")
    else:
        sv = sensevoice_transcribe(video_id)
        if sv:
            return {"level": "sensevoice", "path": str(sv)}
        reasons.append("SenseVoice：调用失败（Key 无效/网络异常，详见任务目录 pipeline.log）")
    # 第三级：本地 Whisper 保底（C+A 方案，2026-11-09 拍板）
    print("ℹ 平台字幕与 SenseVoice 均不可用，切换本地 Whisper 保底")
    wh = whisper_transcribe(video_id)
    if wh:
        return {"level": "whisper_small", "path": str(wh)}
    try:
        import faster_whisper  # noqa: F401

        reasons.append("本地 Whisper：音频中未识别到有效语音段")
    except ImportError:
        reasons.append("本地 Whisper：未安装（可选组件）")
    return {"level": "failed", "path": None, "note": "全部转写通道失败", "reasons": reasons}
