@echo off
setlocal
cd /d "%~dp0"

echo.
echo  ============================================
echo   YT Downloader - one-time setup
echo  ============================================
echo.

set "PYCMD="
where python >nul 2>nul && set "PYCMD=python"
if not defined PYCMD (
    where py >nul 2>nul && set "PYCMD=py -3"
)
if not defined PYCMD goto no_python

if exist ".venv\Scripts\python.exe" goto has_venv
echo  [1/2] Creating virtual environment in .venv ...
%PYCMD% -m venv .venv
if errorlevel 1 goto venv_failed
goto install

:has_venv
echo  [1/2] Reusing existing .venv

:install
echo  [2/2] Installing PySide6-Essentials (a few minutes) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install PySide6-Essentials==6.12.*
if errorlevel 1 goto pip_failed

echo.
echo   Setup finished. Double-click run.bat to start.
echo.
pause
exit /b 0

:no_python
echo   ERROR: Python not found in PATH.
echo   Install Python 3.10+ from python.org, then run this again.
echo.
pause
exit /b 1

:venv_failed
echo   ERROR: failed to create .venv
echo.
pause
exit /b 1

:pip_failed
echo   ERROR: pip install failed. Check your network or proxy.
echo.
pause
exit /b 1
