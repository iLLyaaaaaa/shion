@echo off
rem Start Shion without a console window
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m shion
