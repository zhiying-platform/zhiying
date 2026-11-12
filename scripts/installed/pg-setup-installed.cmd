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