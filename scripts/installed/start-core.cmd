@echo off
rem 知映 zhiying 启动（备用入口）：
rem 快捷方式已直接指向 pythonw.exe，正常使用无需运行本脚本。
rem 本脚本仅用于「从命令行手动拉起」，或快捷方式丢失时的兜底。
set "APP_DIR=%~dp0.."
set "PYTHONW=%APP_DIR%\runtime\python\pythonw.exe"

if not exist "%PYTHONW%" (
    echo [X] 安装不完整，请重新安装
    pause
    exit /b 1
)

rem 交给 pythonw 托盘进程：它自行完成起库、建表、起服务、开浏览器
start "" "%PYTHONW%" -m zhiying.tray
exit /b 0