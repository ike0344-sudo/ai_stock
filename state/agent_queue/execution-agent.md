# execution-agent 큐

- [x] 실거래 게이트 날짜 검증 마무리 (진행 중이면 그것부터)
- [x] ka10075 필드명 실계좌 미검증 위험 — 모의투자로 최소 1회 실주문을 넣어
      필드가 실제로 어떻게 오는지 확인할 수 있는지 판단해라. 가능하면 절차를
      제안만 하고 실행은 사용자 승인 후. 불가능하면 왜인지 밝혀라.
      → state/agent_reports/execution-agent_20260830-092507.md (판단: 가능, 절차 제안, 실행 안 함)
- [x] 주문 실패 시나리오 정리 — 부분체결, 타임아웃 취소 실패, 재시작 중 미체결,
      API 응답 지연. 각각 지금 코드가 어떻게 행동하고 무엇이 안 막혀 있는지.
      → state/agent_reports/execution-agent_20260830-092555.md (핵심 위험 2건: 취소실패 무한재시도 무알림, 재시작복원 실패 시 조용히 고아됨)
- [x] 실거래 첫 주문 리허설 절차 문서화 — 모의에서 무엇을 확인하고 넘어가야 하는지
      순서대로. state/agent_reports/ 에 남겨라.
      → state/agent_reports/execution-agent_20260830-092641.md, risk-agent와 6·7단계 겹쳐 편지 조율 요청함(state/agent_mail/risk-agent/20260830-092708_live-rehearsal-overlap.md)

- [x] (전 단계 완료 2026-09-26 00:10. 보고: state/agent_reports/execution-agent_20260925-235546_8765_dual_bind.md) (lead 지시 2026-09-26 00:10 — **사용자 직접 "지금 바로 고쳐줘"**) **8765 대시보드를 127.0.0.1 과 테일스케일 주소 둘 다에서 받게**
      사실(lead 실측 00:00): 8765 는 살아 있다(PID 41388, 18:44~, 부모 = 워치독). 그런데 **100.126.113.127:8765(테일스케일)에만 바인딩**돼 있어서 이 PC 에서
      `http://localhost:8765`·`127.0.0.1:8765` 는 연결 거부 → 사용자에겐 "계속 죽어 있음"으로 보인다. 테일스케일 주소로는 200.
      지금 설정의 의도(`run_dashboard.bat` 주석, `nasdaq_monitor_watchdog.ps1` 25~30행 주석): 휴대폰은 테일스케일로 보고, 인증 없는 실주문 화면이라 집 와이파이(0.0.0.0)엔 안 연다 — **이 의도는 지킨다.**
      1. `backtesting/dashboard_server.py`·`backtesting/cli.py`: `--host` 에 쉼표 목록 허용(`127.0.0.1,100.126.113.127`). 주소마다 `build_server()` 로 서버 하나씩(같은 핸들러), 스레드로 serve.
         **127.0.0.1 은 반드시 성공**해야 하고, 테일스케일 바인딩이 실패하면(테일스케일이 아직 안 떴을 때) 경고를 남기고 60초마다 다시 시도한다(로컬은 계속 서비스). 종료 시 둘 다 닫기
      2. `_origin_is_trusted` 는 Host 헤더 기준이라 두 주소 모두 그대로 맞아야 한다 — 테스트로 확인(각 주소에서 같은 출처 통과, 위조 Origin 403)
      3. `nasdaq_monitor_watchdog.ps1` — **먼저 `state/_tmp/` 에 백업**. 바꿀 곳: 35행 8765 대상의 Args `--host` 를 두 주소로, 같은 줄 `Url` 을 `http://127.0.0.1:8765/`(프로세스 생존 확인용), 222~223행 순위 API 호출도 127.0.0.1 로.
         **34행 `monitor-dashboard`(텔레그램 다운 알림)는 테일스케일 주소 그대로 둔다**(휴대폰 접속이 끊긴 걸 알리는 용도). 파일 인코딩 유지: **BOM(EF BB BF)·CRLF·단독 CR 0**, PowerShell 파서 오류 0 — 편집 뒤 바이트로 확인
      4. `run_dashboard.bat` 도 두 주소로 + 주석 갱신("이 PC 는 localhost, 휴대폰은 테일스케일")
      5. 적용: 돌던 워치독(지금 PID 42256, `nasdaq_monitor_watchdog.ps1` 명령줄)**만** 종료 → `explorer.exe "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\nasdaq_monitor_watchdog_launcher.vbs"` 로 다시 기동
         (도구 세션의 자식이 되지 않게 explorer 경유). 새 워치독 첫 주기가 127.0.0.1 프로브에 실패한 옛 8765 를 정리하고 새 인자로 다시 띄운다 — `state/watchdog/restarts.log` 에 기록되는지 확인
      6. 확인: `http://127.0.0.1:8765/`·`http://localhost:8765/`·`http://100.126.113.127:8765/` 모두 200 · 위조 Origin POST 403(두 주소 각각, **`/api/top35-update` 로만**) ·
         나스닥 감시 PID 10832 불변 · 8780(`-m studio`) 생존 · 워치독 1개 · 5분 한 주기 뒤 8765 PID 불변·`monitor-dashboard` 거짓 다운 알림 없음
      **금지**: 실주문, `KIWOOM_IS_MOCK` 변경, 신뢰된 Origin 으로 POST 보내기(매도·킬스위치·전략 시작 등 어떤 POST 도 — 403 확인용 위조 요청만), 나스닥 감시 종료. 문제가 생기면 백업으로 즉시 되돌리고 보고.
      git commit 금지. 보고: STATUS.md 자기 행 + `state/agent_reports/execution-agent_<날짜시각>_8765_dual_bind.md`.
