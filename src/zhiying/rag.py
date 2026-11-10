"""RAG 问答（FR-204 / 产物 A4）。

答案生成走 llm.chat_text（DR-14：默认 LongCat，与 VLM 同 Key 覆盖）；
答案强制带来源引用；无据可答时明确说明，不编造。
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

    from zhiying.llm import chat_text

    raw = chat_text([{"role": "user", "content": prompt}], max_tokens=2000, temperature=0.2)
    # 注意：max_tokens 必须 ≥2000——LongCat 输出的完整 JSON（答案+3 条引用）超 800；
    # 截断会导致内层 JSON 解析失败回退到原文（实测事故）
    data = _parse_json(raw)
    # 容错：模型可能把 JSON 嵌套在字符串字段里（双层编码，与 assemble 同款问题）
    if "answer_text" in data and isinstance(data["answer_text"], str) and data["answer_text"].strip().startswith("{"):
        inner = _parse_json(data["answer_text"])
        if inner and inner.get("answer_text"):
            data = inner

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
