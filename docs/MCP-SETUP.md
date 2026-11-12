# MCP 接入指南（知映 zhiying）

> 一句话：**知映提供 5 个 MCP 工具**（ingest / task_status / search / ask / list_videos），
> 任何支持 MCP 的 Agent 配置一次即可在对话里直接丢视频链接、直接提问。
> 前置条件只有一个：知映后端服务已启动（端口 8600）。

## 先确定你的安装形态

| 形态 | 启动器路径 | 说明 |
|---|---|---|
| **Windows 安装器**（普通用户） | `安装目录\scripts\zhiying-mcp.cmd` | 默认装在 `%LOCALAPPDATA%\Programs\zhiying`，已内置 Python 运行时 |
| **源码部署**（开发者） | `仓库路径\scripts\zhiying-mcp.cmd` | 需先建 venv 并 `pip install -e .` |

下面示例以源码路径 `D:\projectMenu\zhiying` 为例，换成你实际的安装路径即可。
服务未启动时，MCP 工具调用会报连接失败——先用桌面图标（安装版）或 `start.cmd` 起服务。

## Windows 启动器（推荐）

两个仓都提供 `scripts\zhiying-mcp.cmd`，它替你处理 Python 路径与环境变量：

```text
D:\projectMenu\zhiying\scripts\zhiying-mcp.cmd
```

各 Agent 的 MCP 配置里 **command 直接填这个 .cmd 文件路径**即可，无需手写解释器绝对路径。

## 各 Agent 接入方式

### Claude Code（最简单，一条命令）

```bash
claude mcp add zhiying -- D:\projectMenu\zhiying\scripts\zhiying-mcp.cmd
```

验证：`claude mcp list` 应显示 zhiying（5 个工具）。

### Codex

编辑 `~/.codex/config.toml`：

```toml
[mcp_servers.zhiying]
command = "D:\\projectMenu\\zhiying\\scripts\\zhiying-mcp.cmd"
```

### OpenClaw

在 OpenClaw 配置的 MCP 客户端段添加 stdio server（与上面相同的 command）；
重启 OpenClaw 后工具进入工具目录，对话里说「用 zhiying 查一下…」即可触发。

### 通用 MCP 客户端（Cursor / 任意支持 stdio 的）

```json
{
  "mcpServers": {
    "zhiying": {
      "command": "D:\\projectMenu\\zhiying\\scripts\\zhiying-mcp.cmd"
    }
  }
}
```

## 5 个工具速览

| 工具 | 用途 | 示例话术 |
|---|---|---|
| `zhiying_ingest(url, quality?)` | 丢视频链接建处理任务 | 「帮我把这个视频入库：https://…」 |
| `zhiying_task_status(task_id)` | 查处理进度 | 「那个视频处理完了吗」 |
| `zhiying_search(query, top_k?)` | 知识库检索 | 「知识库里有没有讲调味料的内容」 |
| `zhiying_ask(question)` | RAG 问答（带时间戳引用） | 「视频里是怎么处理菠萝的？」 |
| `zhiying_list_videos()` | 列出已入库视频 | 「我库里都有哪些视频」 |

## 故障排查

| 现象 | 处置 |
|---|---|
| 工具报「API 不可达」 | 先启动后端：`python -m zhiying.api`（8600） |
| Agent 看不到工具 | 重启该 Agent；确认 command 路径存在 |
| 提示「未配置 Key」 | 检查 `.env` 的 `SILICONFLOW_API_KEY`（MCP 进程继承后端配置） |

> MCP 进程本身不持有任何 Key——它只是转发请求到后端；Key 全部在后端 `.env` 管理。
