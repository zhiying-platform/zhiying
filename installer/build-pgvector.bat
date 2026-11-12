@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
cd /d D:\projectMenu\zhiying\installer\runtime\pgvector-087-src
set "PGROOT=D:\projectMenu\zhiying\installer\runtime\pgsql"
nmake /F Makefile.win
if errorlevel 1 (
    echo BUILD_FAILED
    exit /b 1
)
echo BUILD_OK