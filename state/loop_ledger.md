# lead-loop 원장

매 회차 한 줄. **이 파일을 안 읽으면 같은 상태를 보고 같은 지시를 다시 낸다** — 되먹임 기록이
없는 루프가 제자리를 도는 게 ralph 계열의 전형적 실패다. 절차는 `.claude/skills/lead-loop/SKILL.md`.

회차 20 을 넘으면 무조건 멈춘다. `한 것`이 "대기"뿐인 회차가 3연속이면 무엇을 기다리는지 명시하고,
못 쓰겠으면 그때가 멈출 때다.

| 회차 | 시각 | 본 것 | 한 것 | 다음 |
|---|---|---|---|---|
| 1 | 2026-08-31 20:30 | blocked 0 · 열린큐 6(backtest) · 미배달 2 · 요청 1 · 새 리포트 3건(prereg 2240, 측정의뢰 2245, session_boundary 1951) | backtest 의 [요청] 판정 편지(ret_eod → ret_session_last 개명, SESSION_END 확장 금지, 진짜 종가는 일봉 close) + strategy 편지복사 재발 통지 | poke 가 배달 → backtest 가 정정·개명 후 큐 6건, strategy 는 정리 후 유휴 |
| 2 | 2026-08-31 20:40 | 4개 working · 미배달 4 · 요청 2 · data-agent 재생성 리포트(2035): **41일 배치 중단**, 참조데이터 08-31 10:49 갱신 + 미커밋 KRX→AL 12파일 + 기존 아카이브 5일치 이미 재생성됨 → 재현 불가 | data-agent 에 보류 판단 편지(1=사람게이트 대기, 2=monitoring 이관, 3=AL 채택, 4=60분+15:30 동시생성 권고 채택). 사용자에게 커밋 게이트 상신 | 커밋 결정 대기. 그 사이 backtest(큐6+ret_eod)·strategy 진행분 회수 |
| 3 | 2026-08-31 20:33 | strategy-agent 2300 리포트: **lead 가 두 번 틀렸다** — 그 pane 엔 Bash 가 없다(`Bash is disabled for this session`). 에이전트 정의상 Read/Write/Edit/Grep/Glob 뿐이라 mv/rm 원천 불가 | 근본수정: agent-poke 가 `read/` 에 동명 사본 있으면 처리된 편지로 셈(공유 함수 1곳). strategy standing.md 도구줄 정정 + "Write 사본이면 처리 완료" 규칙. 잔여 원본 2건 lead 가 삭제. poke 재기동 | strategy 는 이제 안 깨워짐. backtest 3건 처리 대기 |
