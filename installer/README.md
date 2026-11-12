# installer — Windows 安装包构建

构建知映 zhiying 的 Windows 离线安装包（`zhiying-setup.exe`）。
产物面向普通用户：双击安装、无需 Python/PostgreSQL/Docker、无需联网。

---

## 一键构建

```powershell
# 正式发布包（最大压缩）：约 370 秒 → 141 MB
powershell -File installer\build-installer.ps1

# 迭代自测包（大件不压缩）：约 44 秒 → 541 MB，仅内部验证用
powershell -File installer\build-installer.ps1 -Fast -SkipStage

# 指定版本（默认读仓库根 VERSION 文件）
powershell -File installer\build-installer.ps1 -Version 1.3.0
```

产物路径：`installer\Output\zhiying-setup.exe`（自测包为 `zhiying-setup-dev.exe`）

### 参数说明

| 参数 | 作用 | 何时用 |
|---|---|---|
| `（无）` | 完整构建 + 最大压缩 | 正式发版 |
| `-Fast` | Python/PG 大件不压缩 | 迭代自测（体积大，不对外） |
| `-SkipStage` | 复用现有 stage，仅同步后端源码后重打包 | 只改了 Python 代码 |
| `-Version x.y.z` | 覆盖版本号 | 临时出指定版本 |

> ⚠️ `-SkipStage` 仍会同步 `src\zhiying` 到 stage（否则会打出旧代码），但**不会**重装依赖、
**不会**重建前端。改了依赖或前端时不要用它。

---

## 首次构建：准备物料（只做一次）

`installer\runtime\` 下需要以下物料（均已在 `.gitignore` 中，不入仓）：

| 物料 | 来源 | 大小 |
|---|---|---|
| `python-embed.zip` | python.org 官方 embeddable 3.12（`python-3.12.10-embed-amd64.zip`） | 11 MB |
| `pg-binaries.zip` | EDB PostgreSQL 18 Windows zip | 319 MB |
| `pgvector-087-src\` | pgvector v0.8.7 源码 + 已编译的 `vector.dll` | 2 MB |

离线 wheels 放在 `installer\wheels\`：

```powershell
# 二进制包（大部分依赖）
.venv\Scripts\python.exe -m pip download -d installer\wheels `
  --only-binary=:all: --python-version 3.12 --platform win_amd64 -r installer\req-binary.txt

# 纯源码包（jieba 需 sdist）
.venv\Scripts\python.exe -m pip download -d installer\wheels --no-deps -r installer\req-pure.txt
```

### pgvector 编译（仅当 PG 大版本变化时需要）

```powershell
# 需要 Visual Studio Build Tools（含 C++ 工作负载）
cmd /c installer\build-pgvector.bat
```

产物 `vector.dll` 与 43 个迁移 SQL 由 `build-installer.ps1` 自动装入 stage。
> 注意：pgvector v0.8.0 与 PostgreSQL 18 不兼容（`vacuum_delay_point` 签名变更），须用 v0.8.7+。

---

## 构建管线（三步）

```
gen-scripts.ps1   → 生成安装后脚本组（GBK+CRLF 的 start/stop/cli/mcp/pg-setup）
build-stage.ps1   → 组装运行环境（Python + 依赖 + zhiying 包 + 前端 + PG）
setup.iss (ISCC)  → 打包为 exe（含卸载器、快捷方式、卸载数据保护逻辑）
```

### 关键设计（踩坑结论，改动前请先读）

| 设计 | 原因 |
|---|---|
| **依赖装到 `python\Lib\site-packages`** | embeddable 的 `._pth` 不会处理 `.pth` 引导文件；只有标准布局才能让 pywin32/pystray 等正常加载 |
| **zhiying 包直接并入 site-packages** | 曾用 `zhiying-src.pth` 相对路径引导，但 stage 布局与安装布局层级不同，安装后必炸 |
| **PG 端口动态探测（15499 起）** | 15432 常被 Docker Desktop / 本机 PostgreSQL 占用；端口记在 `%APPDATA%\zhiying\pg.port` |
| **PG 用 trust 认证** | 嵌入式单机库仅监听 127.0.0.1，免密码管理 |
| **构建期剔除 pgAdmin 4 / StackBuilder** | EDB 包自带 16,878 个文件 / 676 MB GUI 工具，占全部文件 63%，知映完全不用 |
| **构建期清理 `__pycache__`** | 3,203 个 `.pyc`，安装后运行时自动重建，不必打包 |
| **cmd 脚本必须 GBK + CRLF** | UTF-8/LF 会让 cmd 解析错位（详见 `windows-cmd-batch-scripts` 经验） |
| **ps1 脚本必须 UTF-8 BOM** | PowerShell 5 无 BOM 时按 GBK 解码，中文会乱码断裂 |

### 安装包内容

```
{app}\
  runtime\python\           Python 3.12 embeddable + 全部依赖 + zhiying 包
  runtime\pg\               PostgreSQL 18 + pgvector（组件 pg 可选）
  web\                      前端静态产物
  scripts\                  start / stop / zhiying-cli / zhiying-mcp / pg-setup
  安装说明.txt
```

数据目录：`%APPDATA%\zhiying`（卸载与升级不丢）。

---

## 其它文件

| 文件 | 用途 |
|---|---|
| `setup.iss` | Inno Setup 主脚本（中文界面、组件、卸载三段确认、.env 写入） |
| `ChineseSimplified.isl` | Inno 中文语言包（来自 issrc 仓库 `Files/Languages/`） |
| `req-binary.txt` | 离线 wheels 下载清单（二进制包） |
| `req-pure.txt` | 离线 wheels 下载清单（纯源码包，如 jieba） |
| `build-pgvector.bat` | pgvector 编译脚本（nmake，需 VS Build Tools） |

> 依赖的唯一权威来源是仓库根 `pyproject.toml`；`req-*.txt` 仅用于批量下载 wheels。
