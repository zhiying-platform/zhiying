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

import hashlib
import os
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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


class DistillRequest(BaseModel):
    force: bool = False


class CookieLoginRequest(BaseModel):
    site: str = Field(..., description="站点名（bilibili/douyin/xiaohongshu/weibo）")
    timeout_sec: int = Field(300, description="等待登录的最长秒数")


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


@app.get("/api/config")
def readonly_config() -> dict:
    """只读非敏感配置展示（DR-28）：让用户在 Web 上知道数据在哪、用的什么模型。

    不含任何 Key；数据目录修改仍走 .env（安装级配置，改后需重启，不做页面编辑）。
    """
    from zhiying.envkeys import getenv
    from zhiying.paths import data_root

    return {
        "version": __version__,
        "vlm_provider": os.environ.get("ZHIYING_VLM_PROVIDER", "longcat"),
        "text_provider": os.environ.get("ZHIYING_TEXT_PROVIDER", "longcat"),
        "embed_model": os.environ.get("ZHIYING_EMBED_MODEL", "BAAI/bge-m3"),
        "data_dir": str(data_root()),
        "keys_configured": {
            "siliconflow": bool(getenv("SILICONFLOW_API_KEY")),
            "longcat": bool(getenv("LONGCAT_API_KEY")),
        },
    }


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

    流式写盘（1MB 分块）+ 流式 SHA256；同名文件自动加时间戳后缀。
    内容级去重（DR-23）：同内容文件（SHA256 相同）若已入库或在途，返回 409 + 既有 task_id，
    不会重复处理（尤其不会重复帧检测与 VLM 调用）。
    """
    from datetime import datetime

    from zhiying.download import file_sha256
    from zhiying.kb import find_video_by_hash

    incoming = data_root() / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    orig_name = Path(file.filename or "upload.mp4").name
    dst = incoming / orig_name
    if dst.exists():
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        dst = incoming / f"{Path(orig_name).stem}_{stamp}{Path(orig_name).suffix}"
    sha = hashlib.sha256()
    try:
        with dst.open("wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
                sha.update(chunk)  # 写盘同时算哈希，免二次读盘
    except Exception as e:  # noqa: BLE001
        dst.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"保存上传文件失败: {e}") from e
    if dst.stat().st_size == 0:
        dst.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="上传文件为空")
    content_hash = sha.hexdigest()

    # 内容级去重（DR-23）：先查在途任务，再查已入库
    _st, vid_by_hash = detect_source(str(dst))
    duplicate = find_video_by_hash(content_hash)
    if duplicate:
        dst.unlink(missing_ok=True)  # 重复文件直接丢弃，零处理
        raise HTTPException(
            status_code=409,
            detail={"task_id": duplicate[0], "stage": duplicate[1], "reason": "duplicate_content"},
        )

    _st, vid = detect_source(str(dst))
    existing = get_task(vid)
    if existing and existing.get("stage") in ("queued", "downloading", "transcribing", "visual", "summarizing"):
        dst.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail={"task_id": vid, "stage": existing.get("stage")})
    meta = load_meta(vid)
    if meta and meta.status == "done" and (video_dir(vid) / "summary.json").exists() and vid not in _jobs:
        raise HTTPException(status_code=409, detail={"task_id": vid, "stage": "done"})

    t = threading.Thread(target=_run_job, args=(vid, quality, str(dst), precision), daemon=True, name=f"api-upload-{vid}")
    with _lock:
        _jobs[vid] = t
    t.start()
    return {"task_id": vid, "file": str(dst), "stage": "queued", "content_hash": content_hash}


@app.delete("/api/tasks/{video_id}")
def delete_task(video_id: str, mode: str = "record", keep_source: bool = False) -> dict:
    """删除视频数据（DR-26 两种模式）：

    mode=record（默认）：仅清任务记录（task.json/meta.json），保留知识库与源视频/产物；
    mode=all：全部数据（KB 级联 + 工作目录），仅用于彻底清除；
    keep_source=true（配 all）：额外保留源视频文件。
    """
    from zhiying.kb import delete_video_data

    if mode not in ("record", "all"):
        raise HTTPException(status_code=400, detail="mode 仅支持 record|all")
    if not load_meta(video_id) and not (data_root() / "videos" / video_id).exists():
        raise HTTPException(status_code=404, detail="任务不存在")
    with _lock:
        _jobs.pop(video_id, None)
    r = delete_video_data(video_id, mode=mode, keep_source=keep_source)
    return {"deleted": True, "mode": mode, **r}


_RUN_STAGES = ("queued", "downloading", "transcribing", "visual", "summarizing")
_AUTO_RESUME_ON_LIST = True  # DR-36：查询任务列表时自动续跑卡住任务


def _is_stuck(task: dict | None) -> bool:
    """卡住判定（委派 pipeline.is_stuck，单一事实源）。"""
    from zhiying.pipeline import is_stuck

    return is_stuck(task)


@app.get("/api/tasks")
def list_tasks(
    stage_filter: str = "all",
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    auto_resume: bool = True,
) -> dict:
    """任务列表（DR-37：后端主导统计 + 筛选 + 分页）。

    返回结构：
      stats   : 全量各状态计数（不随筛选变化，前端统计卡片直接用）
      tasks   : 当前筛选 + 分页后的列表（只返当前页，降低前端渲染压力）
      total   : 当前筛选条件下的总条数（分页用）
      page/page_size/pages : 分页元信息

    stage_filter：all|running|done|failed|pending；keyword：标题/ID 模糊匹配。
    auto_resume=True（DR-36）：检测到卡住任务自动续跑（全量扫描，不受筛选影响）。
    """
    from zhiying.pipeline import get_task as _get_task
    from zhiying.pipeline import resume_if_stuck

    page = max(1, page)
    page_size = max(1, min(page_size, 200))  # 上限保护

    vdir = data_root() / "videos"
    all_rows: list[dict] = []
    resumed_ids: list[str] = []
    exhausted_ids: list[str] = []

    if vdir.exists():
        for m in sorted(vdir.glob("*/meta.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            vid = m.parent.name
            meta = load_meta(vid)
            task = _get_task(vid)
            stage = (task or {}).get("stage", "-")
            if stage == "-" and (video_dir(vid) / "summary.json").exists():
                stage = "done"  # 无任务记录的历史视频：从产物推断

            # DR-36 卡住自动续跑（全量扫描：不受筛选/分页影响）
            stuck = _is_stuck(task)
            resume_info: dict | None = None
            if stuck and auto_resume and _AUTO_RESUME_ON_LIST:
                resume_info = resume_if_stuck(vid, task=task)
                if resume_info.get("resumed"):
                    resumed_ids.append(vid)
                    task = _get_task(vid) or task
                    stage = (task or {}).get("stage", stage)
                elif "上限" in str(resume_info.get("reason", "")):
                    exhausted_ids.append(vid)

            all_rows.append({
                "video_id": vid,
                "title": meta.title if meta else "",
                "status": meta.status if meta else "",
                "stage": stage,
                "error": (task or {}).get("error", ""),
                "stuck": stuck and not (resume_info or {}).get("resumed"),
                "updated_at": (task or {}).get("updated_at", ""),
                "auto_resume_count": (task or {}).get("auto_resume_count", 0),
                "last_auto_resume_at": (task or {}).get("last_auto_resume_at", ""),
                "resume_note": (resume_info or {}).get("reason", ""),
            })

    # ---- 全量统计（不随筛选变化，对应前端四张统计卡片）----
    stats = {
        "total": len(all_rows),
        "running": sum(1 for r in all_rows if r["stage"] in _RUN_STAGES),
        "done": sum(1 for r in all_rows if r["stage"] == "done"),
        "failed": sum(1 for r in all_rows if r["stage"] == "failed"),
        "stuck": sum(1 for r in all_rows if r["stuck"]),
    }

    # ---- 条件筛选 ----
    rows = all_rows
    if stage_filter == "running":
        rows = [r for r in rows if r["stage"] in _RUN_STAGES]
    elif stage_filter == "done":
        rows = [r for r in rows if r["stage"] == "done"]
    elif stage_filter == "failed":
        rows = [r for r in rows if r["stage"] == "failed"]
    elif stage_filter == "pending":
        rows = [r for r in rows if r["stage"] in ("queued", "-")]

    kw = keyword.strip().lower()
    if kw:
        rows = [r for r in rows if kw in (r["title"] or "").lower() or kw in r["video_id"].lower()]

    # ---- 分页（只返当前页，避免前端一次渲染全部）----
    total = len(rows)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    start = (page - 1) * page_size
    page_rows = rows[start : start + page_size]

    return {
        "tasks": page_rows,
        "stats": stats,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "auto_resumed": resumed_ids,
        "auto_resume_exhausted": exhausted_ids,
    }


@app.post("/api/tasks/{video_id}/reset")
def reset_task(video_id: str) -> dict:
    """重置卡住的任务（DR-34）：清 task.json 后从失败/中断阶段重跑。

    适用场景：后台进程被回收导致任务永远停在 transcribing/visual（实测事故）。
    产物幂等：已完成的阶段（下载/转写/帧描述）会复用缓存，不重复调用 API。
    """
    from zhiying.pipeline import set_stage, start_async

    d = video_dir(video_id)
    if not d.exists():
        raise HTTPException(status_code=404, detail="任务不存在")
    task = get_task(video_id)
    if task and task.get("stage") == "done":
        raise HTTPException(status_code=400, detail="任务已完成，无需重置（如需重跑请用 DELETE + 重新提交）")

    with _lock:
        _jobs.pop(video_id, None)
    set_stage(video_id, "queued", "已重置，等待重跑")
    meta = load_meta(video_id)
    src = meta.source if meta else None
    if not src:
        raise HTTPException(status_code=400, detail="无源信息，无法重跑（请重新提交视频）")
    start_async(video_id, quality="480", src=src)
    return {"reset": True, "task_id": video_id, "stage": "queued"}


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


@app.post("/api/distill/{video_id}")
def distill_api(video_id: str, req: DistillRequest | None = None) -> dict:
    """skill 蒸馏（DR-33）：A1 → 能力卡 → SKILL.md 包。同步执行（含 LLM 调用，数十秒级）。"""
    from zhiying.distill import distill

    force = bool(req and req.force)
    r = distill(video_id, force=force)
    if not r.get("ok"):
        raise HTTPException(status_code=422, detail=r.get("reason", "蒸馏失败"))
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


# ---------------------------------------------------------------- Cookie 管理（DR-39）

# 登录引导会话表（site → 状态）；登录为长操作，走后台线程 + 轮询
_cookie_jobs: dict[str, dict] = {}


def _cookie_job_runner(site: str, timeout_sec: int) -> None:
    from zhiying.cookies import capture_cookies_interactive, cookie_file_for

    try:
        f = capture_cookies_interactive(site, timeout_sec=timeout_sec)
        if f:
            _cookie_jobs[site] = {"state": "captured", "file": str(f)}
        else:
            _cookie_jobs[site] = {"state": "not_captured", "detail": "超时或窗口被关闭，未捕获到登录 Cookie"}
    except Exception as e:  # noqa: BLE001
        _cookie_jobs[site] = {"state": "error", "detail": str(e)[:200]}


@app.post("/api/cookies/{site}/login")
def cookie_login(site: str, req: CookieLoginRequest) -> dict:
    """发起登录引导（DR-39）：弹出浏览器，用户登录后自动捕获 Cookie。

    立即返回 202；用 GET /api/cookies/{site} 轮询状态。
    """
    from zhiying.cookies import SITE_PROFILES

    if site not in SITE_PROFILES:
        raise HTTPException(status_code=400, detail=f"不支持的站点: {site}（支持 {list(SITE_PROFILES)}）")
    if not _interactive_allowed():
        raise HTTPException(status_code=400, detail="当前环境无显示界面（容器），请改用手动导入 Cookie 文件")
    if site in _cookie_jobs and _cookie_jobs[site].get("state") == "capturing":
        raise HTTPException(status_code=409, detail={"state": "capturing"})

    _cookie_jobs[site] = {"state": "capturing"}
    t = threading.Thread(target=_cookie_job_runner, args=(site, req.timeout_sec), daemon=True, name=f"cookie-{site}")
    t.start()
    return {"site": site, "state": "capturing", "timeout_sec": req.timeout_sec}


@app.get("/api/cookies/{site}")
def cookie_status(site: str) -> dict:
    """查询登录引导进度与该站 Cookie 缓存状态。"""
    from zhiying.cookies import has_cookie, cookie_file_for

    job = _cookie_jobs.get(site)
    if job:
        return {"site": site, **job, "has_cookie": has_cookie(site), "file": str(cookie_file_for(site))}
    return {"site": site, "state": "idle", "has_cookie": has_cookie(site), "file": str(cookie_file_for(site))}


@app.delete("/api/cookies/{site}")
def cookie_clear(site: str) -> dict:
    """清除该站点缓存的 Cookie（登录失效或换号时用）。"""
    from zhiying.cookies import cookie_file_for

    f = cookie_file_for(site)
    existed = f.exists()
    f.unlink(missing_ok=True)
    _cookie_jobs.pop(site, None)
    return {"cleared": existed}


# ---------------------------------------------------------------- 前端静态托管（V1.0 单容器部署）
# 设置 ZHIYING_WEB_DIST 指向 zhiying-web 的 dist 目录即开启；未设置则纯 API 服务。
# 必须在所有 /api 路由注册之后挂载 (catch-all 会拦截后续路由)。
_WEB_DIST = os.environ.get("ZHIYING_WEB_DIST")
if _WEB_DIST and Path(_WEB_DIST).is_dir():
    _dist = Path(_WEB_DIST)
    if (_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        """SPA 回退：静态文件命中则返回文件，否则返回 index.html（前端路由接管）。"""
        candidate = (_dist / full_path).resolve()
        # 目录穿越防护
        if candidate.is_file() and str(candidate).startswith(str(_dist.resolve())):
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")


def main() -> int:
    import uvicorn

    from zhiying.console import setup_console

    setup_console()
    # 容器内需 0.0.0.0 才能被宿主机访问；本机开发默认 127.0.0.1
    host = os.environ.get("ZHIYING_API_HOST", "127.0.0.1")
    port = int(os.environ.get("ZHIYING_API_PORT", "8600"))
    web = f"  前端: http://{host}:{port}" if _WEB_DIST else ""
    print(f"知映 API: http://{host}:{port}  (docs: /docs){web}")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
