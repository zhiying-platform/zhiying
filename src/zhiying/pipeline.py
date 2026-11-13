"""管道编排与任务状态（B7：ingest 异步化 + watch/retry，PRD DR-19）。

任务状态落盘 <data>/videos/<id>/task.json：
    {"stage": queued|downloading|transcribing|visual|summarizing|done|failed,
     "detail": 当前阶段说明, "error": 失败原因, "updated_at": iso,
     "precision": fast|precise, "auto_resume_count": N, "last_auto_resume_at": iso}

ingest 默认同步执行全流程；--async 启动独立子进程。
watch 轮询 task.json 直到 done/failed；retry 只重跑（各阶段内部幂等）。

DR-36 卡住自动续跑：后台进程被环境回收时不写 failed（实测事故），任务永远停在
中间阶段。list_tasks 检测心跳陈旧 → 自动续跑（管道幂等，已完成阶段复用缓存，
等价于续跑而非重跑）。防护：每任务最多 3 次、间隔 ≥10 分钟，超限后转人工处理。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from zhiying import proc
from zhiying.paths import video_dir

STAGES = ("queued", "downloading", "transcribing", "visual", "summarizing", "done", "failed")
RUN_STAGES = ("queued", "downloading", "transcribing", "visual", "summarizing")

# 卡住判定与自动续跑防护（DR-36）
STUCK_MINUTES = 10
AUTO_RESUME_MAX = 3
AUTO_RESUME_COOLDOWN_SEC = 600

# set_stage 需保留的追踪字段（不被覆盖）
_PRESERVED_FIELDS = ("precision", "auto_resume_count", "last_auto_resume_at")


def _task_path(video_id: str) -> Path:
    return video_dir(video_id) / "task.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_task(video_id: str) -> dict | None:
    p = _task_path(video_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def set_stage(video_id: str, stage: str, detail: str = "", error: str = "", **extra) -> None:
    """写任务状态；保留 precision 与自动续跑追踪字段（DR-36）。"""
    prev = get_task(video_id) or {}
    payload = {"stage": stage, "detail": detail, "error": error, "updated_at": _now_iso()}
    for k in _PRESERVED_FIELDS:
        if k in prev:
            payload[k] = prev[k]
    payload.update({k: v for k, v in extra.items() if v is not None})
    _task_path(video_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_stuck(task: dict | None, minutes: int = STUCK_MINUTES) -> bool:
    """卡住判定：处于运行阶段但心跳超过 minutes 未更新。"""
    if not task:
        return False
    if task.get("stage") not in RUN_STAGES:
        return False
    updated = task.get("updated_at")
    if not updated:
        return False
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).total_seconds()
    except (ValueError, TypeError):
        return False
    return age > minutes * 60


def _pipeline(video_id: str, quality: str, src: str | None = None, precision: str = "fast") -> None:
    """全流程（同步或子进程内执行）；各阶段内部幂等，因此重跑等价于续跑。"""
    from zhiying.assemble import assemble, summarize
    from zhiying.download import download, load_meta
    from zhiying.transcribe import transcribe

    try:
        set_stage(video_id, "downloading", "下载/复用源视频", precision=precision)
        meta = load_meta(video_id)
        source = (meta.source if meta and meta.source else None) or src
        if not source:
            set_stage(video_id, "failed", error="无源信息（首次处理需传 src，或 meta 缺失）")
            return
        m = download(source, quality=quality)
        if m.status != "done":
            set_stage(video_id, "failed", error=f"下载失败: {(m.error or '')[:200]}")
            return

        set_stage(video_id, "transcribing", "语音转写（三级降级）")
        tr = transcribe(video_id)
        if not tr.get("path"):
            reasons = tr.get("reasons") or []
            detail = "转写失败（全部通道）"
            if reasons:
                detail += "：" + "；".join(reasons)
            set_stage(video_id, "failed", error=detail)
            return

        prec_label = "精细" if precision == "precise" else "快速"
        set_stage(video_id, "visual", f"关键帧提取与 VLM 识别（{prec_label}档）")
        r = assemble(video_id, precision=precision)
        if not r.get("ok"):
            set_stage(video_id, "failed", error=str(r.get("reason")))
            return

        set_stage(video_id, "summarizing", "生成结构化摘要")
        s = summarize(video_id, precision=precision)
        if not s.get("ok"):
            set_stage(video_id, "failed", error=str(s.get("reason")))
            return

        # 知识库自动入库（V0.2 产物闭环；同时写入 content_hash 供上传去重，DR-23）
        kb_note = ""
        try:
            from zhiying.kb import ingest_video as kb_ingest

            kb_r = kb_ingest(video_id)
            kb_note = f"; 入库={kb_r.get('chunks', '?')}chunks" if kb_r.get("ok") else f"; 入库失败: {kb_r.get('reason', '')[:80]}"
        except Exception as e:  # noqa: BLE001  入库失败不影响任务完成（可手动重跑 ingest）
            kb_note = f"; 入库异常: {str(e)[:80]}"

        # 上传副本清理（DR-25）：incoming 的源文件已拷入 videos/<id>/source/，副本无用
        try:
            from zhiying.paths import data_root

            incoming_root = Path(data_root() / "incoming").resolve()
            if source and Path(source).resolve().is_relative_to(incoming_root):
                Path(source).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

        set_stage(video_id, "done", detail=f"A1={r['segments']}段; 摘要={s.get('path', '')}{kb_note}")
    except Exception as e:  # noqa: BLE001
        set_stage(video_id, "failed", error=f"{type(e).__name__}: {str(e)[:200]}")


def start_async(video_id: str, quality: str = "1080", src: str | None = None, precision: str = "fast") -> None:
    """启动独立子进程执行全流程。

    daemon 线程会随 CLI 进程退出被杀（实测事故：任务永远停在 queued）；
    改用独立子进程跑同步管道，跨进程存活，task.json 为唯一状态源。
    """
    set_stage(video_id, "queued", "任务已入队", precision=precision)
    cmd = [sys.executable, "-m", "zhiying.pipeline", "--video-id", video_id,
           "--quality", quality, "--precision", precision]
    if src:
        cmd.extend(["--src", src])
    log_dir = video_dir(video_id)
    log_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    flags = 0x00000008 if sys.platform == "win32" else 0  # DETACHED_PROCESS
    proc.popen(
        cmd,
        env=env,
        stdout=open(log_dir / "pipeline.log", "w", encoding="utf-8"),
        stderr=open(log_dir / "pipeline.err.log", "w", encoding="utf-8"),
        creationflags=flags,
        close_fds=True,
    )


def resume_if_stuck(
    video_id: str,
    task: dict | None = None,
    quality: str = "480",
) -> dict:
    """卡住任务自动续跑（DR-36）。

    返回 {"resumed": bool, "reason": str, "attempt": int}。
    防护：每任务最多 AUTO_RESUME_MAX 次、两次间隔 ≥AUTO_RESUME_COOLDOWN_SEC。
    管道幂等——已完成的下载/转写/帧描述/摘要会命中缓存，因此「续跑」语义成立。
    """
    task = task if task is not None else get_task(video_id)
    if not task:
        return {"resumed": False, "reason": "无任务记录"}
    if not is_stuck(task):
        return {"resumed": False, "reason": "未卡住"}

    count = int(task.get("auto_resume_count") or 0)
    if count >= AUTO_RESUME_MAX:
        return {"resumed": False, "reason": f"已达自动续跑上限（{AUTO_RESUME_MAX} 次），请人工处理", "attempt": count}

    last = task.get("last_auto_resume_at")
    if last:
        try:
            gap = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
            if gap < AUTO_RESUME_COOLDOWN_SEC:
                return {"resumed": False, "reason": "冷却中（距上次自动续跑不足 10 分钟）", "attempt": count}
        except (ValueError, TypeError):
            pass

    from zhiying.download import load_meta

    meta = load_meta(video_id)
    src = meta.source if meta and meta.source else None
    if not src:
        return {"resumed": False, "reason": "无源信息，无法续跑", "attempt": count}

    precision = task.get("precision") or "fast"
    new_count = count + 1
    start_async(video_id, quality=quality, src=src, precision=precision)
    # 记录续跑追踪（set_stage 会保留这些字段）
    cur = get_task(video_id) or {}
    cur["auto_resume_count"] = new_count
    cur["last_auto_resume_at"] = _now_iso()
    _task_path(video_id).write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"resumed": True, "reason": "已自动续跑（已完成阶段复用缓存）", "attempt": new_count}


def run_sync(video_id: str, quality: str = "1080", src: str | None = None, precision: str = "fast") -> None:
    """同步执行（默认模式与子进程入口）。"""
    _pipeline(video_id, quality, src=src, precision=precision)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="zhiying.pipeline", description="内部：异步管道子进程")
    ap.add_argument("--video-id", required=True)
    ap.add_argument("--quality", default="1080")
    ap.add_argument("--src", default=None, help="首次处理时的原始 URL/路径")
    ap.add_argument("--precision", default="fast", choices=["fast", "precise"])
    args = ap.parse_args(argv)
    from zhiying.console import setup_console

    setup_console()
    run_sync(args.video_id, quality=args.quality, src=args.src, precision=args.precision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
