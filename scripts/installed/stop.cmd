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