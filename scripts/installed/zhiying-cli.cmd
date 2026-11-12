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