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