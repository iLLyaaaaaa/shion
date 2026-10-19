@echo off
chcp 65001 >nul
rem 调试模式启动 Shion：冷落/睡眠阈值缩短，控制台显示状态日志
cd /d "%~dp0"
set SHION_DEBUG=1
".venv\Scripts\python.exe" -m shion
echo.
echo Shion 已退出，按任意键关闭窗口
pause >nul
