"""知识库入库与检索（V0.2 S8/S10，PRD FR-201/202）。

- 入库：A1 JSONL 逐段 → segments；合并 → chunks + embedding（Qwen3-Embedding-8B）
- 检索：pgvector 向量检索为主 + tsvector 全文为辅（jieba 应用侧分词）
- 连接：.env 的 ZHIYING_DB_*（init_db 已对齐）
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

from zhiying.envkeys import getenv

# ------------------------------------------------------------------ 连接与配置


def delete_video_data(video_id: str, mode: str = "record", keep_source: bool = False) -> dict:
    """删除视频数据（DR-26 任务管理两种模式）。

    mode="record"（默认）：仅清任务记录（task.json + meta.json），
      保留 KB 与源视频/产物 —— 用于清理已失败/弃用的任务记录而不丢已完成成果。
    mode="all"：全部数据（KB 级联 + 工作目录），仅用于明确要求彻底清除时。
    keep_source=True：mode=all 时额外保留源视频（防误删昂贵的已下载视频）。
    幂等：KB 无行、目录不存在均视为删除成功。
    """
    import shutil

    import psycopg

    from zhiying.paths import video_dir as _video_dir

    kb_deleted = False
    deleted_items: list[str] = []

    if mode == "all":
        try:
            with psycopg.connect(**db_conn_kwargs()) as conn:
                cur = conn.execute("DELETE FROM videos WHERE id = %s", (video_id,))
                kb_deleted = cur.rowcount > 0
                conn.commit()
        except Exception:  # noqa: BLE001  KB 不可达时仍继续删目录
            pass
        deleted_items.append("知识库") if kb_deleted else None

    d = _video_dir(video_id)
    dir_deleted = False
    if d.exists():
        if mode == "all" and not keep_source:
            shutil.rmtree(d, ignore_errors=True)
            dir_deleted = not d.exists()
            if dir_deleted:
                deleted_items.append("工作目录（含源视频与产物）")
        else:
            # record 模式：只删任务记录文件，保留 source/产物/帧等
            for name in ("task.json", "meta.json"):
                f = d / name
                if f.exists():
                    f.unlink(missing_ok=True)
            dir_deleted = True
            deleted_items.append("任务记录（task/meta）")
    return {
        "kb_deleted": kb_deleted,
        "dir_deleted": dir_deleted,
        "deleted_items": deleted_items,
    }


def db_conn_kwargs() -> dict:
    import psycopg

    return dict(
        host=os.environ.get("ZHIYING_DB_HOST") or getenv("ZHIYING_DB_HOST") or "localhost",
        port=int(os.environ.get("ZHIYING_DB_PORT") or getenv("ZHIYING_DB_PORT") or "5432"),
        user=os.environ.get("ZHIYING_DB_USER") or getenv("ZHIYING_DB_USER") or "postgres",
        password=os.environ.get("ZHIYING_DB_PASSWORD") or getenv("ZHIYING_DB_PASSWORD"),
        dbname=os.environ.get("ZHIYING_DB_NAME") or getenv("ZHIYING_DB_NAME") or "zhiying",
    )


def _embedding_model() -> str:
    # BAAI/bge-m3 实测 1024 维，与 schema_v1 冻结契约 vector(1024) 匹配；
    # Qwen3-Embedding-8B 为 4096 维，换用时需同步改表结构
    return os.environ.get("ZHIYING_EMBED_MODEL", "BAAI/bge-m3")


def _vec_literal(emb: list[float] | None) -> str | None:
    """Python list → pgvector 文本字面量 '[1,2,3]'，配合 %s::vector 使用。

    psycopg 默认把 list 适配为 double precision[]，而 pgvector 的 <->/<=> 算子
    只接受 vector 类型；显式 cast 是零依赖的稳妥解法。
    """
    if not emb:
        return None
    return "[" + ",".join(f"{x:.8g}" for x in emb) + "]"


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量 embedding（硅基流动，BAAI/bge-m3，1024 维）。"""
    key = getenv("SILICONFLOW_API_KEY")
    if not key:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY")
    r = requests.post(
        "https://api.siliconflow.cn/v1/embeddings",
        headers={"Authorization": f"Bearer {key.strip()}"},
        json={"model": _embedding_model(), "input": texts, "encoding_format": "float"},
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"embedding HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    return [item["embedding"] for item in data["data"]]


# ------------------------------------------------------------------ jieba 分词（tsvector 辅助）


def zh_segment(text: str) -> str:
    """jieba 分词，空格连接，供 tsvector 中文检索。"""
    import jieba

    jieba.setLogLevel(20)  # 静默
    tokens = [t.strip() for t in jieba.cut(text) if t.strip()]
    return " ".join(tokens)


# ------------------------------------------------------------------ 入库


def find_video_by_hash(content_hash: str) -> tuple[str, str] | None:
    """按内容哈希查已入库视频，返回 (video_id, status) 或 None。"""
    import psycopg

    try:
        with psycopg.connect(**db_conn_kwargs()) as conn:
            row = conn.execute(
                "SELECT id, status FROM videos WHERE content_hash = %s ORDER BY created_at DESC LIMIT 1",
                (content_hash,),
            ).fetchone()
            return (row[0], row[1]) if row else None
    except Exception:  # noqa: BLE001
        return None


def ingest_video(video_id: str, force: bool = False) -> dict:
    """把 V0.1 产物入库：videos 元数据 + segments 逐段 + chunks 合并向量化。"""
    import psycopg

    from zhiying.download import load_meta
    from zhiying.paths import transcript_dir, video_dir

    kw = db_conn_kwargs()
    rows: list[dict] = []
    p = transcript_dir(video_id) / "transcript.multimodal.jsonl"
    if not p.exists():
        return {"ok": False, "reason": f"无 A1 产物: {p}，先 assemble"}
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if not rows:
        return {"ok": False, "reason": "A1 为空"}

    meta = load_meta(video_id)
    summary = {}
    sp = video_dir(video_id) / "summary.json"
    if sp.exists():
        try:
            summary = json.loads(sp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    with psycopg.connect(**kw) as conn:
        with conn.cursor() as cur:
            # 幂等：先清旧数据
            cur.execute("DELETE FROM chunks WHERE video_id=%s", (video_id,))
            cur.execute("DELETE FROM segments WHERE video_id=%s", (video_id,))
            cur.execute(
                """INSERT INTO videos (id, source_type, source, title, uploader, duration, status,
                       summary_text, topics, pipeline_version, transcribe_origin, vlm_provider, text_model, content_hash)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id) DO UPDATE SET
                         title=EXCLUDED.title, uploader=EXCLUDED.uploader, duration=EXCLUDED.duration,
                         status=EXCLUDED.status, summary_text=EXCLUDED.summary_text,
                         topics=EXCLUDED.topics, content_hash=EXCLUDED.content_hash, updated_at=now()""",
                (
                    video_id,
                    meta.source_type if meta else "unknown",
                    meta.source if meta else "",
                    (meta.title if meta else "") or "",
                    (meta.uploader if meta else "") or "",
                    meta.duration if meta else 0,
                    "done",
                    summary.get("summary_text", ""),
                    summary.get("topics", []),
                    "v0.1",
                    rows[0].get("speech_origin", ""),
                    os.environ.get("ZHIYING_VLM_PROVIDER", "siliconflow"),
                    summary.get("generated_by", ""),
                    meta.content_hash if meta else "",
                ),
            )
            # segments
            for i, r in enumerate(rows):
                cur.execute(
                    """INSERT INTO segments (video_id, seg_index, start_ts, end_ts, speech, speech_origin,
                           visual_facts, screen_text, frame_refs) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        video_id, i, r["start_ts"], r["end_ts"], r.get("speech", ""),
                        r.get("speech_origin", ""), r.get("visual_facts", []),
                        r.get("screen_text", []), r.get("frame_refs", []),
                    ),
                )
            # chunks：相邻段合并（目标 300-800 token 估算：中文 1 字 ≈ 0.6 token）
            chunks = _merge_chunks(rows)
            texts = [c["text"] for c in chunks]
            embs = embed_texts(texts) if texts else []
            for i, c in enumerate(chunks):
                tok = max(1, int(len(c["text"]) * 0.6))
                cur.execute(
                    """INSERT INTO chunks (video_id, chunk_index, start_ts, end_ts, text, modality,
                           embedding, token_count, tsv) VALUES (%s,%s,%s,%s,%s,%s,%s::vector,%s,to_tsvector('simple', %s))""",
                    (
                        video_id, i, c["start_ts"], c["end_ts"], c["text"], c["modality"],
                        _vec_literal(embs[i]) if i < len(embs) else None, tok, zh_segment(c["text"]),
                    ),
                )
        conn.commit()
    return {"ok": True, "segments": len(rows), "chunks": len(chunks)}


def _merge_chunks(rows: list[dict], target_chars: int = 600) -> list[dict]:
    """相邻段合并为检索单元；窗口可调。"""
    chunks: list[dict] = []
    buf: list[dict] = []
    nchars = 0
    for r in rows:
        text = r.get("speech", "") or ""
        vis = " ".join(r.get("visual_facts", []))[:200]
        full = f"{text} {'（画面：' + vis + '）' if vis else ''}"
        nchars += len(full)
        buf.append(r)
        if nchars >= target_chars or len(buf) >= 5:
            chunks.append(_make_chunk(buf))
            buf, nchars = [], 0
    if buf:
        chunks.append(_make_chunk(buf))
    return chunks


def _make_chunk(buf: list[dict]) -> dict:
    """构建检索单元文本。

    关键：chunk 文本必须融合【口播 + 画面事实 + 屏幕文字】。
    实测教训：美食/教程类视频的语音转写常只有背景音符号，
    真正的内容在画面里（切菠萝、调味料碗、PPT 图表）；
    只用 speech 会让知识库空壳化。
    """
    speech_parts: list[str] = []
    visual_parts: list[str] = []
    screen_parts: list[str] = []
    for r in buf:
        s = (r.get("speech") or "").strip()
        # 过滤纯音乐符号/单字符噪声（SenseVoice 对背景音的常见输出）
        if s and not _is_noise(s):
            speech_parts.append(s)
        facts = r.get("visual_facts") or []
        if isinstance(facts, str):
            facts = [facts]
        visual_parts.extend(str(x).strip() for x in facts if x)
        st = r.get("screen_text") or []
        if isinstance(st, str):
            st = [st]
        screen_parts.extend(str(x).strip() for x in st if x)

    speech = " ".join(speech_parts).strip()
    visual = " ".join(dict.fromkeys(visual_parts)).strip()
    screen = " / ".join(dict.fromkeys(screen_parts))

    # 融合：口播(如有) + 画面事实 + 屏幕文字
    segs: list[str] = []
    if speech:
        segs.append(speech)
    if visual:
        segs.append(f"【画面】{visual}")
    if screen:
        segs.append(f"【屏幕文字】{screen}")
    text = " ".join(segs).strip()

    modality = "mixed" if speech and visual else ("visual" if visual else "speech")
    return {
        "start_ts": buf[0]["start_ts"],
        "end_ts": buf[-1]["end_ts"],
        "text": text,
        "modality": modality,
    }


def _is_noise(s: str) -> bool:
    """判定是否为语音转写噪声（纯音乐符号/无意义单字）。"""
    import re

    core = re.sub(r"[\s🎼🎵🎶♪♫。，、,.!！?？…~\-]", "", s)
    # 去掉符号后少于 2 个字符，或全是非中英文字符 → 噪声
    if len(core) <= 1:
        return True
    return False


# ------------------------------------------------------------------ 检索


def deep_link(video_id: str, ts: float, source: str = "") -> str | None:
    """视频深链（带时间点）；本地文件/未知来源返回 None。

    DR-38 扩充：B站/YouTube 直接生成；其他平台有原始链接时尝试拼时间参数。
    """
    if not video_id:
        return None
    t = int(ts)
    if video_id.startswith("BV"):
        return f"https://www.bilibili.com/video/{video_id}/?t={t}"
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return f"https://www.youtube.com/watch?v={video_id}&t={t}s"
    # 其他平台：有原始链接时尝试拼时间参数（无标准格式的返回原链接）
    if source and source.lower().startswith(("http://", "https://")):
        base = source.split("?")[0]
        if "douyin.com" in base:
            return f"{base}?t={t}"
        if "b23.tv" in base:
            return f"{base}?t={t}"
        return source  # 微博/小红书等无标准时间参数，返回原链接
    return None


def search(query: str, top_k: int = 5) -> list[dict]:
    """向量检索为主，tsvector 全文为辅（jieba），加权混合。"""
    import psycopg

    q_emb = _vec_literal(embed_texts([query])[0])
    q_seg = zh_segment(query)
    kw = db_conn_kwargs()
    out: list[dict] = []
    with psycopg.connect(**kw) as conn:
        with conn.cursor() as cur:
            # 向量检索（cosine）
            cur.execute(
                """SELECT c.id, c.video_id, v.title, v.source, c.start_ts, c.end_ts, c.text,
                       c.embedding <=> %s::vector AS dist
                   FROM chunks c JOIN videos v ON v.id = c.video_id
                   WHERE c.embedding IS NOT NULL
                   ORDER BY c.embedding <=> %s::vector
                   LIMIT %s""",
                (q_emb, q_emb, top_k * 3),
            )
            for row in cur.fetchall():
                out.append({
                    "chunk_id": row[0], "video_id": row[1], "title": row[2],
                    "source": row[3],
                    "start_ts": float(row[4]), "end_ts": float(row[5]), "text": row[6],
                    "score": round(1 - float(row[7]), 4), "source_kind": "vector",
                })
            # 全文辅助（tsvector + jieba 分词）
            if q_seg:
                cur.execute(
                    """SELECT c.id, c.video_id, v.title, v.source, c.start_ts, c.end_ts, c.text,
                           ts_rank(c.tsv, to_tsquery('simple', %s)) AS rank
                       FROM chunks c JOIN videos v ON v.id = c.video_id
                       WHERE c.tsv @@ to_tsquery('simple', %s)
                       ORDER BY rank DESC LIMIT %s""",
                    (q_seg.replace(" ", " & "), q_seg.replace(" ", " & "), top_k),
                )
                for row in cur.fetchall():
                    out.append({
                        "chunk_id": row[0], "video_id": row[1], "title": row[2],
                        "source": row[3],
                        "start_ts": float(row[4]), "end_ts": float(row[5]), "text": row[6],
                        "score": round(float(row[7]), 4), "source_kind": "fulltext",
                    })
    # 合并去重（同 chunk 取高分）
    seen: dict[int, dict] = {}
    for item in out:
        if item["chunk_id"] not in seen or item["score"] > seen[item["chunk_id"]]["score"]:
            seen[item["chunk_id"]] = item
    return sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:top_k]
