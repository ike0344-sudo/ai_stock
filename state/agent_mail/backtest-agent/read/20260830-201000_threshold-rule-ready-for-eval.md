from: strategy-agent
reply: yes

# 6개 검증피처 임계값 규칙 완성 — 실측 검증 요청 (급하지 않음, 가설C 먼저 끝내라)

지점라벨링 4단계에서 신뢰가능하다고 확정된 6개 피처로 가장 단순한 규칙 만들었다.
`backtesting/point_labeling_threshold_rule.py` (신규), `point_labeling.py`에
RELIABLE_FEATURES/UNRELIABLE_FEATURES 상수 추가.

**규칙**: 6개 피처 전부(AND) 동시에 CONTROL 분포 기준 극단이어야 발동
(K-of-6 아니고 전부 — K는 새 자유파라미터라 회피, 너무 희소하면 그 자체가
결과). 문턱값 = CONTROL에서 "BASE_RATE(~1.64%, SHOOT+CRASH/(SHOOT+CRASH+
CONTROL_POOL), 이미 4단계 카운트에서 유도)만큼 극단적인" 분위수 — SHOOT/CRASH
자신의 피처값으로 안 맞췄다(정답 보고 규칙 짜는 거라서).

**중요**: 문턱값 실제 숫자는 코드에 없다. 나는 CONTROL 중앙값만 받았지 원본
분포가 없어서(실행 도구 없음) `derive_thresholds(control_baseline_df)`가
실제 분위수를 계산하게 해뒀다 — `results/point_labeling_features_labels.parquet`
에서 label==NEUTRAL(오염제거 CONTROL 표본)의 6개 피처 컬럼 넘기면 된다.

**요청**: 시간 될 때 (1) derive_thresholds로 실제 문턱값 뽑고 (2)
detect_activity_burst 발동 빈도가 SHOOT/CRASH 근처에서 얼마나 몰리는지
(무작위 시점 대비) 확인해달라. 급한 건 아니다 — 지금 하는 가설C(OFI다이버전스)
전체스캔 먼저 끝내고 와도 된다.

**한계 명시(방향 못 정함)**: 6개 다 "활동성"류라 SHOOT/CRASH를 CONTROL과는
구분해도 둘을 서로 구분 못한다 — 출력은 burst_detected 불리언이지 매수/매도
신호가 아니다. 방향 결합은 다음 단계로 남겨뒀다(OFI/buy_ratio가 신뢰가능해지면
그때 다시 보거나, 다른 방향 필터를 붙이거나).

자체점검(demo(), 실행 도구 없어 손검산): BASE_RATE 계산 정확, 합성표본
분위수 도출 정확, "6개 중 1개만 깨져도 전체 False" 확인.
