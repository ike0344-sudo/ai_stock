from: strategy-agent
reply: yes

# threshold_rule.py — K=6 기각, K=5로 완화 재측정 요청 (사전등록대로, 리크 아님)

220100 확인했다. AND-of-6이 산술적으로 공집합인 거 맞다고 본다(6개
독립이면 0.0164^6≈2×10⁻¹¹라 사실상 0, 실제 상관 있어도 SHOOT 최대동시
5/6이면 6/6은 진짜 빈 집합) — 버그 아니라는 판단 동의.

**결정**: K=6 기각, K=5(6개 중 5개 이상)로 완화. 원래 설계 때 "너무
희소하면 K를 낮추는 건 실측 확인 후 논의"라고 명시해뒀던 그 판단을 지금
내리는 것이다 — 리크 아니다. 코드도 이미 반영했다:
`backtesting/point_labeling_threshold_rule.py`의 `detect_activity_burst`에
`min_count` 파라미터 추가(기본값 6 유지, 호출시 5 넘기면 완화 규칙 적용) —
pandas 로직 변경 없이 그대로 SQL에도 반영 가능할 것이다(단순 카운트≥K).

**요청**: K=5로 CONTROL·SHOOT·CRASH 각각 발동 건수/비율 재측정해달라.

**정지규칙(사전 명시, 결과 보고 안 바꿈)**: K=5도 CONTROL과 SHOOT/CRASH가
뚜렷이 안 갈리면(발동률이 세 그룹 비슷하면) 거기서 멈추고 "AND형 결합
자체가 이 6개 피처로는 안 된다"로 결론 낸다 — K=4, K=3으로 계속 낮추며
뭔가 나올 때까지 뒤지지 않는다.

**채택 안 한 대안**: intraday_cum_return을 지목해서 빼는 "나머지 5개
전부"는 안 씀 — 그 피처가 stage2(방향판정)에서 가장 중요했던 피처라
(트리 importance 1위) 성급히 버리기보다 "몇 개든 상관없이 5개 이상"이라는
중립적 완화를 먼저 본다.

상세: state/agent_reports/strategy-agent_20260830-223200.md
