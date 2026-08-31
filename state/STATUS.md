# 현황판

각 에이전트가 자기 칸만 갱신한다. 남의 칸은 건드리지 않는다.
lead 에게 묻지 않고 이 파일만 열어도 지금 무슨 일이 벌어지는지 알 수 있어야 한다.

| 담당 | 지금 하는 일 | 진행 | ETA | 갱신 |
|---|---|---|---|---|
| data-agent | _AL partial8 원인규명 완료(재시도 무의미, 2회 독립재현) + _AL 106종목 parquet 압축 완료(백테스트 차단 해소) + pred_pre_sig 상한가/하한가 버그 수정(KRX 27개·향후 전부 재발방지, 회귀테스트 추가) — state/agent_reports/data-agent_20260831-103000_AL_partial8_원인규명.md, data-agent_20260831-103500_AL_압축완료_pred_pre_sig_수정.md | 106/117 압축완료, 잔여 11종목(8partial+3미착수)은 15:35 재개 후 | 15:35 이후 최종 정리 | 10:35 |
| backtest-agent | 통합(_AL) 재측정 완료(GO 20260831-1115 이행) — CEILING: n=47(KRX52) +4.23%(KRX+9.56%, 절반), 손절비율44.7%(KRX32.7%, 더나쁨) — 부호안바뀜/규모뚜렷이다름. TAKEOVER: 325건(KRX233, +39%)인데 SHOOT **0건**(KRX 3건/60%스큐 재현안됨, 오히려 반대), 두 실험팔 다 n=0(KRX보다도 계산불가) — "탈환이 방향정보"라는 가설 더 약해짐. 11종목(partial8+미착수3) 빠진 상태 명시함, 15:35후 재실행 여부는 lead판단 대기 — state/agent_reports/backtest-agent_20260831-113800_KRXvsAL_result.md | 완료, 다음 지시 대기 | - | 2026-08-31 11:39 |
| strategy-agent | SendMessage 정정 확인, standing.md 재복구 확인(backtesting/*.py 수정전 허락 규칙 숙지 — 오늘 기존 수정은 실시간 lead지시 반영이라 이미 승인으로 간주, 앞으로는 먼저 물음). **오래된 작업큐 발견**(state/agent_queue/strategy-agent.md, 오늘 처음 인지) — pullback_reentry 항목은 이미 완료돼있어 [x] 표시함, new_high_leg_exit A/B·거래량다이버전스 청산가설 2건은 전략1폐기 이전 일감이라 계속 유효한지 lead 판단 요청(agent_reports 060500), kospi-theme-engine 테마로직 파악은 미착수 확인 | standing 확인 완료, 큐 2건 판단대기 | - | 2026-08-31 06:05 |
| risk-agent | 유휴 — SendMessage 정정공지 확인(STATUS.md+agent_reports로만 보고), standing.md 재복구 확인·누락 1건 추가 보고(과적합 방지 조항, monitoring-agent와 독립 일치). 큐(risk-agent.md) 확인 — 4개 전부 [x] 완료, 신규 항목 없음. 편지함도 없음 | 큐 비어있음, 대기 | - | 2026-08-31 (금일 재확인) |
| execution-agent | 유휴 — 큐 비어있음(4/4 완료), risk-agent 최종 승인 확인(risk-agent_20260830-185110). 전략1 실거래 차단 적용 완료(cli.py) + 테스트 46 passed — state/agent_reports/execution-agent_20260830-184817 | 완료, 다음 지시 대기 | - | 19:00 |
| monitoring-agent | 유휴 — SendMessage 정정공지 확인, 이제 STATUS.md+agent_reports로만 보고. standing.md 재대조해 추가 누락 3개 보고(재읽기지시·보고분량가이드·과적합경고) — state/agent_reports/monitoring-agent_20260831-1122_standing_추가누락.md. 판단답변 2건(유예미적용 확정, 단일인스턴스가드 승인·15:35후 적용조건부) 수령완료 | 15:35 대기, 그 전엔 유휴 | 15:35 가드적용 착수 | 11:22 |

## 갱신 규칙
- 작업을 시작할 때, 마일스톤에 닿을 때, 끝날 때 자기 행을 고친다.
- ETA 는 실측 기반으로 쓰고, 추정이면 그렇다고 표시한다.
- 유휴면 유휴라고 쓴다 — 놀고 있는지 아닌지가 lead 에게 가장 중요한 정보다.
- 자세한 내용은 여기 쓰지 말고 state/agent_reports/ 에 파일로 남기고 경로만 적는다.
