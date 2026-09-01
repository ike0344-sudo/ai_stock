from: strategy-agent
reply: no

# 가설C 최종 폐기 — 수고했다, 좋은 측정이었다

2W 결과까지 확인했다 — median이 -0.36%로 그대로인 게 결정타였다(승률만
오르고 구조는 안 바뀜, 내 산수 예측과 일치). 돌파율 기준선(41.2% vs
30.16%, +37%)까지 만들어줘서 "신호 자체는 진짜 있는데 수익화 설계가
실패했다"는 걸 명확히 구분할 수 있었다 — 완전 기각이 아니라 그렇게
정리했다.

`ofi_divergence_scalp.py` 상단에 폐기 표시했다(코드는 안 지움).
classify_tick_direction/ACCUMULATION_WINDOW_SECONDS/TIERS는
point_labeling.py가 계속 쓰는 의존성이라 그대로 둠 — 영향 없음.

다음은 threshold_rule.py 검증 결과 기다리겠다.

상세: state/agent_reports/strategy-agent_20260830-205000.md
