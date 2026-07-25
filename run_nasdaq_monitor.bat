@echo off
cd /d "%~dp0"
python -m backtesting.cli monitor-nasdaq-drop
pause
