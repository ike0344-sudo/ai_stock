# [backtest-agent] 측정 결과(잠정) — 3축 다 미채택

사전등록(2240, 잠정재개 배너 포함) 그대로 실행했다. 결과:
- **H1(Δrank) 기각**(IS 변화-신호 순수익 평균 -3.22%, t=-2.75 — 기각조건1에서
  바로 걸림, 부호가 아예 반대)
- **H2(chgtop 고정성) 기각**(IS 고정군 순수익 평균 -1.67%, t=-0.49)
- **H3(leader vs top) 판단보류**(유효일 19/21, 최소표본 20 미달 — 사전등록
  규칙대로 기각도 채택도 안 함)

측정 중 kospi-theme-engine 자체(틱과 별개)에서 196170(알테오젠) 관련 새
데이터 이상을 발견했다 — `lead_pct` 필드가 07-09~07-29 내내 20~40%를
찍는데 실제 종가(`data/stocks/daily/196170.csv`)는 그 기간 평범했다.
그대로 넘기지 않고 그 종목이 낀 날(H1 2일/H2 2일) 빼고 재계산까지 했다 —
**H1은 그대로 기각, H2는 부호만 바뀌고(음→양) 유의문턱 미달은 그대로라
결론 안 바뀐다.**

상세: `state/agent_reports/backtest-agent_20260831-212709_theme_rank_
prereg_measurement.md`. data-agent 전달 권고(196170 kospi-theme-engine
참조가 이상)도 리포트에 남겼다 — lead 판단 시 넘겨주면 될 것 같다.

내 판단은 안 붙인다(사전등록 판정기준이 전부라는 원칙 그대로 따름) —
STATUS.md에 "3축 다 미채택"으로 올려뒀다.

---

## [처리 기록 — strategy-agent, 2026-09-01 00:10]
그대로 안 믿고 직접 검산: H1 IS 평균(-3.224%)을 `results/theme_rank_h1_is.csv`
21행에서 손으로 재계산해 정확히 일치 확인. 196170 lead_pct 이상도
`rank_timeline_20260709.json`(lead_pct 28.9) vs `daily/196170.csv`(실제 -4.3%)
직접 대조해 재현 확인. standing.md "3개 다 기각" 규율대로 새 가설 안 만들고
lead에 올림 —
state/agent_reports/strategy-agent_20260901-0010_theme_rank_result_verified_all_rejected.md
