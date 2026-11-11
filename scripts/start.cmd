@echo off
setlocal
title 知映 zhiying - 服务启动

rem ============================================
rem 知映 zhiying — 一键启动（V1.1-α，DR-41）
rem 自动探测前端产物；后端起 8600；可选自动开浏览器
rem 幂等：已在运行则直接提示访问地址
rem ============================================

set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "WEB_DIST=%ROOT%..\zhiying-web\dist"

rem ---------- 前置：.venv 存在检查（未安装则引导安装向导） ----------
if not exist "%PY%" (
    echo [X] 未检测到安装环境（.venv 缺失）。
    echo [!] 请先运行安装向导: scripts\install.cmd
    pause
    exit /b 1
)

rem ---------- 幂等：8600 已有监听则视为服务已启动 ----------
netstat -ano | findstr ":8600.*LISTENING" >nul 2>&1 && (
    echo [OK] 知映服务已在运行
    echo     访问: http://127.0.0.1:8600
    start "" http://127.0.0.1:8600
    exit /b 0
)

rem ---------- 前端产物探测（有则设 ZHIYING_WEB_DIST，单容器式托管） ----------
if exist "%WEB_DIST%\index.html" (
    set "ZHIYING_WEB_DIST=%WEB_DIST%"
    echo [OK] 检测到前端产物，Web 界面将一并托管
) else (
    echo [i] 未检测到前端产物（zhiying-web/dist），将以纯 API 模式启动
)

rem ---------- 启动后端（新窗口，日志可见） ----------
echo [OK] 启动知映服务（新窗口运行，关闭该窗口即停止服务）...
start "知映 zhiying 服务" /D "%ROOT%" cmd /c "%PY% -m zhiying.api"

rem ---------- 等待就绪并打开浏览器 ----------
echo [..] 等待服务就绪
set /a TRIES=0
:wait_ready
set /a TRIES+=1
if %TRIES% GTR 20 (
    echo   [X] 服务 20 秒内未就绪，请检查 .env 配置或运行 zhiying doctor
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:8600/api/health 2>nul | find "200" >nul 2>&1
if errorlevel 1 goto :wait_ready

echo [OK] 服务已就绪
start "" http://127.0.0.1:8600
echo.
echo   访问:    http://127.0.0.1:8600
echo   API 文档: http://127.0.0.1:8600/docs
echo   停止:    关闭「知映 zhiying 服务」窗口，或 taskkill /PID (uvicorn 进程)
echo.
timeout /t 3 /nobreak >nul
