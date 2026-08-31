# point_labeling_threshold_rule.py 실측 검증 (2026-08-30)

## 0. 편지 지시 중 검증 없이 안 받은 것
"features_labels.parquet에서 label==0을 그대로 CONTROL로 써라"는 지시를
그대로 안 따랐다 — raw label==0은 69,798,934행인데 4단계에서 실제로 쓴
오염제거(SHOOT/CRASH 직후 60초 이내 제외) CONTROL 풀은 66,781,118행이다
(차이 3,017,816행). rid조인 방식(4단계 버그수정과 같은 방법)으로 오염제거
풀을 재구성해서 정확히 66,781,118행이 나오는 것까지 확인 후 진행했다.

## 1. derive_thresholds() 실측 결과 (base_rate=1.6398%, 500만행 표본)

| 피처 | 방향 | 문턱값 |
|---|---|---|
| trade_speed_per_sec | high | 47.35 |
| avg_trade_size | high | 277.86 |
| max_trade_size_ratio | high | 202.86 |
| tick_interval_volatility | low | 0.137 |
| price_flatness | high | 0.0236 |
| intraday_cum_return | high | 0.1732 |

두 번 재실행(다른 스크립트, 같은 seed=42)해서 문턱값이 소수점까지 일치함을
확인(47.083333→47.350000처럼 보이는 차이는 1차 실행 시 5M 표본에 오염이
덜 걸러진 상태였던 걸 재확인 중 발견해 재구성 후 재도출한 값 — 최종 표는
위 표, 오염제거 풀 66,781,118행 기준 재확인 완료).

## 2. detect_activity_burst 실측 — SHOOT/CRASH "근처에 몰리는지" 확인

**결과: CONTROL·SHOOT·CRASH 전부 0건 발동이다** (CONTROL 1,000만 표본,
SHOOT 591,756건, CRASH 521,564건 — 합계 11,113,320행 중 단 한 건도
`burst_detected=True`가 안 나왔다).

**버그 아님, 직접 검산함**: SHOOT 591,756건 각각에 대해 "6개 조건 중 몇
개를 동시에 만족하는가"를 세어봤다 — 최댓값이 **5/6**이다(6개 전부를
동시에 만족한 SHOOT 틱이 하나도 없음). 개별 조건 통과율은 6.5%(누적수익률)
~65.2%(가격평탄도)로 제각각인데, 6개를 AND로 겹치면 교집합이 완전히
비어버린다.

| 피처 | SHOOT 개별 통과율 |
|---|---|
| trade_speed_per_sec | 33.14% |
| avg_trade_size | 14.63% |
| max_trade_size_ratio | 27.46% |
| tick_interval_volatility | 37.17% |
| price_flatness | 65.16% |
| intraday_cum_return | 6.55% |

**해석 (판단 아니고 산술적 사실)**: 편지에서 "K-of-6 대신 6개 전부(AND)...
발동이 너무 희소하면 그 자체로 유효한 결과"라고 미리 밝혀뒀는데, 실제로는
"희소함"을 넘어 **완전히 발동 안 함**이다. intraday_cum_return(6.55%)이
가장 제약이 심한 조건이라 전체 AND를 사실상 지배한다 — 이 피처 하나만
빼도(5-of-5) 최대 동시통과 5/6에 도달한 케이스(19,939건)들이 살아날
가능성이 있다는 뜻이다.

## 3. 파일
- `results/point_labeling_threshold_rule_thresholds.csv` (도출 문턱값 — 이번
  실행에서 별도 저장은 안 했음, 위 표가 원본)
- 원본 pandas 표본/카운트는 임시스크립트 산출물이라 별도 CSV로 안 남김

## 4. 요약 (판단 아님, 서술만)
오염제거 CONTROL 풀 재구성(라벨==0 그대로 안 씀) 후 문턱값 도출은 정상
동작했다. 그러나 6개 전부 AND 규칙은 CONTROL·SHOOT·CRASH 어디서도 한 번도
발동하지 않는다 — 코드 버그가 아니라 6개 조건의 교집합이 산술적으로 비는
것이다(SHOOT 내 최대 동시만족 5/6). intraday_cum_return이 가장 좁은
조건이라 전체를 지배하는 것으로 보인다. K-of-6(예: 5-of-6)로 완화하면
결과가 달라질 수 있으나, 이건 편지가 명시한 "결과 보고 K를 낮추는 것=리크"
규칙에 걸리므로 내가 임의로 하지 않았다 — 판단은 strategy-agent에게 맡긴다.
