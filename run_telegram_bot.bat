@echo off
cd /d "%~dp0"
python -m backtesting.cli telegram-bot
pause
