@echo off
cd /d "%~dp0"
REM 백테스트 스튜디오 서버. 127.0.0.1 에만 연다(코드에 고정) - 이 PC 브라우저에서 http://127.0.0.1:8780/
REM 포트는 STUDIO_PORT 로 바꿀 수 있다. 화면(static\studio)은 frontend 에서 npm run build 로 만든다.
REM 상시 가동(워치독 등록)은 서버가 안정된 뒤 따로 한다 - 지금은 손으로 띄우는 용도.
python -m studio
pause
