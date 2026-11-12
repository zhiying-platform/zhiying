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