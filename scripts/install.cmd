@echo off
setlocal
title 知映 zhiying - 安装向导

rem ============================================
rem 知映 zhiying — 一键安装向导（V1.1-α，DR-41）
rem 交互式组件勾选：md 积累[基础] / 知识库[PG] / skill 蒸馏
rem 幂等：所有步骤重复执行安全；可由 AI Agent 代跑
rem 注意：if 块内 echo 行禁用半角括号（cmd 解析会断裂，实测教训）
rem ============================================

set "ROOT=%~dp0.."
set "VENV=%ROOT%\.venv"
set "PIP=%VENV%\Scripts\pip.exe"
set "PY=%VENV%\Scripts\python.exe"
set "ENV_FILE=%ROOT%\.env"
set "ENV_EXAMPLE=%ROOT%\.env.example"

echo.
echo ============================================
echo   知映 zhiying - 视频知识库 安装向导
echo   版本 V1.1-a
echo ============================================
echo.

rem ---------- 步骤 1：系统 Python 检测 ----------
echo [1/6] 检测系统 Python...
set "SYS_PY="
where python >nul 2>&1 && set "SYS_PY=python"
if not defined SYS_PY where python3 >nul 2>&1 && set "SYS_PY=python3"
if not defined SYS_PY (
    echo   [X] 未检测到 Python 3.10+
    echo   [!] 请先安装 Python 3.10+ 并勾选 Add to PATH，然后重跑本向导
    echo       下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%V in ('%SYS_PY% --version 2^>nul') do echo   [OK] %%V

rem ---------- 步骤 2：venv 创建（幂等） ----------
echo.
echo [2/6] Python 虚拟环境...
if exist "%VENV%\Scripts\python.exe" (
    echo   [OK] .venv 已存在，跳过创建
) else (
    %SYS_PY% -m venv "%VENV%" && echo   [OK] .venv 已创建
)

rem ---------- 步骤 3：依赖安装（pip 自动跳过已装） ----------
echo.
echo [3/6] 安装依赖，首次约 2-5 分钟...
%PIP% install --quiet -e "%ROOT%"
if not errorlevel 1 (
    echo   [OK] 主依赖安装完成
) else (
    echo   [X] 主依赖安装失败，请检查网络后重试
    pause
    exit /b 1
)
%PY% -c "import faster_whisper" >nul 2>&1
if not errorlevel 1 (
    echo   [OK] 本地 Whisper 已装，可选组件
) else (
    echo   [i] 本地 Whisper 未装，可选离线转写保底：pip install faster-whisper
)

rem ---------- 步骤 4：.env 配置（存在则跳过，不覆盖） ----------
echo.
echo [4/6] 环境配置...
if exist "%ENV_FILE%" (
    echo   [OK] .env 已存在，跳过脚手架，不覆盖已有配置
) else if exist "%ENV_EXAMPLE%" (
    copy /y "%ENV_EXAMPLE%" "%ENV_FILE%" >nul
    echo   [OK] .env 已从模板创建
    echo   [!] 请编辑 .env 填入模型 API Key
) else (
    echo   [X] 缺少 .env.example 模板，请从仓库补齐
)

rem ---------- 步骤 5：功能勾选（逐项 Y/N） ----------
echo.
echo [5/6] 功能组件勾选，md 积累为基础能力默认包含
echo.
echo   [1] 知识库：跨视频检索/问答，需要 PostgreSQL
echo   [2] skill 蒸馏：AI 能力卡沉淀，仅需模型 Key，无额外依赖
echo.
set "SEL_KB="
set "SEL_SKILL="
choice /c YN /n /m "安装知识库组件 PostgreSQL+pgvector? [Y/N]: "
if not errorlevel 2 set "SEL_KB=1"
choice /c YN /n /m "启用 skill 蒸馏 仅需模型 Key 无额外依赖? [Y/N]: "
if not errorlevel 2 set "SEL_SKILL=1"

if defined SEL_KB goto :pg_setup
goto :skill_note

:pg_setup
echo.
echo   ---- 知识库组件：PostgreSQL ----
echo   检测本机 PostgreSQL 服务...
set "PG_FOUND="
sc query state= all | find "postgresql" >nul 2>&1 && set "PG_FOUND=1"
if defined PG_FOUND (
    echo   [OK] 检测到本机 PostgreSQL 服务，将直接使用
) else (
    echo   [i] 未检测到本机 PostgreSQL，两种方式任选：
    echo       A. Docker: docker compose up -d zhiying-postgres
    echo       B. zip 版安装: 见 scripts\pg-setup.cmd 说明
)
rem 初始化表结构（幂等：KB 可达即执行，不可达则提示跳过）
%PY% -m zhiying.storage.init_db >nul 2>&1
if not errorlevel 1 (
    echo   [OK] 知识库表结构已就绪
    %PY% -m zhiying.storage.migrate >nul 2>&1
    if not errorlevel 1 echo   [OK] 迁移已应用
) else (
    echo   [i] 知识库暂不可达，无 DB 时跳过，md 积累功能不受影响
)
goto :skill_note

:skill_note
if defined SEL_SKILL (
    echo.
    echo   ---- skill 蒸馏组件：无需额外安装 ----
    echo   [OK] 已随主依赖就绪，使用模型 Key 调用，用法见 README
)

rem ---------- 步骤 6：环境自检 ----------
echo.
echo [6/6] 环境自检...
echo.
%PY% -m zhiying doctor
echo.

echo ============================================
echo   安装完成！
echo ============================================
echo.
echo   启动服务:  scripts\start.cmd
echo   访问:      http://127.0.0.1:8600
echo   MCP 接入:  见 docs\MCP-SETUP.md
echo     claude mcp add zhiying -- %ROOT%\scripts\zhiying-mcp.cmd
echo.
pause
exit /b 0
