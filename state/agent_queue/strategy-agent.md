# strategy-agent 큐

- [>] new_high_leg_exit A/B 결과 오면 청산가설 A 검증 결과 해석
- [>] 청산가설 B(추격매수 소진, 거래량 다이버전스) 구현 여부 판단 — A 결과 보고
- [x] pullback_reentry 처리 확정 (재가설 / 조건 수정 / 폐기) — 이미 완료:
      가설 기각으로 폐기, `pullback_reentry.py` 자체 docstring에 [폐기됨]
      명시 + `strategies/__init__.py` __all__에서 제외(파일은 안 지움).
      순서 무시하고 먼저 체크함(이 큐 존재를 오늘 처음 인지, 이미 끝난
      항목이라 확인 즉시 표시) — 상세는 아래 §1~2 미해결분과 별개임.
- [x] kospi-theme-engine app/engine/ 테마 점수 로직 파악 — 가중치는 바꾸지 말 것
      완료(읽기전용, 가중치 미변경) — state/agent_reports/strategy-agent_20260831-171500_kospi-theme-score-review.md
- [x] 가설 3개 제안 (상시임무 신설분) — lead 지시로 주제를 "장시작60분 테마순위"로 지정,
      highs축 제외 3축(H1 변화vs레벨/H2 chgtop고정성/H3 leader-vs-top_gainer, H3는 원본에
      2등주 데이터 없어 재정의)으로 사전등록 완료 —
      state/agent_reports/strategy-agent_20260831-2240_theme_rank_prereg.md.
      backtest-agent 측정 의뢰 편지 발송 완료(2245) → **보류 요청함(2312)**: 41일
      아카이브 중 5일(0702~0708, IS구간)이 다른시점 재생성돼 비균일함을 뒤늦게 확인
      (data-agent_20260831-2035). data-agent 41일 재정비 후 재의뢰 예정, 그때까지 대기.
