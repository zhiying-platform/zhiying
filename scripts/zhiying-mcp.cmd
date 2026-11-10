@echo off
rem 知映 MCP Server 启动器（stdio 传输）
rem 用途：各 Agent 工具的 MCP 接入入口，配置时指向本文件即可。
rem   Claude Code:  claude mcp add zhiying -- D:\projectMenu\zhiying\scripts\zhiying-mcp.cmd
rem   Codex:        config.toml [mcp_servers.zhiying] command 同上
rem 前置：后端 API 已启动（python -m zhiying.api，默认 127.0.0.1:8600）
set "PYTHONPATH=%~dp0..\src"
"%~dp0..\.venv\Scripts\python.exe" -m zhiying.mcp
