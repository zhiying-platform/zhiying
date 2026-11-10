"""多模态文案组装与结构化摘要（PRD FR-106 / FR-107，产物 A1 / A3）。

流程：
  transcript.jsonl（语音）+ frames.json（画面帧）
    → VLM 逐帧描述（缓存 descriptions.json）
    → 时间轴对齐 → A1 双形态（multimodal_transcript.md + transcript.multimodal.jsonl）
    → 文本 LLM 摘要 → A3（summary.json：摘要 + 主题标签 + 可溯源要点）

A1 双形态由同一数据源生成，不允许手工分叉（PRD §5.4）。
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
from pathlib import Path

import requests

from zhiying.download import load_meta
from zhiying.envkeys import getenv
from zhiying.frames import extract_keyframes
from zhiying.paths import frames_dir, transcript_dir, video_dir
from zhiying.vlm import VLMError, describe_frame

FRAME_MATCH_WINDOW = 60.0  # 帧与语音段的匹配窗口（秒）


# --------------------------------------------------------------- 帧描述（带缓存）


def describe_frames(video_id: str, max_frames: int = 20, force: bool = False) -> list[dict]:
    """对所有关键帧调 VLM，结果缓存到 frames/descriptions.json。"""
    cache = frames_dir(video_id) / "descriptions.json"
    if cache.exists() and not force:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data:
                return data
        except Exception:  # noqa: BLE001
            pass

    frames = extract_keyframes(video_id, max_frames=max_frames)
    if not frames:
        return []

    def work(f: dict) -> dict:
        try:
            desc = describe_frame(Path(f["frame_path"]))
        except VLMError as e:
            desc = f"[VLM 失败: {e}]"
        return {**f, "description": desc}

    out: list[dict] = []
    # 并发 4：兼顾速度与免费档速率限制
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for item in ex.map(work, frames):
            out.append(item)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ------------------------------------------------------------------- 时间轴对齐


def _load_transcript(video_id: str) -> list[dict]:
    p = transcript_dir(video_id) / "transcript.jsonl"
    if not p.exists():
        return []
    rows = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def _frames_in_window(frames: list[dict], start: float, end: float) -> list[dict]:
    """取出落在 [start-w, end+w] 内的帧；无命中则取最近一帧。"""
    lo, hi = start - FRAME_MATCH_WINDOW, end + FRAME_MATCH_WINDOW
    hit = [f for f in frames if lo <= f["ts"] <= hi]
    if hit:
        return hit
    if not frames:
        return []
    nearest = min(frames, key=lambda f: abs(f["ts"] - (start + end) / 2))
    return [nearest]


def build_multimodal(video_id: str, max_frames: int = 20) -> list[dict]:
    """生成 A1 的机器可读形态：每段带 speech/visual_facts/screen_text/frame_refs。"""
    segments = _load_transcript(video_id)
    frames = describe_frames(video_id, max_frames=max_frames)
    if not segments:
        return []

    out: list[dict] = []
    for seg in segments:
        start, end = float(seg["start_ts"]), float(seg["end_ts"])
        matched = _frames_in_window(frames, start, end)
        visual_facts: list[str] = []
        screen_text: list[str] = []
        for f in matched:
            desc = f.get("description", "")
            if not desc or desc.startswith("[VLM 失败"):
                continue
            visual_facts.append(desc)
            # 抽 屏幕文字/OCR 行
            for line in desc.splitlines():
                ls = line.strip()
                if any(k in ls for k in ("屏幕文字", "OCR")) or ls.startswith(("- ", "• ")):
                    if "屏幕文字" not in ls and "OCR" not in ls:
                        screen_text.append(ls.lstrip("- •").strip())
        out.append(
            {
                "start_ts": start,
                "end_ts": end,
                "speech": seg.get("text", ""),
                "speech_origin": seg.get("origin", ""),
                "visual_facts": visual_facts,
                "screen_text": screen_text,
                "frame_refs": [Path(f["frame_path"]).name for f in matched],
            }
        )
    return out


# ------------------------------------------------------------------ A1 双形态产出


def _fmt_ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def write_multimodal_md(video_id: str, rows: list[dict]) -> Path:
    """生成人读主产物 multimodal_transcript.md。"""
    meta = load_meta(video_id)
    out = transcript_dir(video_id) / "multimodal_transcript.md"
    dur = meta.duration if meta else 0

    lines = [
        "---",
        f"video_id: {video_id}",
        f"source: {meta.source if meta else ''}",
        f"source_type: {meta.source_type if meta else ''}",
        f"title: {meta.title if meta else ''}",
        f"uploader: {meta.uploader if meta else ''}",
        f"duration: {dur}",
        "language: zh",
        "pipeline: zhiying-v0.1",
        f"segments: {len(rows)}",
        "---",
        "",
        f"# {meta.title or video_id}",
        "",
        "> 多模态转写：口播 + 画面事实 + 屏幕文字 + 时间戳。由知映 zhiying 自动生成。",
        "",
    ]
    for r in rows:
        lines.append(f"## [{_fmt_ts(r['start_ts'])} - {_fmt_ts(r['end_ts'])}]")
        lines.append("")
        if r.get("speech"):
            lines.append(f"**口播**：{r['speech']}")
            lines.append("")
        for vf in r.get("visual_facts", []):
            dense = " ".join(vf.split())
            lines.append(f"**画面事实**：{dense}")
            lines.append("")
        if r.get("screen_text"):
            uniq = list(dict.fromkeys([t for t in r["screen_text"] if t]))
            if uniq:
                lines.append(f"**屏幕文字**：{' / '.join(uniq[:6])}")
                lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def write_multimodal_jsonl(video_id: str, rows: list[dict]) -> Path:
    out = transcript_dir(video_id) / "transcript.multimodal.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


def assemble(video_id: str, max_frames: int = 20) -> dict:
    """A1 组装总入口。"""
    rows = build_multimodal(video_id, max_frames=max_frames)
    if not rows:
        return {"ok": False, "reason": "无转写或无帧数据，请先执行 transcribe"}
    md = write_multimodal_md(video_id, rows)
    jl = write_multimodal_jsonl(video_id, rows)
    return {"ok": True, "md": str(md), "jsonl": str(jl), "segments": len(rows)}


# ---------------------------------------------------------------- A3 结构化摘要


def _text_llm(messages: list[dict], max_tokens: int = 1200) -> str:
    """文本 LLM 调用（与 VLM 同供应商，一个 Key 覆盖，FR-204 一致）。

    免费档 503/超时波动：自动重试 2 次（5s/15s 退避）。
    """
    import time

    key = getenv("SILICONFLOW_API_KEY")
    if not key:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY")
    model = os.environ.get("ZHIYING_TEXT_MODEL", "Qwen/Qwen3.5-9B")
    last_err = ""
    for attempt in range(3):
        try:
            r = requests.post(
                "https://api.siliconflow.cn/v1/chat/completions",
                headers={"Authorization": f"Bearer {key.strip()}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3},
                timeout=180,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break  # 非瞬时错误不重试
        except requests.RequestException as e:
            last_err = str(e)[:200]
        if attempt < 2:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"文本 LLM 失败（重试后）：{last_err}")


def summarize(video_id: str, force: bool = False) -> dict:
    """A3：视频级摘要 + ≥3 主题标签 + 可溯源要点（产物缓存，幂等）。"""
    cache = video_dir(video_id) / "summary.json"
    if cache.exists() and not force:
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("summary_text"):
                return {"ok": True, "path": str(cache), "cached": True, **d}
        except Exception:  # noqa: BLE001
            pass
    rows = build_multimodal(video_id)
    if not rows:
        return {"ok": False, "reason": "无多模态数据，请先 assemble"}
    meta = load_meta(video_id)

    # 压缩上下文：每段保留时间戳+口播+画面要点，控制 token
    ctx_lines = []
    for r in rows:
        ts = _fmt_ts(r["start_ts"])
        speech = (r.get("speech") or "")[:120]
        vis = " ".join((r.get("visual_facts") or [])[:1])
        vis = " ".join(vis.split())[:100]
        ctx_lines.append(f"[{ts}] 口播:{speech}｜画面:{vis}")
    ctx = "\n".join(ctx_lines)[:12000]

    prompt = f"""你是视频内容分析助手。以下是视频《{meta.title if meta else video_id}》的多模态转写（含时间戳）。

{ctx}

请严格只输出 JSON（不要 markdown 代码块、不要解释、不要多余文字），字段：
1. summary_text: 视频级摘要，200-400 字，说清主题、核心内容、结论
2. topics: 3-8 个主题标签（短词数组）
3. key_points: 3-8 个要点，每个 {{"claim": "要点内容", "start_ts": 对应时间点秒数}}

要求：只依据给定内容，不编造；start_ts 必须是上文中出现过的秒数。"""

    raw = _text_llm([{"role": "user", "content": prompt}])
    data = _parse_json_loose(raw)
    # 容错：模型可能把 JSON 嵌套在字符串字段里
    if "summary_text" in data and isinstance(data["summary_text"], str) and data["summary_text"].strip().startswith("{"):
        inner = _parse_json_loose(data["summary_text"])
        if inner:
            data = inner
    out = {
        "video_id": video_id,
        "title": meta.title if meta else "",
        "summary_text": data.get("summary_text", raw[:500]),
        "topics": data.get("topics", []),
        "key_points": data.get("key_points", []),
        "generated_by": os.environ.get("ZHIYING_TEXT_MODEL", "Qwen/Qwen3.5-9B"),
    }
    p = video_dir(video_id) / "summary.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(p), **out}


def _parse_json_loose(text: str) -> dict:
    """宽松解析：去 markdown 栅栏后取第一个 JSON 对象。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rsplit("```", 1)[0]
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            return json.loads(t[i : j + 1])
        except json.JSONDecodeError:
            pass
    return {}
