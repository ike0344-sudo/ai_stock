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
      backtest-agent 측정 의뢰(2245) → 오염 발견으로 보류(2312) → lead 판단(옵션2,
      오염7일 제외) 반영해 재개(2355) → **측정결과(잠정) 수령·검증 완료: H1 기각,
      H2 기각, H3 판단보류 — 3개 다 미채택**
      (state/agent_reports/strategy-agent_20260901-0010_theme_rank_result_verified_all_rejected.md).
      standing.md 규율대로 새 가설 스스로 안 만듦 — STATUS.md에 "방향 재설정 필요"로
      lead 판단 요청 올림. **41일 균일본 최종 재측정 결과 수령·검증·사전등록 갱신
      완료: H1/H2 기각 유지(크기만 변화), H3는 표본충족(19→25)돼 판단보류→기각으로
      확정 — 3축 다 최종 기각.** 사전등록 문서(2240)에 최종 확정 배너 추가.
- [x] [lead 방향재설정, 2026-09-01] 일봉 3축 사전등록 — H1 눌림후반등/H2 CLV(순매도우세
      데이터제약 재정의)/H3 갭vs장중전용, IS 2019~2024/OOS 2025~2026-08, 리밸런스5거래일
      비중첩 — state/agent_reports/strategy-agent_20260901-0040_daily_bar_prereg.md.
      backtest-agent 측정 의뢰 발송 완료(0045). **결과: H1/H2/H3 전부 기각**(핵심발견:
      H1 총수익 전부 갭에서 나옴, 장중전용은 t=-3.94로 유의하게 마이너스 — 틱 라운드와
      교차검증) — 독립검증(산출물 행수·표본수 대조) 완료, 결론 수용.
- [x] [lead, 2026-09-01 01:00] **3라운드 보류 — 사용자 판단 대기.** 두 라운드(틱/일봉)
      연속 전부 기각, "갭이 전부다"가 두 번 독립 확인됨. 새 가설 스스로 안 만듦, 지시대로
      유휴 전환. 사용자가 방향 정하면 재개.
