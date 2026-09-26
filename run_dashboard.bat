@echo off
cd /d "%~dp0"
REM --host: 이 PC(127.0.0.1)와 Tailscale 주소 두 곳에서 받는다. 인증 없는 실주문 화면이라
REM 0.0.0.0 으로 두면 집 와이파이 전체에 열린다(python.exe 인바운드 Allow 규칙이 Public 프로필에
REM 이미 있음) — 그래서 두 주소만. 이 PC 는 http://localhost:8765/, 휴대폰은 http://100.126.113.127:8765/
REM 자세한 근거는 nasdaq_monitor_watchdog.ps1 의 $dashboardHost 주석 참고.
python -m backtesting.cli dashboard --port 8765 --host 127.0.0.1,100.126.113.127
pause
