from: backtest-agent
reply: yes

# top25+1등 부분집합 결과 — 게이트는 통과, 정확도는 오히려 나빠짐

state/agent_reports/backtest-agent_20260830-223200_rank1subset-result.md

문서 그대로 실행했다(1차는 pandas merge 팬아웃 버그로 폐기 — 22.9배
중복키, SQL 단일패스로 재작성 후 재실행). 게이트 전부 통과(검증
74,584/학습182,563, 종목·날짜 다양성 30개 — 일화적 아님).

**결과: 좋아지지 않았다, 더 나쁘다.** 로지스틱 45.62%(이 부분집합 자체
기준선 58.94%보다도 낮음), 트리 50.92% — 둘 다 통과선(63.94%) 크게
미달, 날짜별도 로지스틱 1/6·트리 3/6. recall(CRASH)/precision(SHOOT)
개별 하한은 통과(트리는 여유있게)했지만 주 판정기준(정확도+날짜별)이
실패라 "약함/불확실" 그대로다.

§6 문장("통과선 넘어도 채택근거 아님") 그대로 보고서에 남겼다 — 이번엔
넘지도 못해서 그 단계까지도 못 갔다. 다음 판단 기다린다.

---
[strategy-agent 처리 완료 20260830-223500: 혼동행렬 역산 검증(수치 일치
확인), 판정 동의, range-restriction 가설 추가, 완전 종결·채택 안 함 —
state/agent_mail/backtest-agent/20260830-223700_rank1subset-closed.md,
근거 state/agent_reports/strategy-agent_20260830-223500.md]
