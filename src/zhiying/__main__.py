"""zhiying CLI 入口（PRD §5.5 命令面，DR-19 CLI 五原则）。

V0.1 完整命令面：
- zhiying doctor                          环境自检（B1）
- zhiying ingest <src> [--sync]           处理视频：默认后台异步，立即返 task_id（B7）
- zhiying watch <video_id>                实时跟踪任务进度到完成（B7）
- zhiying status [video_id]               视频/任务状态（含 stage）
- zhiying transcribe <video_id>          语音转写（三级降级）
- zhiying assemble <video_id>            A1 多模态文案
- zhiying summarize <video_id> [--force] A3 结构化摘要
- zhiying retry <video_id>                从失败阶段重跑（各阶段幂等）
- zhiying open <video_id>                 打开产物目录
- zhiying config                          查看配置（Key 就绪状态）
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _cmd_doctor(_args: argparse.Namespace) -> int:
    from zhiying.doctor import run_doctor

    return run_doctor()


def _cmd_ingest(args: argparse.Namespace) -> int:
    from zhiying.console import setup_console
    from zhiying.download import detect_source
    from zhiying.pipeline import set_stage, start_async

    setup_console()
    _source_type, vid = detect_source(args.src)
    existing_hint = Path(args.src).exists() or args.src.startswith("http")
    if not existing_hint and not args.allow_unknown:
        print(f"⚠ 无法识别来源: {args.src}")
        print("  └─ 支持: B站/YouTube URL、本地文件路径；如确认无误可加 --allow-unknown")
        return 1
    set_stage(vid, "queued", "任务已创建")
    if not args.async_mode:
        # 默认同步：实测 CLI 子进程会被父会话回收，后台异步不可靠（V0.2 服务层提供真正队列）
        from zhiying.pipeline import get_task, run_sync

        run_sync(vid, quality=args.quality, src=args.src, precision=args.precision)
        t = get_task(vid)
        ok = bool(t and t.get("stage") == "done")
        mark = "✅" if ok else "❌"
        detail = t.get("detail", "") if t else ""
        err = f"\n   错误: {t.get('error', '')[:300]}" if t and t.get("stage") == "failed" else ""
        print(f"{mark} video_id={vid} stage={t.get('stage') if t else 'unknown'}")
        if detail:
            print(f"   {detail}")
        if err:
            print(err)
            print(f"   重试: python -m zhiying retry {vid}")
        else:
            print(f"   产物: python -m zhiying open {vid}")
        return 0 if ok else 1
    start_async(vid, quality=args.quality, src=args.src, precision=args.precision)
    print(f"✅ 任务已创建（后台子进程）: video_id={vid}")
    print("   ⚠ 注意：本环境 CLI 退出可能回收子进程；如需可靠后台执行请用 V0.2 服务层")
    print(f"   跟踪: python -m zhiying watch {vid}")
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    import time
    from datetime import datetime, timezone

    from zhiying.console import setup_console
    from zhiying.pipeline import get_task
    from zhiying.paths import video_dir

    setup_console()
    vid = args.video_id
    if not video_dir(vid).exists():
        print(f"未找到任务 {vid}")
        return 1
    # 无 task.json 的历史视频（早期直接命令处理）：从产物推断完成状态
    if get_task(vid) is None:
        summary = video_dir(vid) / "summary.json"
        if summary.exists():
            print(f"✅ 该视频已完成（无任务记录，但有摘要产物）")
            print(f"   产物: {video_dir(vid)}")
            return 0
        print(f"⚠ 该视频无任务记录，也无可识别的完成产物")
        print(f"   重建任务: python -m zhiying retry {vid}")
        return 1
    last = None
    spin = "|/-\\"
    i = 0
    while True:
        t = get_task(vid) or {}
        stage = t.get("stage", "unknown")
        if stage != last:
            if last is not None:
                print()
            mark = {"done": "✅", "failed": "❌"}.get(stage, "⏳")
            print(f"{mark} [{stage}] {t.get('detail', '')}")
            last = stage
        if stage in ("done", "failed"):
            if stage == "failed":
                print(f"   错误: {t.get('error', '')[:300]}")
                print(f"   重试: python -m zhiying retry {vid}")
                return 1
            print(f"   产物: {video_dir(vid)}")
            print(f"   查看: python -m zhiying open {vid}")
            return 0
        # 陈旧检测：task.json 心跳超过 10 分钟未更新且不在 queued，提示可能进程已死
        updated = t.get("updated_at")
        if updated and stage != "queued":
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).total_seconds()
                if age > 600:
                    print(f"\n⚠ 任务心跳已停止 {int(age/60)} 分钟（stage={stage}），管道进程可能已异常退出")
                    print("   处置: python -m zhiying retry " + vid)
                    return 2
            except ValueError:
                pass
        # 总体超时保护
        if args.timeout and (i * args.interval) > args.timeout:
            print(f"\n⚠ watch 超过 {args.timeout}s 未完成，退出监控（任务仍在后台运行）")
            print(f"   继续跟踪: python -m zhiying status {vid}")
            return 2
        print(f"\r   处理中 {spin[i % 4]}", end="", flush=True)
        i += 1
        time.sleep(args.interval)


def _fmt_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.1f}GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f}MB"
    if n >= 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n}B"


def _cmd_status(args: argparse.Namespace) -> int:
    from zhiying.console import setup_console
    from zhiying.download import load_meta
    from zhiying.paths import data_root
    from zhiying.pipeline import get_task

    setup_console()
    vdir = data_root() / "videos"
    if args.video_id:
        meta = load_meta(args.video_id)
        if not meta:
            print(f"未找到 {args.video_id}")
            return 1
        for k, v in vars(meta).items():
            if v not in ("", 0, None, {}):
                print(f"  {k:<14} {v}")
        t = get_task(args.video_id)
        if t:
            print(f"  {'task_stage':<14} {t.get('stage')} {('— ' + t.get('detail', '')) if t.get('detail') else ''}")
            if t.get("stage") == "failed" and t.get("error"):
                print(f"  {'task_error':<14} {t['error'][:200]}")
        return 0
    metas = sorted(vdir.glob("*/meta.json")) if vdir.exists() else []
    if not metas:
        print("(暂无视频记录)")
        return 0
    for m in metas:
        try:
            meta = load_meta(m.parent.name)
            if not meta:
                continue
            t = get_task(m.parent.name) or {}
            stage = t.get("stage", "-")
            mark = {"done": "✅", "failed": "❌"}.get(stage, "⏳")
            size = _fmt_size(meta.filesize) if meta.filesize else "-"
            title = (meta.title or meta.source[:40])[:38]
            print(f"{mark} {meta.video_id:<24} {size:>8} [{stage:<11}] {title}")
        except Exception:  # noqa: BLE001
            continue
    return 0


def _cmd_retry(args: argparse.Namespace) -> int:
    from zhiying.console import setup_console
    from zhiying.pipeline import get_task, start_async
    from zhiying.paths import video_dir

    setup_console()
    vid = args.video_id
    if not video_dir(vid).exists():
        print(f"未找到任务 {vid}")
        return 1
    t = get_task(vid)
    if not t:
        # 历史视频无 task.json：新建 queued 状态并启动子进程
        print(f"ℹ 该视频无历史任务记录，重新启动全流程")
        start_async(vid, quality=args.quality, precision=args.precision)
        print(f"⏳ 已启动，跟踪: python -m zhiying watch {vid}")
        return 0
    if t.get("stage") == "done":
        print(f"ℹ 任务已完成，无需重试（各阶段幂等缓存）")
        return 0
    print(f" 上次失败于 [{t.get('stage')}]，从该阶段重跑（已完成产物复用）")
    start_async(vid, quality=args.quality, precision=args.precision)
    print(f"⏳ 已重启，跟踪: python -m zhiying watch {vid}")
    return 0


def _cmd_open(args: argparse.Namespace) -> int:
    from zhiying.console import setup_console
    from zhiying.paths import video_dir

    setup_console()
    d = video_dir(args.video_id)
    if not d.exists():
        print(f"未找到 {args.video_id}")
        return 1
    print(f"产物目录: {d}")
    for f in sorted(d.rglob("*")):
        if f.is_file() and f.suffix.lower() in {".md", ".json", ".jsonl", ".mp4", ".wav", ".jpg"}:
            rel = f.relative_to(d)
            print(f"  {rel}  ({_fmt_size(f.stat().st_size)})")
    if sys.platform == "win32":
        subprocess.run(["explorer", str(d)], check=False)
    else:
        subprocess.run(["xdg-open", str(d)], check=False)
    return 0


def _cmd_config(_args: argparse.Namespace) -> int:
    from zhiying.console import setup_console
    from zhiying.envkeys import getenv

    setup_console()
    print("知映配置状态")
    print("=" * 40)
    sf = (getenv("SILICONFLOW_API_KEY") or "").strip()
    lc = (getenv("LONGCAT_API_KEY") or "").strip()
    pg = getenv("ZHIYING_PG_PASSWORD") or getenv("PGPASSWORD")
    print(f"{'✅' if sf else '❌'} SILICONFLOW_API_KEY  {'已配置' if sf else '未配置'}（转写/VLM/摘要）")
    print(f"{'✅' if lc else '⏳'} LONGCAT_API_KEY     {'已配置' if lc else '未配置'}（VLM 备选，当前未激活）")
    print(f"{'✅' if pg else '⏳'} ZHIYING_PG_PASSWORD {'已配置' if pg else '未配置'}（知识库，V0.2）")
    print()
    print("VLM: ZHIYING_VLM_PROVIDER=siliconflow（默认）| longcat（Key 激活后切换）")
    print("转写: 平台字幕 → SenseVoice → 本地 Whisper 自动降级")
    print("=" * 40)
    return 0


def _cmd_transcribe(args: argparse.Namespace) -> int:
    from zhiying.console import setup_console
    from zhiying.transcribe import transcribe

    setup_console()
    r = transcribe(args.video_id)
    level = r.get("level")
    if r.get("path"):
        print(f"✅ 转写完成（级别: {level}）")
        print(f"   产物: {r['path']}")
        _print_transcript_preview(r["path"])
        return 0
    print(f"❌ 转写失败（级别: {level}）")
    if r.get("note"):
        print(f"   {r['note']}")
    return 1


def _print_transcript_preview(path: str, n: int = 3) -> None:
    import json

    lines = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= n:
                break
            d = json.loads(line)
            lines.append(f"   [{d['start_ts']:.0f}s-{d['end_ts']:.0f}s] {d['text'][:70]}")
    total = sum(1 for _ in open(path, encoding="utf-8"))
    print(f"   共 {total} 段，前 {len(lines)} 段：")
    for ln in lines:
        print(ln)


def _cmd_assemble(args: argparse.Namespace) -> int:
    from zhiying.assemble import assemble
    from zhiying.console import setup_console

    setup_console()
    r = assemble(args.video_id, max_frames=args.max_frames, precision=args.precision)
    if r.get("ok"):
        print(f"✅ A1 多模态文案产出完成，{r['segments']} 段")
        print(f"   MD: {r['md']}")
        print(f"   JSONL: {r['jsonl']}")
        return 0
    print(f"❌ {r.get('reason')}")
    return 1


def _cmd_summarize(args: argparse.Namespace) -> int:
    from zhiying.assemble import summarize
    from zhiying.console import setup_console

    setup_console()
    r = summarize(args.video_id, force=args.force, precision=args.precision)
    if r.get("ok"):
        cached = "（缓存）" if r.get("cached") else ""
        print(f"✅ A3 摘要产出{cached}：{r['path']}")
        print(f"   主题: {' / '.join(r.get('topics', []))}")
        print(f"   摘要: {r.get('summary_text', '')[:150]}...")
        print(f"   要点: {len(r.get('key_points', []))} 条")
        return 0
    print(f"❌ {r.get('reason')}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zhiying", description="知映 — 视频知识库 CLI（V0.1）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="环境自检")
    sub.add_parser("config", help="查看配置与 Key 状态")

    p_ing = sub.add_parser("ingest", help="处理一条视频（默认前台同步全流程）")
    p_ing.add_argument("src", help="视频 URL 或本地文件路径")
    p_ing.add_argument("--quality", default="1080", help="最高清晰度（默认 1080）")
    p_ing.add_argument("--precision", default="fast", choices=["fast", "precise"],
                       help="画面识别精度：fast=≥10min 走 seek 采样（秒级）；precise=强制逐帧场景检测（长视频 10min+）")
    p_ing.add_argument("--async", dest="async_mode", action="store_true",
                       help="后台子进程模式（本环境不可靠，V0.2 服务层替代）")
    p_ing.add_argument("--allow-unknown", action="store_true", help="允许未识别的来源类型")

    p_w = sub.add_parser("watch", help="实时跟踪任务进度")
    p_w.add_argument("video_id", help="video_id")
    p_w.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒（默认 2）")
    p_w.add_argument("--timeout", type=int, default=3600, help="总监控时长上限秒（默认 3600，0=不限）")

    p_st = sub.add_parser("status", help="查看视频/任务状态")
    p_st.add_argument("video_id", nargs="?", help="指定 video_id；缺省列出全部")

    p_rt = sub.add_parser("retry", help="从失败阶段重跑（已完成产物复用）")
    p_rt.add_argument("video_id", help="video_id")
    p_rt.add_argument("--quality", default="1080")
    p_rt.add_argument("--precision", default="fast", choices=["fast", "precise"])

    p_op = sub.add_parser("open", help="打开产物目录")
    p_op.add_argument("video_id", help="video_id")

    p_tr = sub.add_parser("transcribe", help="语音转写（三级降级）")
    p_tr.add_argument("video_id", help="已 ingest 的 video_id")

    p_as = sub.add_parser("assemble", help="A1 多模态文案（md + jsonl 同源）")
    p_as.add_argument("video_id", help="已 transcribe 的 video_id")
    p_as.add_argument("--max-frames", type=int, default=20, help="最大帧数（默认 20）")
    p_as.add_argument("--precision", default="fast", choices=["fast", "precise"],
                      help="画面识别精度（DR-22）：影响帧缓存命中与提取路由")

    p_sum = sub.add_parser("summarize", help="A3 结构化摘要（缓存幂等）")
    p_sum.add_argument("video_id", help="已 assemble 的 video_id")
    p_sum.add_argument("--force", action="store_true", help="忽略缓存重新生成")
    p_sum.add_argument("--precision", default="fast", choices=["fast", "precise"])

    args = parser.parse_args(argv)
    return {
        "doctor": _cmd_doctor,
        "config": _cmd_config,
        "ingest": _cmd_ingest,
        "watch": _cmd_watch,
        "status": _cmd_status,
        "retry": _cmd_retry,
        "open": _cmd_open,
        "transcribe": _cmd_transcribe,
        "assemble": _cmd_assemble,
        "summarize": _cmd_summarize,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
