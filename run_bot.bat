@echo off
chcp 65001 >nul
cd /d "%~dp0"
:loop
python app\run_bot.py
echo.
echo [bot] Process exited, restarting in 10s...
timeout /t 10 /nobreak
goto loop
