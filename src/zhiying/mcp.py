"""知映 MCP Server（V0.2 FR-305 / PRD §5.6）。

薄包装 REST API（§5.5 唯一契约底座），暴露 5 个工具供各 Agent 发现与调用：
    zhiying_ingest(url, mode?)        提交处理任务
    zhiying_task_status(task_id?)     查任务状态
    zhiying_search(query, top_k?)     知识库检索
    zhiying_ask(question)             RAG 问答（A4 结构化回答）
    zhiying_list_videos(topic?)       知识库视频清单

接入（三端官方入口）：
    OpenClaw:    MCP 客户端配置
    Claude Code: claude mcp add zhiying -- python -m zhiying.mcp
    Codex:       config.toml [mcp_servers.zhiying]

边界（DR-11）：Agent 是客户端不是执行者；stdio 传输，单机部署默认。
"""

from __future__ import annotations

import json
import os

import requests
from mcp.server.mcpserver import MCPServer

API_BASE = os.environ.get("ZHIYING_API_BASE", "http://127.0.0.1:8600")
TIMEOUT = 300

mcp = MCPServer("zhiying")


def _call(method: str, path: str, body: dict | None = None, timeout: int = TIMEOUT) -> dict:
    url = f"{API_BASE}{path}"
    try:
        if method == "GET":
            r = requests.get(url, params=body, timeout=timeout)
        else:
            r = requests.post(url, json=body, timeout=timeout)
        if r.status_code == 409:
            d = r.json().get("detail", {})
            return {"status": "already_exists", "task_id": d.get("task_id"), "stage": d.get("stage"),
                    "hint": "该视频已在知识库中或正在处理，用 zhiying_task_status 查看进度"}
        if r.status_code >= 400:
            return {"status": "error", "http": r.status_code, "detail": r.text[:300]}
        return r.json()
    except requests.RequestException as e:
        return {"status": "error", "detail": f"API 不可达: {e}", "hint": "先启动服务: python -m zhiying.api"}


@mcp.tool()
def zhiying_ingest(url: str, quality: str = "480") -> str:
    """提交视频处理任务（下载→转写→画面识别→多模态文案→摘要→入库）。

    Args:
        url: 视频 URL（B站/YouTube）或本地文件路径
        quality: 最高清晰度（默认 480，可 1080）
    """
    r = _call("POST", "/api/tasks", {"source": url, "quality": quality})
    return json.dumps(r, ensure_ascii=False)


@mcp.tool()
def zhiying_task_status(task_id: str) -> str:
    """查询处理任务的状态与阶段。

    Args:
        task_id: ingest 返回的 video_id
    """
    r = _call("GET", f"/api/tasks/{task_id}")
    return json.dumps(r, ensure_ascii=False)


@mcp.tool()
def zhiying_search(query: str, top_k: int = 5) -> str:
    """知识库检索：跨视频查找相关内容片段（带时间戳，可回跳原视频）。

    Args:
        query: 检索问题或关键词
        top_k: 返回条数（默认 5）
    """
    r = _call("POST", "/api/search", {"query": query, "top_k": top_k}, timeout=120)
    return json.dumps(r, ensure_ascii=False)


@mcp.tool()
def zhiying_ask(question: str, top_k: int = 5) -> str:
    """知识库问答：基于已入库视频回答问题，答案带来源引用（视频名+时间戳）。

    Args:
        question: 用户问题
        top_k: 检索参考条数（默认 5）
    """
    r = _call("POST", "/api/ask", {"question": question, "top_k": top_k}, timeout=300)
    return json.dumps(r, ensure_ascii=False)


@mcp.tool()
def zhiying_distill(video_id: str, force: bool = False) -> str:
    """skill 蒸馏：把已入库视频的多模态内容蒸馏成可挂载的 SKILL.md 能力包。

    Args:
        video_id: 已完成处理的 video_id
        force: 忽略缓存重新蒸馏
    """
    import requests as _rq

    try:
        r = _rq.post(f"{API_BASE}/api/distill/{video_id}", json={"force": force}, timeout=600)
        if r.status_code >= 400:
            return json.dumps({"status": "error", "http": r.status_code, "detail": r.text[:300]}, ensure_ascii=False)
        return json.dumps(r.json(), ensure_ascii=False)
    except _rq.RequestException as e:
        return json.dumps({"status": "error", "detail": f"API 不可达: {e}"}, ensure_ascii=False)


@mcp.tool()
def zhiying_list_videos() -> str:
    """列出知识库中已入库的全部视频（含摘要与主题标签）。"""
    r = _call("GET", "/api/videos", timeout=60)
    return json.dumps(r, ensure_ascii=False)


def main() -> int:
    mcp.run()  # stdio 传输（默认；mcp 2.x MCPServer）
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
