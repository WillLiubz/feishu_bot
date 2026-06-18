@echo off
cd /d "%~dp0"
start "飞书Bot" cmd /k "python app\run_bot.py"
start "日志查看" cmd /k "python app\logview.py"
