# 部署指南（V1.0 产品化）

> 两条部署路径：**A. Docker 一键（推荐）** / **B. 本地 Python 直装**。
> 两种方式最终都提供：Web 界面（浏览器）+ REST API + MCP 接入（任一 Agent）。

---

## A. Docker 一键部署（推荐）

### 前置

- Docker Desktop / Docker Engine ≥ 24
- 首次部署需构建前端产物（Node 18+）

### 三步启动

```bash
# 1) 配置（只需填 2 个必填项）
cd D:\projectMenu\zhiying
cp .env.example .env
#   必填：ZHIYING_DB_PASSWORD（任意强密码）、SILICONFLOW_API_KEY 或 LONGCAT_API_KEY

# 2) 构建前端（产物被容器只读挂载）
cd ..\zhiying-web && npm ci && npm run build && cd ..\zhiying

# 3) 起全套（后端 + PostgreSQL + Redis）
docker compose up -d
```

### 首次初始化（仅一次）

```bash
docker compose exec zhiying-server python -m zhiying.storage.init_db
docker compose exec zhiying-server python -m zhiying.storage.migrate
```

### 访问

| 入口 | 地址 |
|---|---|
| **Web 界面** | http://127.0.0.1:8600 |
| API 文档（Swagger） | http://127.0.0.1:8600/docs |
| 健康检查 | http://127.0.0.1:8600/api/health |

### 国内网络说明

Dockerfile 默认用清华 PyPI 源。海外部署可在 `.env` 覆盖：

```bash
PIP_INDEX_URL=https://pypi.org/simple
PIP_TRUSTED_HOST=pypi.org
```

### 数据持久化

| Volume | 内容 |
|---|---|
| `zhiying-data` | 源视频、转写、关键帧、摘要（**换容器不丢**） |
| `zhiying-pgdata` | 知识库（videos/segments/chunks + 向量） |
| `zhiying-redisdata` | 队列数据（预留） |

备份：

```bash
docker run --rm -v zhiying-data:/data -v %CD%:/backup alpine tar czf /backup/zhiying-data.tar.gz -C /data .
docker exec zhiying-postgres pg_dump -U postgres zhiying > backup.sql
```

### 常用运维

```bash
docker compose logs -f zhiying-server    # 看日志
docker compose restart zhiying-server    # 重启应用
docker compose down                      # 停止（保留数据）
docker compose down -v                   # 停止并清空数据（危险）
```

---

## B. 本地 Python 直装

```bash
python -m venv .venv
.venv\Scripts\pip install -e .          # 含 console scripts: zhiying / zhiying-api / zhiying-mcp
cp .env.example .env                     # 填 Key 与 DB 密码
.venv\Scripts\zhiying doctor             # 环境自检
.venv\Scripts\zhiying-api                # 起服务（8600）
```

数据库：本机 PostgreSQL 18 + pgvector，或只起 DB 容器：

```bash
docker compose up -d zhiying-postgres
.venv\Scripts\python -m zhiying.storage.init_db
.venv\Scripts\python -m zhiying.storage.migrate
```

前端开发/生产：

```bash
cd ..\zhiying-web
npm run dev      # 开发（5273，/api 代理到 8600）
npm run build    # 生产（dist 目录，设 ZHIYING_WEB_DIST 指向它即可由 API 托管）
```

---

## 验证部署成功

```bash
# 1) 服务活着
curl http://127.0.0.1:8600/api/health
# {"status":"ok","version":"0.3.0"}

# 2) 配置正确（Key 就绪、数据目录）
curl http://127.0.0.1:8600/api/config

# 3) 端到端：丢一条视频进去
curl -X POST http://127.0.0.1:8600/api/tasks \
  -H "Content-Type: application/json" \
  -d "{\"source\":\"https://www.bilibili.com/video/BV1GJ411x7t7/\",\"quality\":\"480\",\"precision\":\"fast\"}"

# 4) 查进度，done 后试着提问
curl -X POST http://127.0.0.1:8600/api/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"视频里是怎么处理菠萝的？\"}"
```

---

## 故障排查

| 现象 | 原因 | 处置 |
|---|---|---|
| `docker compose up` 报 `ZHIYING_DB_PASSWORD` 缺失 | `.env` 未配 | 填 `.env` 后重试 |
| 容器反复重启 | 端口占用 / Key 无效 | `docker compose logs zhiying-server` |
| Web 打开是 404 / 空白 | 未构建前端或未挂载 | `npm run build`，确认 `ZHIYING_WEB_DIST` |
| `/api/videos` 返回 503 | DB 未就绪 | 检查 postgres 健康状态，跑 init_db/migrate |
| 视频处理失败「未配置 Key」 | `.env` Key 为空 | 填 `SILICONFLOW_API_KEY` 或 `LONGCAT_API_KEY` |
| 长视频卡在画面识别 | 默认 fast 档已优化；若选 precise 属预期 | 见 PRD DR-22 精度两档说明 |

---

## 给第二用户的建议（开源分发）

本项目按 DR-13 采用**每用户自部署**模式：

1. 对方 clone 两个仓（`zhiying` + `zhiying-web`）
2. 按本文档 **A** 或 **B** 部署到自己的机器
3. 用自己的模型 API Key（成本自理，作者不承担任何使用者的 token 费用）

不提供共享实例——与仓颉.Skill 的零基础设施成本模型一致。
