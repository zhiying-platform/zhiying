@echo off
setlocal
title 知映 zhiying - PostgreSQL zip 版初始化（方案 A 嵌入式 PG）

rem ============================================
rem 知映 zhiying — PostgreSQL zip 版自动初始化（DR-41 方案 A）
rem 前置：已下载 PostgreSQL 18 zip 版并解压（如 <PG\pgsql>）
rem       https://www.enterprisedb.com/download-postgresql-binaries
rem 用法：scripts\pg-setup.cmd <PG解压目录>
rem 幂等：data 目录已存在则跳过 initdb
rem ============================================

set "PG_HOME=%~1"
if "%PG_HOME%"=="" (
    echo 用法: %~nx0 ^<PostgreSQL解压目录^>
    echo 示例: %~nx0 <PG\pgsql>
    echo.
    echo 下载地址: https://www.enterprisedb.com/download-postgresql-binaries
    echo （选 Windows x86-64 版本，解压后把 bin 同级的目录传进来）
    pause
    exit /b 1
)

if not exist "%PG_HOME%\bin\initdb.exe" (
    echo [X] %PG_HOME%\bin\initdb.exe 不存在——请确认解压目录正确
    pause
    exit /b 1
)

set "PGDATA=%PG_HOME%\data"
set "PORT=15432"
set "PASSWORD=zhiying-local"

echo.
echo [1/3] initdb（首次初始化；%PGDATA% 已存在则跳过）...
if exist "%PGDATA%\PG_VERSION" (
    echo   [OK] 数据目录已初始化，跳过
) else (
    echo.%PASSWORD%>"%TEMP%\zy_pgpass.txt"
    echo y | "%PG_HOME%\bin\initdb.exe" -D "%PGDATA%" -U postgres --pwfile="%TEMP%\zy_pgpass.txt" -E UTF8 --locale=C >nul 2>&1
    if exist "%PGDATA%\PG_VERSION" (echo   [OK] initdb 完成) else (echo   [X] initdb 失败 & pause & exit /b 1)
)

echo.
echo [2/3] 启动 PostgreSQL（端口 %PORT%；已运行则跳过）...
"%PG_HOME%\bin\pg_ctl.exe" -D "%PGDATA%" -o "-p %PORT%" status >nul 2>&1 && (
    echo   [OK] 已在运行
) || (
    "%PG_HOME%\bin\pg_ctl.exe" -D "%PGDATA%" -l "%PGDATA%\zhiying.log" -o "-p %PORT%" start
    echo   [OK] 已启动（日志: %PGDATA%\zhiying.log）
)

echo.
echo [3/3] 建库 zhiying（已存在则跳过）...
set "PGPASSWORD=%PASSWORD%"
"%PG_HOME%\bin\psql.exe" -U postgres -h localhost -p %PORT% -tAc "SELECT 1 FROM pg_database WHERE datname='zhiying'" 2>nul | find "1" >nul 2>&1 && (
    echo   [OK] 库已存在
) || (
    "%PG_HOME%\bin\createdb.exe" -U postgres -h localhost -p %PORT% zhiying && echo   [OK] 已建库
)

echo.
echo [!] 接下来请编辑 .env 对齐以下配置：
echo     ZHIYING_DB_HOST=localhost
echo     ZHIYING_DB_PORT=%PORT%
echo     ZHIYING_DB_USER=postgres
echo     ZHIYING_DB_PASSWORD=%PASSWORD%
echo.
echo [i] pgvector 扩展说明：zip 版官方 PG 不自带 pgvector，需单独安装
echo     （vector.dll 放入 %PG_HOME%\lib，控制文件放 share\extension）
echo     或者：改用 docker compose 的 pgvector/pgvector:pg18 镜像（自带）
echo.
pause
