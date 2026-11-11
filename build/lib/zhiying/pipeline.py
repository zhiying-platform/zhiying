"""管道编排与任务状态（B7：ingest 异步化 + watch/retry，PRD DR-19）。

任务状态落盘 <data>/videos/<id>/task.json：
    {"stage": queued|downloading|transcribing|visual|summarizing|done|failed,
     "detail": 当前阶段说明, "error": 失败原因, "updated_at": iso}

ingest 默认同步执行全流程（下载→转写→组装→摘要）；--async 启动独立子进程。
watch 轮询 task.json 直到 done/failed；retry 只重跑（各阶段内部幂等）。
precision（DR-22）：画面识别精度两档 fast/precise，全链路穿透。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from zhiying.paths import video_dir

STAGES = ("queued", "downloading", "transcribing", "visual", "summarizing", "done", "failed")


def _task_path(video_id: str) -> Path:
    return video_dir(video_id) / "task.json"


def set_stage(video_id: str, stage: str, detail: str = "", error: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _task_path(video_id).write_text(
        json.dumps(
            {"stage": stage, "detail": detail, "error": error, "updated_at": now},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def get_task(video_id: str) -> dict | None:
    p = _task_path(video_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _pipeline(video_id: str, quality: str, src: str | None = None, precision: str = "fast") -> None:
    """全流程（同步或子进程内执行）；各阶段内部幂等，retry 直接重跑即可。

    src：首次 ingest 时 meta.json 尚未生成（download 成功后才写），
    由调用方传入原始 URL/路径兜底；retry 场景 meta 已存在，src 可缺省。
    precision：画面识别精度（DR-22 两档：fast/precise）。
    """
    from zhiying.assemble import assemble, summarize
    from zhiying.download import download, load_meta
    from zhiying.transcribe import transcribe

    try:
        set_stage(video_id, "downloading", "下载/复用源视频")
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
            set_stage(video_id, "failed", error="转写失败（全部通道）")
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
        try:
            from zhiying.kb import ingest_video as kb_ingest

            kb_r = kb_ingest(video_id)
            kb_note = f"; 入库={kb_r.get('chunks', '?')}chunks" if kb_r.get("ok") else f"; 入库失败: {kb_r.get('reason', '')[:80]}"
        except Exception as e:  # noqa: BLE001  入库失败不影响任务完成（可手动重跑 ingest）
            kb_note = f"; 入库异常: {str(e)[:80]}"

        # 上传副本清理（DR-25）：incoming 的源文件已拷入 videos/<id>/source/，副本无用
        try:
            incoming_root = Path(data_root() / "incoming").resolve()
            if source and Path(source).resolve().is_relative_to(incoming_root):
                Path(source).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

        set_stage(video_id, "done", detail=f"A1={r['segments']}段; 摘要={s.get('path', '')}{kb_note}")
    except Exception as e:  # noqa: BLE001
        set_stage(video_id, "failed", error=f"{type(e).__name__}: {str(e)[:200]}")


def start_async(video_id: str, quality: str = "1080", src: str | None = None, precision: str = "fast") -> None:
    """启动独立子进程执行全流程（--async 模式）。

    daemon 线程会随 CLI 进程退出被杀（实测事故：任务永远停在 queued）；
    改用独立子进程跑同步管道，跨进程存活，task.json 为唯一状态源。
    注意：exec 会话环境可能回收 detached 子进程（实测），生产异步走 V0.3 服务层。
    """
    set_stage(video_id, "queued", "任务已入队")
    cmd = [sys.executable, "-m", "zhiying.pipeline", "--video-id", video_id,
           "--quality", quality, "--precision", precision]
    if src:
        cmd.extend(["--src", src])
    # 子进程日志：后台运行时保留诊断信息
    log_dir = video_dir(video_id)
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = log_dir / "pipeline.log"
    err_log = log_dir / "pipeline.err.log"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    flags = 0x00000008 if sys.platform == "win32" else 0  # DETACHED_PROCESS
    subprocess.Popen(
        cmd,
        env=env,
        stdout=open(out_log, "w", encoding="utf-8"),
        stderr=open(err_log, "w", encoding="utf-8"),
        creationflags=flags,
        close_fds=True,
    )


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
