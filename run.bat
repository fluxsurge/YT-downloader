@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" goto no_venv
if not exist ".venv\Scripts\python.exe" goto no_venv

".venv\Scripts\python.exe" -c "import PySide6" >nul 2>nul
if errorlevel 1 goto no_pyside

start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0

:no_venv
echo.
echo   ERROR: .venv not found.
echo   Double-click setup.bat once to create it.
echo.
pause
exit /b 1

:no_pyside
echo.
echo   ERROR: PySide6 is missing inside .venv
echo   Double-click setup.bat to install it.
echo.
pause
exit /b 1
