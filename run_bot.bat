@echo off
cd /d "%~dp0"
:loop
python app\run_bot.py
echo.
echo [bot] 进程退出，10 秒后自动重启...
timeout /t 10 /nobreak
goto loop
