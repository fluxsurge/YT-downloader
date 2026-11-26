@echo off
setlocal
cd /d "%~dp0"
echo  Debug mode: console stays open, errors are visible.
echo.
".venv\Scripts\python.exe" main.py
echo.
echo  Exit code: %errorlevel%
pause
