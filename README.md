# 知映 zhiying

把「收藏夹里吃灰的视频」变成「可检索、可问答、可溯源到时间点的视频知识库」。

输入视频链接（B站 / YouTube / 本地文件），自动完成 **下载 → 语音转写 → 画面识别 → 多模态文案对齐 → 结构化摘要 → 知识库入库**，最终支撑「提问即答、答必溯源到视频时间点」的使用体验。

> **当前版本：V1.2（Windows 一键安装器）** — 产品规划见 [docs/PRD.md](docs/PRD.md)，各版本实施记录见 [docs/plan/](docs/plan/)。

## 四种使用方式（按方便程度排序）

| 方式 | 适合谁 | 入口 |
|---|---|---|
| **📦 Windows 安装器** | 普通用户（零环境） | 双击 `zhiying-setup.exe`，装完双击桌面图标即用，服务常驻托盘 |
| **🌐 Web 界面** | 日常使用 | 浏览器打开 `http://127.0.0.1:8600`（Docker 部署自带，无需额外启动） |
| **🤖 Agent 对话**（MCP） | AI 工具重度用户 | 对话里直接丢链接、直接提问（见 [docs/MCP-SETUP.md](docs/MCP-SETUP.md)） |
| **⌨️ CLI** | 脚本/批量场景 | `zhiying ingest <url>` |

> macOS 用户：官方 `.dmg` 暂缓（PostgreSQL/pgvector 无 macOS 预编译包），请用 Docker 或本地 Python 路径。

## 快速开始（Windows 安装器，最省事）

双击 `zhiying-setup.exe` → 中文向导选组件（完整含知识库 / 精简纯 md）→ 装完双击桌面「知映 zhiying」。

- 服务以**托盘图标**常驻（任务栏右下角），关浏览器服务继续运行
- 右键托盘「退出」才停止服务；数据在 `%APPDATA%\zhiying`，卸载不丢
- 无需安装 Python / PostgreSQL / Docker，完全离线

## 快速开始（Docker 一键，开发者推荐）

```bash
# 1) 配置（必填 2 项：DB 密码 + 模型 Key）
cp .env.example .env

# 2) 构建前端产物（首次）
cd ../zhiying-web && npm ci && npm run build && cd ../zhiying

# 3) 起全套（后端 + PostgreSQL + Redis + 前端托管）
docker compose up -d
```

浏览器打开 **http://127.0.0.1:8600** 即用。详细步骤与排错见 [docs/DEPLOY.md](docs/DEPLOY.md)。

## 特性

- 🎬 **多源接入**：B站 / YouTube / 本地文件上传 / 批量导入；断点续传，失败片段级重跑
- 🎙️ **三级转写降级**：平台字幕 → 硅基流动 SenseVoiceSmall → 本地 Whisper（自动降级，保底可用）
- 👁️ **VLM 画面识别**：看懂 PPT / 代码 / 图表，OCR 屏幕文字（LongCat-2.5 默认，SiliconFlow Qwen3-VL 备选）
- ⚡ **精度两档**：快速（长视频秒级）/ 精细（逐帧场景检测），交互指定（DR-22）
- 🕐 **时间戳溯源**：答案带引用角标，点击跳转原视频对应时间点（DR-24）
- 🗄️ **知识库**：PostgreSQL + pgvector 向量检索 + jieba/tsvector 全文，混合排序
- 🤖 **Agent 原生**：MCP Server 暴露 5 个工具，Claude Code / Codex / OpenClaw 一条配置接入
- 🔒 **隐私**：数据全部本地（`ZHIYING_DATA` 可自定义路径）；Key 只在后端 `.env`，前端/Agent 不接触

## 本地 Python 部署

```bash
python -m venv .venv
.venv\Scripts\pip install -e .            # 含 console scripts
cp .env.example .env                      # 填 Key
.venv\Scripts\zhiying doctor              # 环境自检
.venv\Scripts\zhiying-api                 # 起服务
```

CLI 全命令（均有缓存幂等）：

```bash
zhiying ingest <url> [--precision=fast|precise]   # 端到端处理
zhiying status [video_id]                          # 状态
zhiying retry  <video_id>                          # 失败重跑
zhiying open   <video_id>                          # 打开产物目录
zhiying transcribe / assemble / summarize <id>     # 单阶段
zhiying config                                     # 配置一览
zhiying doctor                                     # 环境自检
```

## MCP 接入（Agent 对话即用）

```bash
# Claude Code 一条命令
claude mcp add zhiying -- D:\projectMenu\zhiying\scripts\zhiying-mcp.cmd
```

接入后对话里直接说：「帮我把这个视频入库：<链接>」「视频里是怎么处理菠萝的？」
完整指南（Codex / OpenClaw / 通用客户端）见 [docs/MCP-SETUP.md](docs/MCP-SETUP.md)。

## 产物结构

```
<data>/videos/<video_id>/
├── meta.json / task.json              # 元信息与任务状态
├── source/                            # 源视频（保留，支持重处理）
├── audio/ · frames/                   # 音频与关键帧（VLM 描述缓存）
├── transcript/
│   ├── multimodal_transcript.md       # ★ A1 人读主产物
│   └── transcript.multimodal.jsonl    # ★ A1 机器可读（同源生成）
└── summary.json                       # ★ A3 摘要 + 主题标签 + 溯源要点
```

## 架构

```
Web / Agent(MCP) / CLI
        ↓ REST API (FastAPI :8600)
  download(yt-dlp) → transcribe(字幕→SenseVoice→Whisper)
  → frames(PySceneDetect/seek) → vlm(LongCat/SiliconFlow 适配器)
  → assemble(A1 双形态) → summarize(A3) → kb(PG+pgvector 入库)
        ↓
  检索(向量+全文) → RAG 问答(A4 引用深链)
```

设计原则：转写引擎 / VLM / 文本 LLM / 向量库 / 导出器全部为适配器接口，切换供应商只改配置不改代码（PRD FR-105 / DR-16 / DR-20）。

## 版本路线

| 版本 | 内容 | 状态 |
|---|---|---|
| V0.1 | CLI 最小闭环 | ✅ |
| V0.2 | 知识库入库 + 检索 + FastAPI + RAG 问答 + MCP | ✅ |
| V0.3 | Web 前端（[zhiying-web](https://github.com/zhiying-platform/zhiying-web)） | ✅ |
| V1.0 | 产品化：打包 / 镜像 / 编排 / 部署文档 / MCP 接入指南 | ✅ |
| V1.1 | 脚本安装器（install/start/pg-setup 三件套） | ✅ |
| V1.2 | Windows 一键安装器：exe 图形向导 + 托盘常驻 + 卸载数据保护 | ✅ 当前 |

## 相关仓库

| 仓 | 内容 |
|---|---|
| [zhiying](https://github.com/zhiying-platform/zhiying)（本仓） | Python 管道 + 知识库 + FastAPI + MCP + Docker |
| [zhiying-web](https://github.com/zhiying-platform/zhiying-web) | Vue3 前端（任务台 / 知识库 / 问答） |

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/PRD.md](docs/PRD.md) | 产品需求与决策记录（DR-1~DR-42） |
| [docs/DEPLOY.md](docs/DEPLOY.md) | 部署指南（Windows 安装器 / Docker 一键 / 本地直装 / 排错表） |
| [docs/MCP-SETUP.md](docs/MCP-SETUP.md) | MCP 接入指南（四种 Agent） |
| [docs/plan/](docs/plan/) | 各版本实施记录（V0.1–V1.2） |

## License

MIT
