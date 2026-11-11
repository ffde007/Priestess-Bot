@echo off
rem Debug mode: runs the bot with a console window so you can watch its output.
rem For everyday use, open the PRTS shortcut instead (it runs in the tray, no window).
rem The first run sets up .venv and makes that shortcut in this folder.
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
)
if not exist PRTS.lnk .venv\Scripts\python tray.py --shortcut
.venv\Scripts\python bot.py
pause
