"""FastAPI 服务层（V0.2 S11，PRD FR-302 / §5.5 API 契约）。

启动：python -m zhiying.api  （默认 127.0.0.1:8600）

端点（§5.5 契约草案）：
- POST /api/tasks        提交处理任务（异步执行，202 返回 task 信息；409 幂等）
- GET  /api/tasks        任务列表
- GET  /api/tasks/{id}   任务详情（含 stage）
- POST /api/search       知识库检索（top_k 默认 5）
- POST /api/ask          RAG 问答（A4 结构化回答 + 引用）
- GET  /api/videos       知识库视频清单
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from zhiying import __version__
from zhiying.download import detect_source, load_meta
from zhiying.paths import data_root, video_dir
from zhiying.pipeline import get_task, run_sync

app = FastAPI(title="知映 zhiying API", version=__version__, description="视频知识库服务层（V0.2）")

# 进程内任务表（FR-301 进程内队列起步；V0.3+ 可换 Redis/DB 队列）
_jobs: dict[str, threading.Thread] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- 请求/响应模型


class TaskCreate(BaseModel):
    source: str = Field(..., description="视频 URL 或本地路径")
    quality: str = Field("480", description="最高清晰度")
    precision: str = Field("fast", description="画面识别精度：fast（默认，≥10min 走 seek 采样）| precise（逐帧场景检测）")


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class AskRequest(BaseModel):
    question: str
    top_k: int = 5


# ---------------------------------------------------------------- 工具


def _run_job(video_id: str, quality: str, src: str, precision: str = "fast") -> None:
    try:
        run_sync(video_id, quality=quality, src=src, precision=precision)
    except Exception as e:  # noqa: BLE001
        from zhiying.pipeline import set_stage

        set_stage(video_id, "failed", error=f"{type(e).__name__}: {str(e)[:200]}")


# ---------------------------------------------------------------- 端点


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/api/tasks", status_code=202)
def create_task(req: TaskCreate) -> dict:
    _st, vid = detect_source(req.source)
    existing = get_task(vid)
    meta = load_meta(vid)
    # 幂等（FR-203）：已完成或处理中返回 409 + 既有 task_id
    if existing and existing.get("stage") in ("queued", "downloading", "transcribing", "visual", "summarizing"):
        raise HTTPException(status_code=409, detail={"task_id": vid, "stage": existing.get("stage")})
    if meta and meta.status == "done" and (video_dir(vid) / "summary.json").exists() and vid not in _jobs:
        raise HTTPException(status_code=409, detail={"task_id": vid, "stage": "done"})

    t = threading.Thread(target=_run_job, args=(vid, req.quality, req.source, req.precision), daemon=True, name=f"api-{vid}")
    with _lock:
        _jobs[vid] = t
    t.start()
    return {"task_id": vid, "stage": "queued"}


@app.post("/api/upload")
async def upload_video(
    file: UploadFile = File(...),
    quality: str = Form("480"),
    precision: str = Form("fast"),
) -> dict:
    """上传本地视频并创建处理任务（一步到位：落盘 + 建任务）。

    流式写盘（1MB 分块），支持大文件；同名文件自动加时间戳后缀。
    """
    from datetime import datetime

    incoming = data_root() / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    orig_name = Path(file.filename or "upload.mp4").name
    dst = incoming / orig_name
    if dst.exists():
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        dst = incoming / f"{Path(orig_name).stem}_{stamp}{Path(orig_name).suffix}"
    try:
        with dst.open("wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
    except Exception as e:  # noqa: BLE001
        dst.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"保存上传文件失败: {e}") from e
    if dst.stat().st_size == 0:
        dst.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传文件为空")

    _st, vid = detect_source(str(dst))
    existing = get_task(vid)
    if existing and existing.get("stage") in ("queued", "downloading", "transcribing", "visual", "summarizing"):
        raise HTTPException(status_code=409, detail={"task_id": vid, "stage": existing.get("stage")})
    meta = load_meta(vid)
    if meta and meta.status == "done" and (video_dir(vid) / "summary.json").exists() and vid not in _jobs:
        raise HTTPException(status_code=409, detail={"task_id": vid, "stage": "done"})

    t = threading.Thread(target=_run_job, args=(vid, quality, str(dst), precision), daemon=True, name=f"api-upload-{vid}")
    with _lock:
        _jobs[vid] = t
    t.start()
    return {"task_id": vid, "file": str(dst), "stage": "queued"}


@app.get("/api/tasks")
def list_tasks() -> dict:
    vdir = data_root() / "videos"
    out = []
    if vdir.exists():
        for m in sorted(vdir.glob("*/meta.json")):
            vid = m.parent.name
            meta = load_meta(vid)
            task = get_task(vid)
            out.append({
                "video_id": vid,
                "title": meta.title if meta else "",
                "status": meta.status if meta else "",
                "stage": (task or {}).get("stage", "-"),
            })
    return {"tasks": out}


@app.get("/api/tasks/{video_id}")
def task_detail(video_id: str) -> dict:
    meta = load_meta(video_id)
    if not meta:
        raise HTTPException(status_code=404, detail="task not found")
    task = get_task(video_id) or {}
    return {"video_id": video_id, "meta": {k: v for k, v in vars(meta).items()}, "stage": task.get("stage", "-"),
            "detail": task.get("detail", ""), "error": task.get("error", "")}


@app.post("/api/search")
def search_api(req: SearchRequest) -> dict:
    from zhiying.kb import search

    hits = search(req.query, top_k=req.top_k)
    return {"query": req.query, "results": hits}


@app.post("/api/ask")
def ask_api(req: AskRequest) -> dict:
    from zhiying.rag import ask

    r = ask(req.question, top_k=req.top_k)
    return r


@app.get("/api/videos")
def list_videos() -> dict:
    import psycopg

    from zhiying.kb import db_conn_kwargs

    try:
        with psycopg.connect(**db_conn_kwargs()) as conn:
            rows = conn.execute(
                "SELECT id, title, uploader, duration, status, topics, summary_text FROM videos ORDER BY created_at DESC"
            ).fetchall()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"知识库不可用: {e}") from e
    return {"videos": [
        {"video_id": r[0], "title": r[1], "uploader": r[2], "duration": r[3],
         "status": r[4], "topics": r[5], "summary": (r[6] or "")[:120]}
        for r in rows
    ]}


def main() -> int:
    import uvicorn

    from zhiying.console import setup_console

    setup_console()
    host = "127.0.0.1"
    port = 8600
    print(f"知映 API: http://{host}:{port}  (docs: /docs)")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
