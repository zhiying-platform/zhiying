# 知映 zhiying

把「收藏夹里吃灰的视频」变成「可检索、可问答、可溯源到时间点的视频知识库」。

输入视频链接（B站 / YouTube / 本地文件），自动完成 **下载 → 语音转写 → 画面识别 → 多模态文案对齐 → 结构化摘要**，产出可入库、可检索、答案可回跳原视频时间点的知识资产。

> **当前版本：V0.2（知识库与服务层）** — 产品规划见 [docs/PRD.md](docs/PRD.md)，实施记录见 [docs/plan/V0.1-PLAN.md](docs/plan/V0.1-PLAN.md)。

## 特性

- 🎬 **多源接入**：B站 / YouTube / 本地文件；1080p 默认，断点续传，失败片段级重跑
- 🎙️ **三级转写降级**：平台字幕 → 硅基流动 SenseVoiceSmall → 本地 Whisper（自动降级，保底可用）
- 👁️ **VLM 画面识别**：看懂 PPT / 代码 / 图表，OCR 屏幕文字（适配器架构：LongCat-2.5 默认首选，SiliconFlow Qwen3-VL 备选，只改配置切换）
- 🕐 **时间戳溯源**：口播、画面事实、屏幕文字全部挂时间轴，答案可回跳原视频对应位置
- 📦 **双形态产物**：人读的 `multimodal_transcript.md` + 机器可读的 `transcript.multimodal.jsonl`（同源生成，不分叉）
- 🗄️ **知识库契约已冻结**：PostgreSQL + pgvector 表结构 V1（videos / segments / chunks），V0.2 实现检索问答

## 快速开始

### 1. 环境准备

```bash
# Python 3.10+ 与 venv
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
```

ffmpeg 免安装：`imageio-ffmpeg` 自带二进制（自动探测）；系统已装 ffmpeg 也可。

### 2. 配置

```bash
cp .env.example .env    # 填入 SILICONFLOW_API_KEY（必填）等
```

或直接设置环境变量。配置命名与端口约定参照 gewu 项目（DB 15432 / Redis 16379）。

### 3. 环境自检

```bash
.venv\Scripts\python -m zhiying doctor    # 依赖/版本/Key 逐项检查
.venv\Scripts\python -m zhiying config    # 配置状态一览
```

### 4. 处理一条视频（端到端）

```bash
.venv\Scripts\python -m zhiying ingest "https://www.bilibili.com/video/BVxxxx/"
# 全流程：下载 → 转写 → 画面识别 → 多模态文案 → 摘要，完成后自动提示产物位置
```

单阶段命令（可独立使用，均有缓存幂等）：

```bash
python -m zhiying transcribe BVxxxx    # 语音转写（三级降级）
python -m zhiying assemble   BVxxxx    # A1 多模态文案（md + jsonl）
python -m zhiying summarize  BVxxxx    # A3 摘要 + 主题标签 + 溯源要点
python -m zhiying status    [BVxxxx]   # 视频/任务状态
python -m zhiying open      BVxxxx     # 打开产物目录
python -m zhiying retry     BVxxxx     # 从失败阶段重跑
```

### 5. 知识库与服务（V0.2）

```bash
# 数据库（pgvector + Redis）
docker compose up -d

# 首次建表（schema + 迁移，幂等）
.venv\Scripts\python -m zhiying.storage.init_db
.venv\Scripts\python -m zhiying.storage.migrate

# 启动 API 服务
.venv\Scripts\python -m zhiying.api        # http://127.0.0.1:8600  (docs: /docs)
```

API 端点：
| 端点 | 说明 |
|---|---|
| `POST /api/tasks` | 提交处理任务（202；已完成/处理中返回 409 + 既有 task_id，幂等） |
| `GET /api/tasks` · `GET /api/tasks/{id}` | 任务列表/详情 |
| `POST /api/search` | 知识库检索（向量 + 全文混合，带时间戳） |
| `POST /api/ask` | RAG 问答（答案强制带引用，无据可答显式声明） |
| `GET /api/videos` | 知识库视频清单（含摘要与主题标签） |

### 6. Agent 接入（V0.2 MCP）

启动 MCP Server（stdio 传输，薄包装 REST API）：

```bash
.venv\Scripts\python -m zhiying.mcp
```

暴露 5 个工具：`zhiying_ingest` / `zhiying_task_status` / `zhiying_search` / `zhiying_ask` / `zhiying_list_videos`

接入方式：
- **OpenClaw**：MCP 客户端配置（对话里直接丢视频链接、提问）
- **Claude Code**：`claude mcp add zhiying -- python -m zhiying.mcp`
- **Codex**：`config.toml` 的 `mcp_servers.zhiying`

## 产物结构

```
data/videos/<video_id>/
├── meta.json                          # 视频元信息（标题/时长/UP主）
├── task.json                          # 管道任务状态（queued→…→done/failed）
├── source/                            # 原视频（1080p，断点续传）
├── audio/audio.wav                    # 16k 单声道（转写输入）
├── frames/                            # 关键帧 + VLM 描述缓存
│   ├── scene_000.jpg
│   └── descriptions.json
├── transcript/
│   ├── transcript.jsonl               # 纯语音转写（带时间戳与来源级别）
│   ├── multimodal_transcript.md       # ★ A1 人读主产物
│   └── transcript.multimodal.jsonl    # ★ A1 机器可读（同源生成）
└── summary.json                       # ★ A3 摘要 + 主题标签 + 溯源要点
```

## 架构（V0.1）

```
ingest → download（yt-dlp 封装）
       → transcribe（平台字幕 → SenseVoice → Whisper 三级降级）
       → frames（PySceneDetect 关键帧）
       → vlm（适配器：SiliconFlow Qwen3-VL / LongCat-2.5，base64 内联传图）
       → assemble（时间轴对齐 → A1 双形态）
       → summarize（文本 LLM → A3）
```

设计原则：所有外部依赖（转写引擎 / VLM / 文本 LLM / 向量库 / 导出器）均为适配器接口，切换供应商只改配置不改代码（PRD FR-105 / DR-16）。

## 版本路线

| 版本 | 内容 | 状态 |
|---|---|---|
| V0.1 | CLI 最小闭环（单条视频端到端） | ✅ 已完成 |
| V0.2 | 知识库入库 + 检索 + FastAPI + RAG 问答 + MCP 接入 | ✅ 已完成 |
| V0.3 | Web 前端（任务台 / 知识库浏览 / 问答界面） | ✅ 当前（前端仓 [zhiying-web](https://github.com/zhiying-platform/zhiying-web)）|
| V1.0 | 产品化（触发条件制） | 规划中 |

## 相关仓库

| 仓 | 内容 |
|---|---|
| [zhiying](https://github.com/zhiying-platform/zhiying)（本仓） | Python 管道 + 知识库 + FastAPI + MCP |
| [zhiying-web](https://github.com/zhiying-platform/zhiying-web) | Vue3 前端（任务台 / 知识库 / 问答） |

## License

MIT
