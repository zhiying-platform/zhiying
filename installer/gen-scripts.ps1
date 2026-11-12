# ============================================================
# 安装后脚本组生成：GBK 编码 + CRLF（cmd 批处理铁律）
# 布局: {app}\runtime\python（Lib\site-packages 含 zhiying 包）+ runtime\pg + web
# 数据: %APPDATA%\zhiying
# 启动模式: start.cmd 引导环境与嵌入式 PG 后，交给 pythonw 托盘进程
#          （无常驻控制台窗口；浏览器由托盘在服务就绪后打开；右键托盘退出）
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

# ---------- start-core.cmd：启动入口（引导后转 pythonw 托盘，无常驻窗口） ----------
Write-GbkScript "start-core.cmd" @'
@echo off
setlocal enabledelayedexpansion
title 知映 zhiying
rem 知映 zhiying 启动引导：本窗口仅做环境准备，几秒后自动关闭；
rem 服务以托盘图标常驻（任务栏右下角），右键托盘「退出」即停止服务。
set "APP_DIR=%~dp0.."
set "PYTHONW=%APP_DIR%\runtime\python\pythonw.exe"
set "PGBIN=%APP_DIR%\runtime\pg\bin"
set "ZHIYING_HOME=%APP_DIR%"
set "ZHIYING_DATA=%APPDATA%\zhiying"
set "ZHIYING_WEB_DIST=%APP_DIR%\web"
set "PATH=%PGBIN%;%PATH%"

if not exist "%PYTHONW%" (
    echo [X] 安装不完整，请重新安装
    pause
    exit /b 1
)
if not exist "%ZHIYING_DATA%" mkdir "%ZHIYING_DATA%"

rem 已在运行：托盘实例存在，只打开页面
netstat -ano | findstr ":8600" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    start "" http://127.0.0.1:8600
    exit /b 0
)

if not exist "%PGBIN%\pg_ctl.exe" goto launch

rem ---------- 嵌入式数据库（知识库组件） ----------
if not exist "%ZHIYING_DATA%\pg\PG_VERSION" (
    echo [..] 首次运行：初始化知识库数据库，约 10 秒
    "%PGBIN%\initdb.exe" -D "%ZHIYING_DATA%\pg" -U postgres -E UTF8 --locale=C >nul 2>&1
)

rem 复用已运行实例的端口，否则探测空闲端口
set "PGPORT="
if exist "%ZHIYING_DATA%\pg.port" (
    set /p PGPORT=<"%ZHIYING_DATA%\pg.port"
    netstat -ano | findstr ":!PGPORT!" | findstr "LISTENING" >nul 2>&1
    if not errorlevel 1 (
        "%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p !PGPORT! -q >nul 2>&1
        if errorlevel 1 set "PGPORT="
    ) else (
        set "PGPORT="
    )
)
if not defined PGPORT (
    for %%p in (15499 15500 15501 15502 15503 15504 15505 15506 15507 15508 15509 15510) do (
        if not defined PGPORT (
            netstat -ano | findstr ":%%p" | findstr "LISTENING" >nul 2>&1
            if errorlevel 1 set "PGPORT=%%p"
        )
    )
)
if not defined PGPORT (
    echo [X] 找不到空闲数据库端口，请关闭占用 15499-15510 的程序后重试
    pause
    exit /b 1
)
echo !PGPORT!> "%ZHIYING_DATA%\pg.port"

netstat -ano | findstr ":!PGPORT!" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    "%PGBIN%\pg_ctl.exe" -D "%ZHIYING_DATA%\pg" -o "-p !PGPORT!" -l "%ZHIYING_DATA%\pg.log" start >nul 2>&1
    set "READY="
    for /l %%i in (1,1,20) do (
        if not defined READY (
            "%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p !PGPORT! -q >nul 2>&1
            if not errorlevel 1 set "READY=1"
            if not defined READY ping -n 2 127.0.0.1 >nul 2>&1
        )
    )
)

set "ZHIYING_DB_HOST=127.0.0.1"
set "ZHIYING_DB_PORT=!PGPORT!"
set "ZHIYING_DB_USER=postgres"
set "ZHIYING_DB_NAME=zhiying"

if not exist "%ZHIYING_DATA%\pg.createdb" (
    "%PGBIN%\createdb.exe" -h 127.0.0.1 -p !PGPORT! -U postgres zhiying >nul 2>&1
    if not errorlevel 1 echo ok> "%ZHIYING_DATA%\pg.createdb"
)

echo [..] 校验知识库表结构...
"%APP_DIR%\runtime\python\python.exe" -m zhiying.storage.init_db > "%ZHIYING_DATA%\initdb.log" 2>&1

:launch
rem 交给无窗口托盘进程：就绪后自动开浏览器；右键托盘退出
start "" "%PYTHONW%" -m zhiying.tray
exit /b 0
'@

# ---------- stop.cmd ----------
Write-GbkScript "stop.cmd" @'
@echo off
setlocal enabledelayedexpansion
title 知映 zhiying - 停止服务
rem 停止知映服务（托盘进程/后端 8600 + 嵌入式数据库）
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8600" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
if exist "%APPDATA%\zhiying\pg.port" (
    set /p PGPORT=<"%APPDATA%\zhiying\pg.port"
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":!PGPORT!" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
)
echo [OK] 已停止
'@

# ---------- zhiying-cli.cmd ----------
Write-GbkScript "zhiying-cli.cmd" @'
@echo off
setlocal
set "APP_DIR=%~dp0.."
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
if exist "%APPDATA%\zhiying\pg.port" (
    set /p PGPORT=<"%APPDATA%\zhiying\pg.port"
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":!PGPORT!" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
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
  -> 浏览器关闭后服务继续运行，随时双击图标再打开 http://127.0.0.1:8600

退出服务：
  右键任务栏托盘的「知」图标 -> 退出（会同时停止数据库）

组件说明：
  - 完整安装：含嵌入式 PostgreSQL（知识库向量检索）
  - 精简安装：仅 md 知识积累，不装数据库

常用操作：
  停止服务：右键托盘图标退出，或运行 scripts\stop.cmd
  命令行：  scripts\zhiying-cli.cmd --help
  AI 接入： scripts\zhiying-mcp.cmd（MCP 协议）
            claude mcp add zhiying -- "安装目录\scripts\zhiying-mcp.cmd"
  重置知识库：scripts\pg-setup.cmd

数据位置：
  %APPDATA%\zhiying\（视频、知识库、数据库）
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
