# ============================================================
# 安装后脚本组生成：GBK 编码 + CRLF（cmd 批处理铁律）
# 布局: {app}\runtime\python（Lib\site-packages 含 zhiying 包）+ runtime\pg + web
# 数据: %APPDATA%\zhiying
#
# 启动设计（V1.3）：全部引导逻辑落在 pythonw 进程（zhiying.tray）里，
# cmd 脚本只做一件事——用 pythonw 拉起托盘，然后立即退出。
# 这样双击时不会残留 cmd 窗口（曾出现「校验知识库表结构」窗口不自动关闭）。
# ============================================================
$ErrorActionPreference = "Stop"
$gbk = [System.Text.Encoding]::GetEncoding(936)
$dst = "D:\projectMenu\zhiying\scripts\installed"
New-Item -ItemType Directory -Force -Path $dst | Out-Null

function Write-GbkScript($name, $content) {
    $p = Join-Path $dst $name
    [IO.File]::WriteAllText($p, ($content -replace "`n", "`r`n"), $gbk)
    Write-Host "已生成: $name"
}

# ---------- start-core.cmd：薄启动器（快捷方式已直接指向 pythonw，此脚本仅作备用/开发者路径） ----------
Write-GbkScript "start-core.cmd" @'
@echo off
rem 知映 zhiying 启动（备用入口）：
rem 快捷方式已直接指向 pythonw.exe，正常使用无需运行本脚本。
rem 本脚本仅用于「从命令行手动拉起」，或快捷方式丢失时的兜底。
set "APP_DIR=%~dp0.."
set "PYTHONW=%APP_DIR%\runtime\python\pythonw.exe"

if not exist "%PYTHONW%" (
    echo [X] 安装不完整，请重新安装
    pause
    exit /b 1
)

rem 交给 pythonw 托盘进程：它自行完成起库、建表、起服务、开浏览器
start "" "%PYTHONW%" -m zhiying.tray
exit /b 0
'@

# ---------- stop.cmd ----------
Write-GbkScript "stop.cmd" @'
@echo off
setlocal enabledelayedexpansion
title 知映 zhiying - 停止服务
rem 停止托盘进程与后端（8600），再停嵌入式数据库
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8600" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1

rem 停数据库：按数据目录里的 pg.port 记录
if exist "%APPDATA%\zhiying\pg.port" (
    set /p PGPORT=<"%APPDATA%\zhiying\pg.port"
    if exist "%~dp0..\runtime\pg\bin\pg_ctl.exe" (
        if exist "%APPDATA%\zhiying\pg\PG_VERSION" (
            "%~dp0..\runtime\pg\bin\pg_ctl.exe" -D "%APPDATA%\zhiying\pg" stop -m fast >nul 2>&1
        )
    )
)
echo [OK] 已停止
'@

# ---------- zhiying-cli.cmd ----------
Write-GbkScript "zhiying-cli.cmd" @'
@echo off
setlocal
set "APP_DIR=%~dp0.."
set "ZHIYING_HOME=%APP_DIR%"
set "ZHIYING_DATA=%APPDATA%\zhiying"
set "ZHIYING_DB_HOST=127.0.0.1"
set "ZHIYING_DB_USER=postgres"
set "ZHIYING_DB_NAME=zhiying"
if exist "%APPDATA%\zhiying\pg.port" set /p ZHIYING_DB_PORT=<"%APPDATA%\zhiying\pg.port"
set "PATH=%APP_DIR%\runtime\pg\bin;%PATH%"
"%APP_DIR%\runtime\python\python.exe" -m zhiying %*
'@

# ---------- zhiying-mcp.cmd ----------
Write-GbkScript "zhiying-mcp.cmd" @'
@echo off
setlocal
set "APP_DIR=%~dp0.."
set "ZHIYING_HOME=%APP_DIR%"
set "ZHIYING_DATA=%APPDATA%\zhiying"
set "ZHIYING_DB_HOST=127.0.0.1"
set "ZHIYING_DB_USER=postgres"
set "ZHIYING_DB_NAME=zhiying"
if exist "%APPDATA%\zhiying\pg.port" set /p ZHIYING_DB_PORT=<"%APPDATA%\zhiying\pg.port"
"%APP_DIR%\runtime\python\python.exe" -m zhiying.mcp
'@

# ---------- pg-setup-installed.cmd ----------
Write-GbkScript "pg-setup-installed.cmd" @'
@echo off
setlocal enabledelayedexpansion
title 知映 zhiying - 重置知识库数据库
echo 将停止服务并清空知识库数据库（已积累的视频与 md 不受影响，向量索引需重新生成）
set /p CONFIRM=确认请输入 yes:
if not "%CONFIRM%"=="yes" exit /b 1

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8600" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1

if exist "%~dp0..\runtime\pg\bin\pg_ctl.exe" (
    if exist "%APPDATA%\zhiying\pg\PG_VERSION" (
        "%~dp0..\runtime\pg\bin\pg_ctl.exe" -D "%APPDATA%\zhiying\pg" stop -m immediate >nul 2>&1
    )
)
if exist "%APPDATA%\zhiying\pg" rmdir /s /q "%APPDATA%\zhiying\pg"
if exist "%APPDATA%\zhiying\pg.createdb" del "%APPDATA%\zhiying\pg.createdb"
if exist "%APPDATA%\zhiying\pg.port" del "%APPDATA%\zhiying\pg.port"
echo [OK] 已重置，下次启动自动重建数据库
'@

# ---------- 安装说明 ----------
$readme = @'
知映 zhiying - 安装说明
========================

快速开始：
  双击「知映 zhiying」（桌面或开始菜单）
  -> 服务以托盘图标常驻（任务栏右下角「知」字图标），就绪后自动打开浏览器
  -> 全程不会弹出黑色命令行窗口
  -> 浏览器关闭后服务继续运行，随时双击图标再打开 http://127.0.0.1:8600

退出服务：
  右键任务栏托盘的「知」图标 -> 退出（会同时停止数据库）

两个安装选项的区别：
  [完整安装]  产出：视频转写 + md 文档 + 摘要 + skill 包 + 知识库（检索、问答、溯源）
              含 PostgreSQL 数据库，占用约 300MB
  [精简安装]  产出：视频转写 + md 文档 + 摘要 + skill 包
              不含数据库，不能检索/问答；之后想开通，重装选「完整安装」即可（数据不丢）

常用操作：
  停止服务：右键托盘图标退出，或运行 scripts\stop.cmd
  命令行：  scripts\zhiying-cli.cmd --help
  AI 接入： scripts\zhiying-mcp.cmd（MCP 协议）
            claude mcp add zhiying -- "安装目录\scripts\zhiying-mcp.cmd"
  重置知识库：scripts\pg-setup.cmd

数据位置：
  %APPDATA%\zhiying\（视频、知识库、数据库、日志 app.log）
  卸载或升级重装不会删除数据

模型配置：
  首次使用在网页「设置」页填写 VLM（视觉识别）与文本模型 API Key，支持混搭不同厂商。
  B 站高清下载：在「设置」页点一次登录引导，缓存 Cookie 后即可 1080P 下载。

端口：
  网页与 API：8600（固定）
  嵌入式数据库：自动选择空闲端口（15499 起），记录在 %APPDATA%\zhiying\pg.port
  这样不会与 Docker、本机已装 PostgreSQL 等冲突。
'@
[IO.File]::WriteAllText("D:\projectMenu\zhiying\docs\installation-readme.txt", ($readme -replace "`n", "`r`n"), $gbk)
Write-Host "已生成: docs\installation-readme.txt（GBK）"
Write-Host "=== 脚本组生成完毕 ==="
