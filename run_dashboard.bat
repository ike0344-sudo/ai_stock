@echo off
cd /d "%~dp0"
python -m backtesting.cli dashboard --port 8765
pause
