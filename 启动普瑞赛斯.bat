@echo off
rem Everyday start: runs in the tray with no console window. The first run opens the setup page.
rem Uses the Python in runtime\ (the portable package); without it, sets up .venv (source download).
cd /d "%~dp0"
set "PY=runtime\python.exe"
if exist "%PY%" goto start
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto start
echo First start: installing the libraries. This takes a few minutes...
python -m venv .venv
if errorlevel 1 goto nopython
"%PY%" -m pip install -r app\requirements.txt
if errorlevel 1 goto failed
:start
if not exist PRTS.lnk "%PY%" app\tray.py --shortcut
start "" "%PY:python.exe=pythonw.exe%" app\tray.py
exit /b
:nopython
echo.
echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH"), or download the portable package, which needs no Python.
pause
exit /b 1
:failed
echo.
echo Installing the libraries failed. Check the messages above, then run this file again.
rmdir /s /q .venv
pause
exit /b 1
