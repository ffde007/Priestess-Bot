@echo off
rem Debug mode: runs the bot with a console window so you can watch its output.
rem For everyday use, open the PRTS shortcut instead (it runs in the tray, no window).
rem Uses the Python in runtime\ (the portable package); without it, sets up .venv on the first run.
cd /d "%~dp0"
set "PY=runtime\python.exe"
if exist "%PY%" goto run
set "PY=.venv\Scripts\python.exe"
if not exist .venv (
    python -m venv .venv
    "%PY%" -m pip install -r app\requirements.txt
)
:run
if not exist PRTS.lnk "%PY%" app\tray.py --shortcut
"%PY%" app\bot.py
pause
