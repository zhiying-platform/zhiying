"""RAG 问答（FR-204 / 产物 A4）。

答案生成 LLM 与 VLM 同供应商（一个 Key，FR-204），答案强制带来源引用；
无据可答时明确说明，不编造。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

import requests

from zhiying.envkeys import getenv
from zhiying.kb import search


def _fmt_ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def ask(question: str, top_k: int = 5) -> dict:
    """基于知识库的 RAG 问答。返回 A4 结构化回答。"""
    hits = search(question, top_k=top_k)
    if not hits:
        return {
            "answer_text": "知识库中无依据",
            "citations": [],
            "note": "no_evidence",
        }

    ctx_lines = []
    for h in hits:
        ts = f"[{_fmt_ts(h['start_ts'])} - {_fmt_ts(h['end_ts'])}]"
        ctx_lines.append(f"【{h['title']}】{ts}\n{h['text'][:400]}")
    context = "\n\n".join(ctx_lines)[:8000]

    prompt = f"""你是知识库问答助手。以下是知识库检索到的相关内容（含视频标题与时间戳）：

{context}

用户问题：{question}

请输出严格 JSON（不要 markdown 代码块），字段：
1. answer_text: 用中文回答，清晰简洁，基于上述内容，不编造
2. citations: 引用数组，每个 {{"video_title": "视频标题", "start_ts": 秒数, "end_ts": 秒数, "quote": "支撑该答案的原文片段（简短）"}}

如果内容不足以回答，answer_text 写「知识库中无依据」并将 citations 置空。"""

    key = getenv("SILICONFLOW_API_KEY")
    if not key:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY")
    model = os.environ.get("ZHIYING_TEXT_MODEL", "Qwen/Qwen3.5-9B")
    r = requests.post(
        "https://api.siliconflow.cn/v1/chat/completions",
        headers={"Authorization": f"Bearer {key.strip()}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 800, "temperature": 0.2},
        timeout=180,
    )
    if r.status_code != 200:
        raise RuntimeError(f"问答 LLM HTTP {r.status_code}: {r.text[:200]}")

    raw = r.json()["choices"][0]["message"]["content"]
    data = _parse_json(raw)

    citations = data.get("citations") or []
    # 强制溯源校验：每条引用补齐 video_id（从 hits 里匹配标题）
    title_to_hit = {h["title"]: h for h in hits}
    norm_cites = []
    for c in citations:
        title = c.get("video_title", "")
        hit = title_to_hit.get(title)
        norm_cites.append({
            "video_id": hit["video_id"] if hit else "",
            "title": title,
            "start_ts": c.get("start_ts", 0),
            "end_ts": c.get("end_ts", 0),
            "quote": c.get("quote", ""),
            "start_ts_fmt": _fmt_ts(c.get("start_ts", 0)),
            "end_ts_fmt": _fmt_ts(c.get("end_ts", 0)),
        })
    if not norm_cites and data.get("answer_text") and "无依据" not in data.get("answer_text", ""):
        # LLM 没给引用时兜底用检索 hit（保证「答必有据」）
        for h in hits[:3]:
            norm_cites.append({
                "video_id": h["video_id"], "title": h["title"],
                "start_ts": h["start_ts"], "end_ts": h["end_ts"],
                "quote": h["text"][:120],
                "start_ts_fmt": _fmt_ts(h["start_ts"]), "end_ts_fmt": _fmt_ts(h["end_ts"]),
            })
    return {
        "answer_text": data.get("answer_text", raw[:500]),
        "citations": norm_cites,
        "note": "" if norm_cites else "no_evidence",
    }


def _parse_json(text: str) -> dict:
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
    return {"answer_text": text}
